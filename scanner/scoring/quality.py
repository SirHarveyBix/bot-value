from scanner.config import logger


def calculate_quality_metrics(ticker_info):
    """
    Extrait les métriques de qualité depuis le dictionnaire info.
    """
    try:
        # Section 4.1: ROE 3 ans obligatoire — TTM proscrit par la spec
        roe_3y = ticker_info.get("roe_3y")
        roe_used = roe_3y  # None si FMP n'a pas fourni le calcul 3 ans → exclu dans apply_quality_gates

        margin = ticker_info.get("operatingMargins")
        sector = ticker_info.get("sector")

        # Section 4.4: Financials, Real Estate ET Utilities exclus de la dette/EBITDA
        # (levier structurel réglementé — ratio sans sens comparatif pour ces secteurs)
        exclude_debt = sector in ["Financials", "Real Estate", "Utilities"]

        total_debt = ticker_info.get("totalDebt")
        total_cash = ticker_info.get("totalCash")
        net_debt = ticker_info.get("netDebt") # FMP fournit souvent netDebt directement
        ebitda = ticker_info.get("ebitda")

        debt_ebitda = None
        if not exclude_debt:
            # Calcul via Net Debt direct (FMP)
            if net_debt is not None and ebitda and ebitda > 0:
                debt_ebitda = net_debt / ebitda
            # Ou via Total Debt - Cash (yfinance)
            elif total_debt is not None and total_cash is not None and ebitda and ebitda > 0:
                debt_ebitda = (total_debt - total_cash) / ebitda

        # FCF Yield Proxy (Note: yfinance FCF data can be noisy/unreliable)
        fcf = ticker_info.get("freeCashflow")
        mcap = ticker_info.get("marketCap")
        fcf_yield = None
        if fcf is not None and mcap and mcap > 0:
            fcf_yield = fcf / mcap
        elif ticker_info.get("operatingCashflow") and mcap and mcap > 0:
            # Fallback sur l'Operating Cash Flow si le FCF est manquant
            fcf_yield = ticker_info.get("operatingCashflow") / mcap
            logger.debug(f"Utilisation de l'Operating Cashflow pour {ticker_info.get('symbol')} (FCF manquant)")

        return {
            "roe": roe_used,
            "margin": margin,
            "debt_ebitda": debt_ebitda,
            "fcf_yield": fcf_yield,
            "ebitda": ebitda
        }
    except Exception as e:
        logger.error(f"Erreur calcul métriques qualité: {e}")
        return {}

def apply_quality_gates(metrics, ticker_info=None):
    """
    Vérifie si le ticker passe les filtres d'exclusion Qualité (Section 4.1).
    Retourne (passed: bool, reason: str | None, flags: list[str])
    """
    roe = metrics.get("roe")
    debt_ebitda = metrics.get("debt_ebitda")
    ebitda = metrics.get("ebitda")
    flags = []

    # Gate: ROE 3 ans absent → FMP n'a pas fourni le calcul (TTM proscrit)
    if roe is None:
        return False, "ROE 3 ans indisponible (non calculable sans FMP)", flags

    # Gate: EBITDA <= 0 exclu
    if ebitda is not None and ebitda <= 0:
        return False, "EBITDA négatif ou nul", flags

    # Gate: book_value_per_share <= 0 → ROE mathématiquement sans sens
    bvps = (ticker_info or {}).get("bookValuePerShare")
    if bvps is not None and bvps <= 0:
        return False, "book_value_per_share <= 0 (ROE non interprétable)", flags

    # Gate: ROE négatif exclu
    if roe < 0:
        return False, "ROE négatif", flags

    # Flag: ROE > 150% avec book_value < 5$ → probable gonflement par buybacks
    if roe > 1.50 and bvps is not None and bvps < 5.0:
        flags.append("⚠️ ROE possiblement gonflé par buybacks")
        metrics["roe_capped"] = True  # engine.py plafonne le percentile à 80

    # Gate: Dette trop élevée
    if debt_ebitda is not None and debt_ebitda > 6:
        return False, f"Dette/EBITDA trop élevé: {debt_ebitda:.2f}", flags

    return True, None, flags
