from __future__ import annotations

import asyncio
import random
from datetime import datetime
import httpx
import pandas as pd
import yfinance as yf

from scanner.cache import cache
from scanner.config import CONFIG, logger
from scanner.scoring.momentum import compute_analyst_revision_3m
from scanner.notifier import notify_fmp_unavailable

# TTL en secondes
TTL_FUNDAMENTALS = 24 * 3600
TTL_PRICES = 4 * 3600

SECTOR_ETFS = ["XLK", "XLV", "XLF", "XLY", "XLP", "XLI", "XLE", "XLB", "XLRE", "XLU", "XLC", "SPY"]


class FMPUnavailableError(Exception):
    """Levée quand FMP est inaccessible (clé absente ou 5xx après fmp_max_retries tentatives)."""
    pass


async def fetch_prices_batch(tickers, period="1y"):
    """
    Télécharge les prix historiques pour une liste de tickers via yfinance.
    Délégué à un thread pour ne pas bloquer l'event loop.
    """
    if not tickers:
        return pd.DataFrame()

    logger.info(f"Téléchargement des prix pour {len(tickers)} tickers...")
    try:
        data = await asyncio.to_thread(
            yf.download,
            tickers=" ".join(tickers),
            period=period,
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True
        )
        return data
    except Exception as e:
        logger.error(f"Erreur lors du batch download: {e}")
        return pd.DataFrame()

async def fetch_fmp_data(client, symbol):
    """
    Récupère les fondamentaux institutionnels via Financial Modeling Prep (httpx async).
    Lève FMPUnavailableError si clé absente ou 5xx persistant après fmp_max_retries.
    """
    api_key = CONFIG["scanner"].get("fmp_api_key")
    base_url = CONFIG["scanner"].get("fmp_base_url")

    if not api_key or api_key.startswith("${"):
        raise FMPUnavailableError("Clé FMP absente ou non configurée.")

    max_retries = CONFIG["scanner"].get("fmp_max_retries", 2)

    for attempt in range(max_retries):
        try:
            responses = await asyncio.gather(
                client.get(f"{base_url}/ratios-ttm/{symbol}?apikey={api_key}"),
                client.get(f"{base_url}/key-metrics-ttm/{symbol}?apikey={api_key}"),
                client.get(f"{base_url}/profile/{symbol}?apikey={api_key}"),
                client.get(f"{base_url}/income-statement/{symbol}?limit=3&apikey={api_key}"),
                client.get(f"{base_url}/balance-sheet-statement/{symbol}?limit=3&apikey={api_key}"),
                client.get(f"{base_url}/earnings-surprises/{symbol}?apikey={api_key}"),
                client.get(f"{base_url}/analyst-estimates/{symbol}?period=quarter&limit=3&apikey={api_key}"),
            )

            if any(resp.status_code >= 500 for resp in responses):
                if attempt < max_retries - 1:
                    await asyncio.sleep(random.uniform(0.8, 1.5))
                    continue
                raise FMPUnavailableError(f"FMP 5xx persistant après {max_retries} tentatives pour {symbol}.")

            if all(resp.status_code == 200 for resp in responses):
                r_data = responses[0].json()
                k_data = responses[1].json()
                p_data = responses[2].json()
                is_data = responses[3].json()
                bs_data = responses[4].json()
                s_data = responses[5].json()
                a_data = responses[6].json()

                if r_data and k_data and p_data:
                    r = r_data[0]
                    k = k_data[0]
                    p = p_data[0]

                    surprise_pct = 0.0
                    surprise_date = None
                    if s_data and len(s_data) > 0:
                        surprise_pct = s_data[0].get("surprisePercentage", 0) / 100.0
                        surprise_date = s_data[0].get("date")

                    analyst_revision_3m = compute_analyst_revision_3m(a_data) if a_data else None

                    # Gap 2: date FMP → timestamp compatible data_freshness_check (filters.py)
                    most_recent_quarter_ts = None
                    if is_data and len(is_data) > 0:
                        date_str = is_data[0].get("date")
                        if date_str:
                            try:
                                most_recent_quarter_ts = datetime.fromisoformat(date_str).timestamp()
                            except ValueError:
                                pass

                    roe_3y = None
                    if is_data and bs_data and len(is_data) >= 3 and len(bs_data) >= 3:
                        roes = []
                        for i in range(min(3, len(is_data), len(bs_data))):
                            ni = is_data[i].get("netIncome", 0)
                            te = bs_data[i].get("totalStockholdersEquity", 1)
                            if te and te > 0:
                                roes.append(ni / te)
                        if roes:
                            roe_3y = sum(roes) / len(roes)

                    return {
                        "symbol": symbol,
                        "longName": p.get("companyName"),
                        "sector": p.get("sector"),
                        "marketCap": p.get("mktCap"),
                        "returnOnEquity": roe_3y,
                        "roe_ttm": r.get("returnOnEquityTTM"),
                        "roe_3y": roe_3y,
                        "operatingMargins": r.get("operatingProfitMarginTTM"),
                        "totalDebt": k.get("totalDebtTTM"),
                        "totalCash": None,
                        "netDebt": k.get("netDebtTTM"),
                        "ebitda": k.get("ebitdaTTM"),
                        "freeCashflow": k.get("freeCashFlowTTM"),
                        "forwardPE": r.get("priceEarningsRatioTTM"),
                        "enterpriseToEbitda": r.get("enterpriseValueOverEBITDATTM"),
                        "pegRatio": r.get("pegRatioTTM"),
                        "surprise_pct": surprise_pct,
                        "surprise_date": surprise_date,
                        "analyst_revision_3m": analyst_revision_3m,
                        "mostRecentQuarter": most_recent_quarter_ts,
                        "source": "FMP",
                    }
            return None
        except FMPUnavailableError:
            raise
        except Exception as e:
            logger.error(f"Erreur API FMP pour {symbol}: {e}")
            return None

    return None

