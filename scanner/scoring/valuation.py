from scanner.config import CONFIG, logger

def calculate_valuation_metrics(ticker_info):
    """
    Extrait les métriques de valorisation.
    """
    try:
        pe_fwd = ticker_info.get("forwardPE")
        pe_ttm = ticker_info.get("trailingPE")
        ev_ebitda = ticker_info.get("enterpriseToEbitda")
        peg = ticker_info.get("pegRatio")
        sector = ticker_info.get("sector")
        
        # Fallback P/E
        pe_used = pe_fwd
        pe_flag = None
        if pe_used is None or pe_used <= 0:
            if pe_ttm and pe_ttm > 0:
                pe_used = pe_ttm
                pe_flag = "P/E TTM used as fallback"
        
        return {
            "pe": pe_used,
            "ev_ebitda": ev_ebitda,
            "peg": peg,
            "sector": sector,
            "pe_flag": pe_flag
        }
    except Exception as e:
        logger.error(f"Erreur calcul métriques valorisation: {e}")
        return {}

def apply_valuation_gates(metrics):
    """
    Applique les seuils d'exclusion pour la valorisation.
    """
    pe = metrics.get("pe")
    ev_ebitda = metrics.get("ev_ebitda")
    sector = metrics.get("sector")
    
    if pe is None or pe <= 0:
        return False, "P/E manquant ou négatif"
        
    # Seuil P/E par secteur
    pe_limit = 50
    if sector in ["Technology", "Health Care"]:
        pe_limit = 80
        
    if pe > pe_limit:
        return False, f"P/E trop élevé: {pe:.1f} (limit {pe_limit})"
        
    if ev_ebitda and ev_ebitda > 40:
        return False, f"EV/EBITDA trop élevé: {ev_ebitda:.1f}"
        
    return True, None
