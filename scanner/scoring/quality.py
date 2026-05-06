from scanner.config import logger


def calculate_quality_metrics(ticker_info):
    """
    Extrait les métriques de qualité depuis le dictionnaire info.
    """
    try:
        roe = ticker_info.get("returnOnEquity")
        margin = ticker_info.get("operatingMargins")
        sector = ticker_info.get("sector")

        # Dette Nette / EBITDA
        # Section 4.4: Financials et Real Estate exclus de la dette/EBITDA
        exclude_debt = sector in ["Financials", "Real Estate"]

        total_debt = ticker_info.get("totalDebt")
        total_cash = ticker_info.get("totalCash")
        ebitda = ticker_info.get("ebitda")

        debt_ebitda = None
        if not exclude_debt:
            if total_debt is not None and total_cash is not None and ebitda and ebitda > 0:
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
