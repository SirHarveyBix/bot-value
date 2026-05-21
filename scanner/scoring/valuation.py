from scanner.config import logger


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
        mcap = ticker_info.get("marketCap", 0)

        # Fallback P/E
        pe_used = pe_fwd
        pe_flag = None
        if pe_used is None or pe_used <= 0:
            if pe_ttm and pe_ttm > 0:
                pe_used = pe_ttm
                pe_flag = "P/E TTM used as fallback"

        return {"pe": pe_used, "ev_ebitda": ev_ebitda, "peg": peg, "sector": sector, "mcap": mcap, "pe_flag": pe_flag}
    except Exception as e:
        logger.error(f"Erreur calcul métriques valorisation: {e}")
        return None


def apply_valuation_gates(metrics):
    """
    Applique les seuils d'exclusion pour la valorisation.
    Retourne (is_excluded, is_v_ok, reason)
    """
    pe = metrics.get("pe")
    ev_ebitda = metrics.get("ev_ebitda")
    sector = metrics.get("sector")
    mcap = metrics.get("mcap", 0)

    # Section 4.4: Exception Health Care < 5B$ (Biotechs)
    # On suspend le gate P/E négatif
    is_biotech_exception = sector == "Health Care" and mcap < 5_000_000_000

    # Cas : Pas de P/E disponible
    if pe is None:
        return False, False, "P/E manquant"

    # Cas : P/E négatif
    if pe <= 0:
        if is_biotech_exception:
            # On garde le ticker mais on invalide le pilier valorisation (score 50/50)
            # car un P/E négatif n'a pas de sens pour le scoring
            return False, False, "P/E négatif (Biotech exception)"
        else:
            # Exclusion pure
            return True, False, "P/E négatif"

    # Seuil P/E par secteur (Section 4.1)
    pe_limit = 50
    if sector in ["Technology", "Health Care"]:
        pe_limit = 80

    if pe > pe_limit:
        return True, False, f"P/E trop élevé: {pe:.1f} (limit {pe_limit})"

    if ev_ebitda and ev_ebitda > 40:
        return True, False, f"EV/EBITDA trop élevé: {ev_ebitda:.1f}"

    return False, True, None
