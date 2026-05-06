import json
import os
from datetime import datetime
from scanner.config import logger

def save_signals(top_stocks, top_etfs, all_data, universe_size):
    """
    Sauvegarde les résultats du scan au format JSON.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    output_dir = "data/signals"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    file_path = os.path.join(output_dir, f"signals_{today_str}.json")
    latest_path = os.path.join(output_dir, "signals_latest.json")
    
    # Préparation de la structure
    signals = {
        "scan_date": today_str,
        "scan_timestamp": datetime.now().isoformat(),
        "universe_size": universe_size,
        "top_stocks": top_stocks.to_dict(orient="records") if not top_stocks.empty else [],
        "top_etfs": top_etfs.to_dict(orient="records") if not top_etfs.empty else []
    }
    
    try:
        with open(file_path, 'w') as f:
            json.dump(signals, f, indent=2)
            
        # Mise à jour du lien "latest" (copie du fichier)
        with open(latest_path, 'w') as f:
            json.dump(signals, f, indent=2)
            
        logger.info(f"Signaux sauvegardés dans {file_path}")
        return file_path
    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde des signaux: {e}")
        return None
