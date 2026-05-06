import json
import os
import yfinance as yf
from scanner.config import CONFIG, logger

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
        # Note: on recalculera plus précisément le volume 20j dans le Fetcher via OHLCV
        avg_vol = ticker_info.get("averageVolume", 0)
        vol_usd = avg_vol * price
        if vol_usd < CONFIG["scanner"]["min_volume_20j"]:
            return False, f"Volume USD trop faible: {vol_usd}"

        # Listing Exchange
        exchange = ticker_info.get("exchange", "")
        valid_exchanges = ["NMS", "NYQ", "ASE", "NGM", "NCM"] # NASDAQ, NYSE, AMEX codes yfinance
        if exchange not in valid_exchanges:
            return False, f"Exchange non supporté: {exchange}"

        return True, None
    except Exception as e:
        return False, f"Erreur lors du filtrage: {str(e)}"

def build_eligible_universe(stocks):
    """
    Filtre une liste de stocks pour ne garder que les éligibles.
    Note: En v1, cette étape est lente car elle appelle .info pour chaque ticker.
    """
    eligible_stocks = []
    logger.info(f"Filtrage de l'univers ({len(stocks)} stocks)...")
    
    for ticker_symbol in stocks:
        try:
            ticker = yf.Ticker(ticker_symbol)
            info = ticker.info
            is_eligible, reason = get_eligibility_filters(info)
            if is_eligible:
                eligible_stocks.append(ticker_symbol)
                logger.debug(f"{ticker_symbol} est éligible.")
            else:
                logger.debug(f"{ticker_symbol} exclu : {reason}")
        except Exception as e:
            logger.error(f"Erreur sur {ticker_symbol}: {e}")
            
    logger.info(f"Fin du filtrage. {len(eligible_stocks)} stocks éligibles sur {len(stocks)}.")
    return eligible_stocks
