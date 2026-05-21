from __future__ import annotations

import asyncio
import random
from datetime import datetime
from typing import Any, Optional

import httpx
import pandas as pd
import yfinance as yf
from pydantic import BaseModel, model_validator
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from scanner.cache import cache
from scanner.config import CONFIG, logger
from scanner.notifier import notify_fmp_unavailable
from scanner.scoring.momentum import compute_analyst_revision_3m

# yfinance handles its own session natively via curl_cffi to bypass bot protections.
# Do not pass a custom requests Session.


def normalize_sector_name(sector: str | None) -> str:
    if not sector:
        return "Unknown"
    s = sector.strip()
    mapping = {
        "Financial Services": "Financials",
        "Financial": "Financials",
        "Healthcare": "Health Care",
        "Health Services": "Health Care",
        "Consumer Cyclical": "Consumer Discretionary",
        "Consumer Defensive": "Consumer Staples",
        "Basic Materials": "Materials",
        "Industrial Goods": "Industrials",
        "Technology": "Technology",
        "Energy": "Energy",
        "Real Estate": "Real Estate",
        "Utilities": "Utilities",
        "Communication Services": "Communication Services",
        "Industrials": "Industrials",
    }
    return mapping.get(s, s)


# TTL depuis config (anti race-condition : 27h > 24h pour éviter expiration 3 min avant scan 09h35)
TTL_FUNDAMENTALS = CONFIG["scanner"].get("cache_ttl_fundamentals", 97200)
TTL_PRICES = CONFIG["scanner"].get("cache_ttl_prices", 14400)

# Disjoncteur global FMP — réinitialisé à chaque scan dans main.py
fmp_call_counter: int = 0

SECTOR_ETFS = ["XLK", "XLV", "XLF", "XLY", "XLP", "XLI", "XLE", "XLB", "XLRE", "XLU", "XLC", "SPY"]


class FMPUnavailableError(Exception):
    """Levée quand FMP est inaccessible (clé absente ou 5xx après fmp_max_retries tentatives)."""

    pass


class _FMPBase(BaseModel):
    """Convertit les strings non-numériques en None avant validation (ex: 'N/A' → None)."""

    model_config = {"extra": "allow"}

    @model_validator(mode="before")
    @classmethod
    def _coerce_invalid_to_none(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        cleaned: dict = {}
        for k, v in data.items():
            if isinstance(v, str):
                try:
                    cleaned[k] = float(v)
                except (TypeError, ValueError):
                    cleaned[k] = None
            else:
                cleaned[k] = v
        return cleaned


class FMPRatiosTTM(_FMPBase):
    priceEarningsRatioTTM: Optional[float] = None
    enterpriseValueOverEBITDATTM: Optional[float] = None
    pegRatioTTM: Optional[float] = None
    operatingProfitMarginTTM: Optional[float] = None
    returnOnEquityTTM: Optional[float] = None


class FMPKeyMetricsTTM(_FMPBase):
    roicTTM: Optional[float] = None
    netDebtTTM: Optional[float] = None
    ebitdaTTM: Optional[float] = None
    totalDebtTTM: Optional[float] = None
    freeCashFlowTTM: Optional[float] = None
    bookValuePerShareTTM: Optional[float] = None


def _parse_fmp_response(raw: list | dict, model_class: type[_FMPBase], ticker: str) -> Optional[_FMPBase]:
    """Parse le premier élément d'une réponse FMP. Retourne None si invalide."""
    if not raw:
        return None
    item = raw[0] if isinstance(raw, list) else raw
    try:
        return model_class(**item)
    except Exception as e:
        logger.warning(f"FMP parse error [{ticker}] {model_class.__name__}: {e}")
        return None


def _is_fmp_server_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TimeoutException)


