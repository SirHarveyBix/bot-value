import pandas as pd
from datetime import datetime
from scanner.config import CONFIG, logger

def filter_post_scoring(df):
    """
    Applique les filtres de diversification sectorielle et autres post-traitements.
    """
    if df.empty:
        return df
        
    # 1. Diversification sectorielle : max 3 par secteur dans le top 10
    final_top_10 = []
    sector_counts = {}
    
    # On parcourt le df trié par score_global
    for _, row in df.iterrows():
        sector = row.get("sector", "Unknown")
        count = sector_counts.get(sector, 0)
        
        if len(final_top_10) < 10:
            if count < 3:
                final_top_10.append(row)
                sector_counts[sector] = count + 1
            else:
                logger.debug(f"Ticker {row['symbol']} exclu du top 10 (limite secteur {sector} atteinte)")
        
    return pd.DataFrame(final_top_10)

def add_earnings_flags(df, all_data):
    """
    Ajoute les dates de résultats et les flags.
    Note: yf.Ticker.calendar est instable, on l'utilise avec précaution.
    """
    results = []
    for _, row in df.iterrows():
        symbol = row["symbol"]
        info = all_data.get(symbol, {}).get("info", {})
        
        # En v1.0, on essaie de récupérer la date via info ou calendar si dispo
        # yfinance ne donne pas toujours .calendar de façon simple en batch
        # On ajoute un placeholder informatif
        row_dict = row.to_dict()
        row_dict["earnings_date"] = "TBD" 
        row_dict["flags"] = []
        
        results.append(row_dict)
        
    return pd.DataFrame(results)
