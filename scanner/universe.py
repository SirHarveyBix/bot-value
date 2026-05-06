import json
import os

from concurrent.futures import ThreadPoolExecutor

import yfinance as yf

from scanner.cache import cache
from scanner.config import CONFIG, logger

# On définit le TTL du cache fondamentaux (24h)
TTL_FUNDAMENTALS = 24 * 3600

def load_universe():
    """Charge l'univers complet depuis le fichier JSON."""
    universe_path = "data/universe/tickers_universe.json"
    if not os.path.exists(universe_path):
        logger.error(f"Fichier univers {universe_path} introuvable.")
        return {"stocks": [], "etfs": []}

    with open(universe_path, 'r') as f:
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

        return True, None
    except Exception as e:
        return False, f"Erreur lors du filtrage: {str(e)}"

def _check_single_ticker(symbol):
    """Fonction helper pour le filtrage parallèle."""
    try:
        # Tenter de récupérer depuis le cache d'abord
        info = cache.get("fundamentals", symbol, TTL_FUNDAMENTALS)
        if not info:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            if info:
                cache.set("fundamentals", symbol, info)

        is_eligible, reason = get_eligibility_filters(info)
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
    max_workers = CONFIG["scanner"].get("max_workers", 8)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(_check_single_ticker, stocks))

    eligible_stocks = [s for s in results if s is not None]

    logger.info(f"Fin du filtrage. {len(eligible_stocks)} stocks éligibles sur {len(stocks)}.")
    return eligible_stocks
