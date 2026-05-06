import pandas as pd
import numpy as np
from scanner.config import CONFIG, logger

def calculate_quality_metrics(ticker_info):
    """
    Extrait les métriques de qualité depuis le dictionnaire info.
    """
    try:
        roe = ticker_info.get("returnOnEquity")
        margin = ticker_info.get("operatingMargins")
        
        # Dette Nette / EBITDA
        total_debt = ticker_info.get("totalDebt")
        total_cash = ticker_info.get("totalCash")
        ebitda = ticker_info.get("ebitda")
        
        debt_ebitda = None
        if total_debt is not None and total_cash is not None and ebitda and ebitda > 0:
            debt_ebitda = (total_debt - total_cash) / ebitda
            
        # FCF Yield Proxy
        fcf = ticker_info.get("freeCashflow")
        mcap = ticker_info.get("marketCap")
        fcf_yield = None
        if fcf is not None and mcap and mcap > 0:
            fcf_yield = fcf / mcap
            
        return {
            "roe": roe,
            "margin": margin,
            "debt_ebitda": debt_ebitda,
            "fcf_yield": fcf_yield
        }
    except Exception as e:
        logger.error(f"Erreur calcul métriques qualité: {e}")
        return {}

def apply_quality_gates(metrics):
    """
    Vérifie si le ticker passe les filtres d'exclusion Qualité.
    """
    roe = metrics.get("roe")
    debt_ebitda = metrics.get("debt_ebitda")
    
    # ROE négatif exclu
    if roe is not None and roe < 0:
        return False, "ROE négatif"
        
    # Dette trop élevée
    if debt_ebitda is not None and debt_ebitda > 6:
        return False, f"Dette/EBITDA trop élevé: {debt_ebitda:.2f}"
        
    return True, None
