import pandas as pd
import json
import os
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
        logger.info(f"Fichier univers mis à jour avec succès : {len(current_data['stocks'])} stocks, {len(current_data['etfs'])} etfs.")
    except Exception as e:
        logger.error(f"Erreur écriture univers: {e}")

if __name__ == "__main__":
    sp500_tickers = refresh_sp500()
    if sp500_tickers:
        update_universe_file(new_stocks=sp500_tickers)
