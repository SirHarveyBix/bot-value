import time
import requests

import pandas as pd
import yfinance as yf

from scanner.cache import cache
from scanner.config import CONFIG, logger

# TTL en secondes
TTL_FUNDAMENTALS = 24 * 3600
TTL_PRICES = 4 * 3600

SECTOR_ETFS = ["XLK", "XLV", "XLF", "XLY", "XLP", "XLI", "XLE", "XLB", "XLRE", "XLU", "XLC", "SPY"]

def fetch_prices_batch(tickers, period="1y"):
    """
    Télécharge les prix historiques pour une liste de tickers via yfinance.
    """
    if not tickers:
        return pd.DataFrame()
    logger.info(f"Téléchargement des prix pour {len(tickers)} tickers...")
    try:
        data = yf.download(
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

def fetch_fmp_data(symbol):
    """
    Récupère les fondamentaux institutionnels via Financial Modeling Prep.
    """
    api_key = CONFIG["scanner"].get("fmp_api_key")
    base_url = CONFIG["scanner"].get("fmp_base_url")

    if not api_key or api_key.startswith("${"):
        logger.warning(f"Clé FMP manquante. Repli sur yfinance pour {symbol}.")
        return None

    # On a besoin de : Quote, Ratios-TTM, Key-Metrics-TTM
    # Pour minimiser les appels sur plan gratuit (250/jour), on cible l'essentiel
    try:
        # 1. Ratios TTM (ROE, Marges, P/E, PEG)
        r_resp = requests.get(f"{base_url}/ratios-ttm/{symbol}?apikey={api_key}")
        # 2. Key Metrics TTM (Net Debt / EBITDA, Market Cap)
        k_resp = requests.get(f"{base_url}/key-metrics-ttm/{symbol}?apikey={api_key}")
        # 3. Profile (Sector, Industry, Name)
        p_resp = requests.get(f"{base_url}/profile/{symbol}?apikey={api_key}")

        if r_resp.status_code == 200 and k_resp.status_code == 200 and p_resp.status_code == 200:
            r_data = r_resp.json()
            k_data = k_resp.json()
            p_data = p_resp.json()

            if r_data and k_data and p_data:
                # Normalisation vers un format compatible avec le scoring
                r = r_data[0]
                k = k_data[0]
                p = p_data[0]
                
                return {
                    "symbol": symbol,
                    "longName": p.get("companyName"),
                    "sector": p.get("sector"),
                    "marketCap": p.get("mktCap"),
                    "returnOnEquity": r.get("returnOnEquityTTM"),
                    "operatingMargins": r.get("operatingProfitMarginTTM"),
                    "totalDebt": k.get("totalDebtTTM"),
                    "totalCash": k.get("netDebtTTM"), # On va tricher un peu car on a directement netDebt
                    "netDebt": k.get("netDebtTTM"),
                    "ebitda": k.get("ebitdaTTM"),
                    "freeCashflow": k.get("freeCashFlowTTM"),
                    "forwardPE": r.get("priceEarningsRatioTTM"), # FMP ratios are TTM, used as proxy for Forward
                    "enterpriseToEbitda": r.get("enterpriseValueOverEBITDATTM"),
                    "pegRatio": r.get("pegRatioTTM"),
                    "revenueGrowth": r.get("revenueGrowthTTM"),
                    "source": "FMP"
                }
        return None
    except Exception as e:
        logger.error(f"Erreur API FMP pour {symbol}: {e}")
        return None

def fetch_ticker_info(ticker_symbol):
    """
    Récupère les informations d'un ticker avec cache, en priorité via FMP puis yfinance.
    """
    # 1. Vérifier le cache
    cached_data = cache.get("fundamentals", ticker_symbol, TTL_FUNDAMENTALS)
    if cached_data:
        return cached_data

    # 2. Priorité FMP (Sniper)
    info = fetch_fmp_data(ticker_symbol)
    
    # 3. Fallback yfinance si FMP échoue ou absent
    if not info:
        max_retries = 2
        for attempt in range(max_retries):
            try:
                ticker = yf.Ticker(ticker_symbol)
                info = ticker.info
                if info and (info.get("currentPrice") or info.get("regularMarketPrice")):
                    info["source"] = "yfinance"
                    break
            except Exception as e:
                logger.warning(f"Erreur fallback yfinance {ticker_symbol}: {e}")
                time.sleep(1)

    if info:
        cache.set("fundamentals", ticker_symbol, info)
    return info

def fetch_all_data(tickers, etfs=None, prices_batch=None):
    """
    Orchestre la récupération de toutes les données pour une shortlist de tickers.
    Le Sniper : Utilise FMP pour la shortlist.
    """
    if etfs is None:
        etfs = []

    all_tickers = list(set(tickers + etfs + SECTOR_ETFS))
    results = {}

    if prices_batch is None:
        prices_batch = fetch_prices_batch(all_tickers)

    delay = CONFIG["scanner"].get("inter_request_delay", 0.5)
    for i, symbol in enumerate(tickers):
        if i > 0 and delay > 0:
            time.sleep(delay)
            
        logger.info(f"Sniper : Récupération des fondamentaux pour {symbol}...")
        info = fetch_ticker_info(symbol)

        prices = None
        if isinstance(prices_batch.columns, pd.MultiIndex):
            if symbol in prices_batch.columns.levels[0]:
                prices = prices_batch[symbol]
        
        results[symbol] = {
            "info": info,
            "prices": prices
        }

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

