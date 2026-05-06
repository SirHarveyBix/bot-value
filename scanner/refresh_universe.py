import json
import os

import pandas as pd

from scanner.config import logger


def refresh_sp500():
    """
    Récupère la liste à jour des entreprises du S&P 500 depuis Wikipedia.
    """
    logger.info("Récupération de la liste S&P 500 depuis Wikipedia...")
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        tables = pd.read_html(url)
        sp500_df = tables[0]

        # Nettoyage des symboles (certains utilisent '.' au lieu de '-')
        tickers = sp500_df["Symbol"].str.replace('.', '-', regex=False).tolist()

        logger.info(f"{len(tickers)} tickers récupérés pour le S&P 500.")
        return tickers
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du S&P 500: {e}")
        return []

def update_universe_file(new_stocks=None, new_etfs=None):
    """
    Met à jour le fichier tickers_universe.json en préservant les données existantes
    si aucune nouvelle donnée n'est fournie.
    """
    path = "data/universe/tickers_universe.json"

    # Charger l'existant
    current_data = {"stocks": [], "etfs": []}
    if os.path.exists(path):
        with open(path, 'r') as f:
            current_data = json.load(f)

    if new_stocks:
        # On fusionne sans doublons
        updated_stocks = list(set(current_data["stocks"] + new_stocks))
        current_data["stocks"] = sorted(updated_stocks)

    if new_etfs:
        updated_etfs = list(set(current_data["etfs"] + new_etfs))
        current_data["etfs"] = sorted(updated_etfs)

    try:
        with open(path, 'w') as f:
            json.dump(current_data, f, indent=2)
        logger.info(
            f"Fichier univers mis à jour avec succès : "
            f"{len(current_data['stocks'])} stocks, {len(current_data['etfs'])} etfs."
        )
    except Exception as e:
        logger.error(f"Erreur écriture univers: {e}")

def refresh_nifty50():
    """
    Récupère le NIFTY 50 (Inde) depuis Wikipedia.
    """
    logger.info("Récupération du NIFTY 50 (Inde)...")
    try:
        url = "https://en.wikipedia.org/wiki/NIFTY_50"
        tables = pd.read_html(url)
        # Wikipedia table index might change, usually it's the 1st or 2nd
        df = tables[1]
        tickers = [f"{s}.NS" for s in df["Symbol"].tolist()] # Format Yahoo pour l'Inde
        return tickers
    except Exception as e:
        logger.error(f"Erreur NIFTY 50: {e}")
        return []

def refresh_from_url(url, column_name="Symbol"):
    """
    Méthode générique pour extraire des tickers d'une table HTML (ex: Wikipedia).
    """
    logger.info(f"Extraction de tickers depuis {url}...")
    try:
        tables = pd.read_html(url)
        for df in tables:
            if column_name in df.columns:
                return df[column_name].tolist()
        return []
    except Exception as e:
        logger.error(f"Erreur extraction URL {url}: {e}")
        return []

if __name__ == "__main__":
    import sys

    source = sys.argv[1] if len(sys.argv) > 1 else "sp500"

    if source == "sp500":
        tickers = refresh_sp500()
        update_universe_file(new_stocks=tickers)
    elif source == "india":
        tickers = refresh_nifty50()
        update_universe_file(new_stocks=tickers)
    elif source == "nasdaq100":
        url = "https://en.wikipedia.org/wiki/Nasdaq-100"
        tickers = refresh_from_url(url, "Ticker")
        update_universe_file(new_stocks=tickers)
    elif source == "world":
        # Proxy via les composants majeurs du MSCI World (ex: top holdings)
        # Note: ACWI/World complets sont énormes, on cible souvent les indices par pays
        url = "https://en.wikipedia.org/wiki/MSCI_World"
        tickers = refresh_from_url(url, "Ticker")
        update_universe_file(new_stocks=tickers)
    elif source == "custom":
        if len(sys.argv) < 3:
            logger.error("Usage: python3 refresh_universe.py custom <URL> [COLUMN_NAME]")
        else:
            url = sys.argv[2]
            col = sys.argv[3] if len(sys.argv) > 3 else "Symbol"
            tickers = refresh_from_url(url, col)
            update_universe_file(new_stocks=tickers)
