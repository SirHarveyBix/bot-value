import time

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
    Télécharge les prix historiques pour une liste de tickers.
    Utilise yfinance download pour le batching.
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

def fetch_ticker_info(ticker_symbol):
    """
    Récupère les informations (.info) d'un ticker avec cache et retry.
    """
    # 1. Vérifier le cache
    cached_data = cache.get("fundamentals", ticker_symbol, TTL_FUNDAMENTALS)
    if cached_data:
        return cached_data

    # 2. Fetch yfinance avec retry
    max_retries = 3
    for attempt in range(max_retries):
        try:
            ticker = yf.Ticker(ticker_symbol)
            info = ticker.info
            if info and (info.get("currentPrice") or info.get("regularMarketPrice")):
                # Sauvegarder dans le cache
                cache.set("fundamentals", ticker_symbol, info)
                return info
            else:
                logger.warning(f"Données incomplètes pour {ticker_symbol} (tentative {attempt+1})")
        except Exception as e:
            logger.warning(f"Erreur fetch {ticker_symbol} (tentative {attempt+1}): {e}")

        if attempt < max_retries - 1:
            time.sleep(2 * (attempt + 1)) # Backoff exponentiel simple

    return None

def fetch_all_data(tickers, etfs=None, prices_batch=None):
    """
    Orchestre la récupération de toutes les données pour une shortlist de tickers.
    Le Sniper : Focus sur la qualité pour un nombre réduit d'actions.
    """
    if etfs is None:
        etfs = []

    all_tickers = list(set(tickers + etfs + SECTOR_ETFS))
    results = {}

    # 1. Fetch prix en batch si non fourni
    if prices_batch is None:
        prices_batch = fetch_prices_batch(all_tickers)

    # 2. Fetch info individuelles (Sniper stage - uniquement sur la shortlist)
    delay = CONFIG["scanner"].get("inter_request_delay", 1.0) # Délai plus long pour le Sniper
    for i, symbol in enumerate(tickers):
        if i > 0 and delay > 0:
            time.sleep(delay)
            
        logger.debug(f"Sniper : Récupération des fondamentaux pour {symbol}...")
        info = fetch_ticker_info(symbol)

        # Extraire les prix
        prices = None
        if isinstance(prices_batch.columns, pd.MultiIndex):
            if symbol in prices_batch.columns.levels[0]:
                prices = prices_batch[symbol]
        
        results[symbol] = {
            "info": info,
            "prices": prices
        }

    # Ajouter les prix pour les ETFs et Sector ETFs
    for s_etf in list(set(etfs + SECTOR_ETFS)):
        prices = None
        if isinstance(prices_batch.columns, pd.MultiIndex):
            if s_etf in prices_batch.columns.levels[0]:
                prices = prices_batch[s_etf]
        
        results[s_etf] = {
            "info": {}, # Pas de fondamentaux pour les ETFs dans cette étape
            "prices": prices
        }

    return results