async def fetch_ticker_info(symbol, client=None):
    """
    Récupère les informations d'un ticker avec cache.
    Lève FMPUnavailableError si FMP indisponible.
    """
    cached_data = cache.get("fundamentals", symbol, TTL_FUNDAMENTALS)
    if cached_data:
        return cached_data

    info = None
    if client:
        info = await fetch_fmp_data(client, symbol)

    if info:
        cache.set("fundamentals", symbol, info)
    return info

async def fetch_market_indices():
    """Récupère l'historique du SPY et du VIX pour le Market Gate."""
    logger.info("Récupération du SPY et du VIX pour le Market Gate...")
    try:
        indices = await asyncio.to_thread(
            yf.download,
            tickers="SPY ^VIX",
            period="2y",
            progress=False,
            auto_adjust=True
        )
        return indices
    except Exception as e:
        logger.error(f"Erreur fetch indices marché: {e}")
        return pd.DataFrame()

async def fetch_all_data(tickers, etfs=None, prices_batch=None):
    """
    Orchestre la récupération de toutes les données de manière asynchrone et non-bloquante.
    Lève FMPUnavailableError si FMP est inaccessible (après notification Telegram).
    """
    if etfs is None:
        etfs = []

    all_tickers = list(set(tickers + etfs + SECTOR_ETFS))
    results = {}

    if prices_batch is None:
        prices_batch = await fetch_prices_batch(all_tickers)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            for i, symbol in enumerate(tickers):
                if i > 0:
                    await asyncio.sleep(random.uniform(0.8, 1.5))

                logger.info(f"Sniper : Récupération des fondamentaux pour {symbol}...")
                info = await fetch_ticker_info(symbol, client=client)

                prices = None
                if isinstance(prices_batch.columns, pd.MultiIndex):
                    if symbol in prices_batch.columns.levels[0]:
                        prices = prices_batch[symbol]

                results[symbol] = {
                    "info": info,
                    "prices": prices
                }
    except FMPUnavailableError:
        await notify_fmp_unavailable()
        raise

    for s_etf in list(set(etfs + SECTOR_ETFS)):
        prices = None
        if isinstance(prices_batch.columns, pd.MultiIndex):
            if s_etf in prices_batch.columns.levels[0]:
                prices = prices_batch[s_etf]

        results[s_etf] = {
            "info": {},
            "prices": prices
        }

    return results
