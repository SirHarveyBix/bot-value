import time
import yfinance as yf
import pandas as pd
from scanner.config import CONFIG, logger
from scanner.cache import cache

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

def fetch_all_data(tickers, etfs=None):
    """
    Orchestre la récupération de toutes les données pour une liste de tickers et d'ETFs.
    Inclut les ETFs sectoriels pour les calculs de surperformance.
    """
    if etfs is None:
        etfs = []
        
    all_tickers = list(set(tickers + etfs + SECTOR_ETFS))
    results = {}
    
    # 1. Fetch prix en batch
    prices_batch = fetch_prices_batch(all_tickers)
    
    # 2. Fetch info individuelles (uniquement pour les stocks)
    for symbol in tickers + etfs:
        logger.debug(f"Récupération des données pour {symbol}...")
        info = fetch_ticker_info(symbol) if symbol in tickers else {}
        
        # Extraire les prix du batch
        prices = None
        if isinstance(prices_batch.columns, pd.MultiIndex):
            if symbol in prices_batch.columns.levels[0]:
                prices = prices_batch[symbol]
        else:
            if symbol == prices_batch.name if hasattr(prices_batch, 'name') else False:
                prices = prices_batch
            
        results[symbol] = {
            "info": info,
            "prices": prices
        }
        
    # Ajouter les prix des sector ETFs au dictionnaire de résultats
    for s_etf in SECTOR_ETFS:
        if isinstance(prices_batch.columns, pd.MultiIndex) and s_etf in prices_batch.columns.levels[0]:
            results[s_etf] = {"prices": prices_batch[s_etf]}
        
    return results
