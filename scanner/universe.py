import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import yfinance as yf

from scanner.cache import cache
from scanner.config import CONFIG, logger

EXCLUDED_ETF_PATTERNS = [
    "3X",
    "2X",
    "-3",
    "-2",
    "ULTRA",
    "ULTRA SHORT",
    "BEAR",
    "SHORT",
    "INVERSE",
    "DAILY",
    "PROSHARES",
]


def is_eligible_etf(ticker: str, name: str = "") -> bool:
    """Retourne False si l'ETF est à effet de levier ou inverse."""
    check = name.upper() if name else ticker.upper()
    return not any(pat in check for pat in EXCLUDED_ETF_PATTERNS)


def load_universe():
    """Charge l'univers complet depuis le fichier JSON."""
    universe_path = "data/universe/tickers_universe.json"
    if not os.path.exists(universe_path):
        logger.error(f"Fichier univers {universe_path} introuvable.")
        return {"stocks": [], "etfs": []}

    with open(universe_path, "r") as f:
        return json.load(f)


def get_eligibility_filters(ticker_info):
    """
    Applique les filtres d'éligibilité sur les données .info de yfinance.
    Retourne (True, None) si éligible, (False, raison) sinon.
    """
    if not ticker_info or "error" in ticker_info:
        return False, "Données invalides ou manquantes"

    try:
        # Market Cap
        mcap = ticker_info.get("marketCap", 0)
        if mcap < CONFIG["scanner"]["min_market_cap"]:
            return False, f"Market Cap trop faible: {mcap}"

        # Prix
        price = ticker_info.get("currentPrice") or ticker_info.get("regularMarketPrice")
        if price is None or price < CONFIG["scanner"]["min_price"]:
            return False, f"Prix trop faible: {price}"

        # Volume (Volume moyen 10j ou 20j si dispo dans .info)
        avg_vol = ticker_info.get("averageVolume", 0)
        vol_usd = avg_vol * price
        if vol_usd < CONFIG["scanner"]["min_volume_20j"]:
            return False, f"Volume USD trop faible: {vol_usd}"

        # Listing Exchange
        exchange = ticker_info.get("exchange", "")
        valid_exchanges = ["NMS", "NYQ", "ASE", "NGM", "NCM"]
        if exchange not in valid_exchanges:
            return False, f"Exchange non supporté: {exchange}"

        # Ancienneté des données (2 ans d'historique requis)
        # On vérifie si firstTradeDateEpochUtc est présent (yfinance .info)
        first_trade = ticker_info.get("firstTradeDateEpochUtc")
        if first_trade:
            two_years_ago = (datetime.now() - timedelta(days=365 * 2)).timestamp()
            if first_trade > two_years_ago:
                return False, "Moins de 2 ans d'historique"

        return True, None
    except Exception as e:
        return False, f"Erreur lors du filtrage: {str(e)}"


def _check_single_ticker(symbol):
    """Fonction helper pour le filtrage parallèle."""
    try:
        # Tenter de récupérer depuis le cache d'abord (TTL depuis config — cohérence avec fetcher.py)
        _ttl = CONFIG["scanner"].get("cache_ttl_fundamentals", 97200)
        info = cache.get("eligibility", symbol, _ttl)
        if not info:
            delay = CONFIG["scanner"].get("inter_request_delay", 0.5)
            if delay > 0:
                time.sleep(delay)

            ticker = yf.Ticker(symbol)
            info = ticker.info
            if info:
                cache.set("eligibility", symbol, info)

        is_eligible, reason = get_eligibility_filters(info)
        if not is_eligible:
            logger.debug(f"Exclu {symbol}: {reason}")
        return symbol if is_eligible else None
    except Exception as e:
        logger.error(f"Erreur filtrage {symbol}: {e}")
        return None


def build_eligible_universe(stocks):
    """
    Filtre une liste de stocks en parallèle pour ne garder que les éligibles.
    """
    logger.info(f"Filtrage de l'univers ({len(stocks)} stocks) en parallèle...")
    eligible_stocks = []

    # Utilisation de ThreadPoolExecutor pour accélérer le processus (Section 2.2 des specs)
    max_workers = CONFIG["scanner"]["max_workers_universe"]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(_check_single_ticker, stocks))

    eligible_stocks = [s for s in results if s is not None]

    logger.info(f"Fin du filtrage. {len(eligible_stocks)} stocks éligibles sur {len(stocks)}.")
    return eligible_stocks