@retry(
    retry=retry_if_exception(_is_fmp_server_error),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
async def _fmp_get(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """GET FMP avec retry automatique sur 5xx/timeout (tenacity, max 2 tentatives)."""
    response = await client.get(url, timeout=10.0)
    if response.status_code >= 500:
        response.raise_for_status()
    return response


async def fetch_prices_batch(tickers, period="1y"):
    """
    Télécharge les prix OHLCV par chunks pour éviter le ban IP yfinance (HTTP 429).
    Chunks de YFINANCE_CHUNK_SIZE tickers max + pause YFINANCE_CHUNK_DELAY_S entre chunks.
    threads=False : évite les connexions simultanées qui déclenchent le ban.
    """
    if not tickers:
        return pd.DataFrame()

    chunk_size = CONFIG["scanner"].get("yfinance_chunk_size", 100)
    chunk_delay = CONFIG["scanner"].get("yfinance_chunk_delay_s", 2.0)
    min_valid_ratio = CONFIG["scanner"].get("min_valid_data_ratio", 0.60)
    chunks = [tickers[i : i + chunk_size] for i in range(0, len(tickers), chunk_size)]

    logger.info(f"Téléchargement des prix pour {len(tickers)} tickers en {len(chunks)} chunk(s) de {chunk_size}...")

    all_frames = []
    failed_chunks = 0

    for idx, chunk in enumerate(chunks):
        try:
            data = await asyncio.wait_for(
                asyncio.to_thread(
                    yf.download,
                    tickers=" ".join(chunk),
                    period=period,
                    group_by="ticker",
                    auto_adjust=True,
                    progress=False,
                    threads=False,  # Pas de multi-thread interne (amplifie les 429)
                ),
                timeout=60.0,
            )
            if not data.empty:
                valid_count = sum(
                    1
                    for s in chunk
                    if isinstance(data.columns, pd.MultiIndex) and s in data.columns.get_level_values(0)
                )
                if valid_count / len(chunk) < min_valid_ratio:
                    logger.warning(
                        f"Chunk {idx + 1}/{len(chunks)} : batch_partial_failure ({valid_count}/{len(chunk)} valides)"
                    )
                    failed_chunks += 1
                all_frames.append(data)
        except Exception as e:
            logger.error(f"Erreur chunk {idx + 1}/{len(chunks)}: {e}")
            failed_chunks += 1

        if idx < len(chunks) - 1:
            await asyncio.sleep(chunk_delay)

    if failed_chunks == len(chunks):
        logger.error("Tous les chunks ont échoué — fetch yfinance impossible")
        return pd.DataFrame()

    if not all_frames:
        return pd.DataFrame()

    return pd.concat(all_frames, axis=1) if len(all_frames) > 1 else all_frames[0]


async def fetch_fmp_data(client, symbol):
    """
    Récupère les fondamentaux institutionnels via Financial Modeling Prep (httpx async).
    Lève FMPUnavailableError si clé absente ou 5xx persistant (tenacity, 2 retries max).
    Respecte le disjoncteur global fmp_call_counter (hard limit 245 calls/run).
    Valide les réponses via Pydantic — null/string invalide → None, pipeline non corrompu.
    """
    global fmp_call_counter

    budget_limit = CONFIG["scanner"].get("fmp_call_budget_hard_limit", 245)
    if fmp_call_counter + 7 > budget_limit:
        logger.warning(
            f"Budget FMP atteint ({fmp_call_counter} calls) — skip {symbol} (disjoncteur {budget_limit} calls)"
        )
        return None

    api_key = CONFIG["scanner"].get("fmp_api_key")
    base_url = CONFIG["scanner"].get("fmp_base_url")

    if not api_key or api_key.startswith("${"):
        raise FMPUnavailableError("Clé FMP absente ou non configurée.")

    try:
        responses = await asyncio.gather(
            _fmp_get(client, f"{base_url}/ratios-ttm/{symbol}?apikey={api_key}"),
            _fmp_get(client, f"{base_url}/key-metrics-ttm/{symbol}?apikey={api_key}"),
            _fmp_get(client, f"{base_url}/profile/{symbol}?apikey={api_key}"),
            _fmp_get(client, f"{base_url}/income-statement/{symbol}?limit=3&apikey={api_key}"),
            _fmp_get(client, f"{base_url}/balance-sheet-statement/{symbol}?limit=3&apikey={api_key}"),
            _fmp_get(client, f"{base_url}/earnings-surprises/{symbol}?apikey={api_key}"),
            _fmp_get(client, f"{base_url}/analyst-estimates/{symbol}?period=quarter&limit=3&apikey={api_key}"),
        )
        fmp_call_counter += 7  # comptabilisé après succès du gather
    except httpx.HTTPStatusError as e:
        raise FMPUnavailableError(f"FMP 5xx persistant après 2 tentatives pour {symbol}: {e}") from e
    except FMPUnavailableError:
        raise
    except Exception as e:
        logger.error(f"Erreur réseau FMP pour {symbol}: {e}")
        return None

    try:
        r_data = responses[0].json()
        k_data = responses[1].json()
        p_data = responses[2].json()
        is_data = responses[3].json()
        bs_data = responses[4].json()
        s_data = responses[5].json()
        a_data = responses[6].json()

        if not (r_data and k_data and p_data):
            return None

        # Validation Pydantic — null/strings invalides → None (pas de crash percentile)
        r = _parse_fmp_response(r_data, FMPRatiosTTM, symbol)
        k = _parse_fmp_response(k_data, FMPKeyMetricsTTM, symbol)
        if r is None or k is None:
            logger.warning(f"FMP: réponse invalide pour {symbol} (ratios/key-metrics)")
            return None

        p = p_data[0]

        surprise_pct = 0.0
        surprise_date = None
        if s_data and len(s_data) > 0:
            surprise_pct = s_data[0].get("surprisePercentage", 0) / 100.0
            surprise_date = s_data[0].get("date")

        analyst_revision_3m = compute_analyst_revision_3m(a_data) if a_data else None

        # Priority: surprise_date (quarterly earnings announcement) → far more recent
        # than annual IS date (e.g. "2024-12-31" = 500+ days ago, always fails freshness).
        most_recent_quarter_ts = None
        if surprise_date:
            try:
                most_recent_quarter_ts = datetime.fromisoformat(surprise_date).timestamp()
            except ValueError:
                pass
        if most_recent_quarter_ts is None and is_data and len(is_data) > 0:
            date_str = is_data[0].get("date")
            if date_str:
                try:
                    most_recent_quarter_ts = datetime.fromisoformat(date_str).timestamp()
                except ValueError:
                    pass

        roe_3y = None
        if is_data and bs_data and len(is_data) >= 1 and len(bs_data) >= 1:
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
            "sector": normalize_sector_name(p.get("sector")),
            "marketCap": p.get("mktCap"),
            "roe_ttm": r.returnOnEquityTTM,
            "roe_3y": roe_3y,
            "roicTTM": k.roicTTM,
            "operatingMargins": r.operatingProfitMarginTTM,
            "totalDebt": k.totalDebtTTM,
            "totalCash": None,
            "netDebt": k.netDebtTTM,
            "ebitda": k.ebitdaTTM,
            "freeCashflow": k.freeCashFlowTTM,
            "forwardPE": r.priceEarningsRatioTTM,
            "enterpriseToEbitda": r.enterpriseValueOverEBITDATTM,
            "pegRatio": r.pegRatioTTM,
            "surprise_pct": surprise_pct,
            "surprise_date": surprise_date,
            "analyst_revision_3m": analyst_revision_3m,
            "mostRecentQuarter": most_recent_quarter_ts,
            "bookValuePerShare": k.bookValuePerShareTTM,
            "source": "FMP",
        }
    except FMPUnavailableError:
        raise
    except Exception as e:
        logger.error(f"Erreur API FMP pour {symbol}: {e}")
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
            yf.download, tickers="SPY ^VIX", period="2y", progress=False, auto_adjust=True
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

                results[symbol] = {"info": info, "prices": prices}
    except FMPUnavailableError:
        await notify_fmp_unavailable()
        raise

    for s_etf in list(set(etfs + SECTOR_ETFS)):
        prices = None
        if isinstance(prices_batch.columns, pd.MultiIndex):
            if s_etf in prices_batch.columns.levels[0]:
                prices = prices_batch[s_etf]

        results[s_etf] = {"info": {}, "prices": prices}

    return results
