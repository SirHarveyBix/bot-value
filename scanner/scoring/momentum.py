from scanner.config import logger

SECTOR_ETF_MAP = {
    "Technology": "XLK",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC"
}

def calculate_momentum_metrics(prices_df, info, sector_prices_df=None):
    """
    Calcule les métriques de momentum.
    prices_df: OHLCV du ticker.
    sector_prices_df: OHLCV de l'ETF sectoriel correspondant.
    """
    if prices_df is None or len(prices_df) < 126: # 126 jours = ~6 mois
        return {}

    try:
        close = prices_df["Close"]
        p_now = close.iloc[-1]

        # Perf absolues
        perf_6m = (p_now - close.iloc[-126]) / close.iloc[-126] if len(close) >= 126 else None
        perf_3m = (p_now - close.iloc[-63]) / close.iloc[-63] if len(close) >= 63 else None
        perf_1m = (p_now - close.iloc[-21]) / close.iloc[-21] if len(close) >= 21 else None

        # Surperf sectorielle
        outperf_6m = None
        if sector_prices_df is not None and len(sector_prices_df) >= 126:
            s_close = sector_prices_df["Close"]
            s_perf_6m = (s_close.iloc[-1] - s_close.iloc[-126]) / s_close.iloc[-126]
            if perf_6m is not None:
                outperf_6m = perf_6m - s_perf_6m

        # Surprise Earnings % (Momentum Fondamental - Section 4.1)
        surprise_pct = info.get("surprise_pct", 0)

        return {
            "perf_6m": perf_6m,
            "perf_3m": perf_3m,
            "perf_1m": perf_1m,
            "outperf_6m": outperf_6m,
            "surprise_pct": surprise_pct
        }
    except Exception as e:
        logger.error(f"Erreur calcul momentum: {e}")
        return {}

def apply_momentum_penalties(score, metrics):
    """
    Applique les pénalités anti-momentum extrême.
    """
    perf_1m = metrics.get("perf_1m")
    if perf_1m is None:
        return score

    new_score = score
    if perf_1m > 0.25:
        new_score -= 10
    elif perf_1m < -0.20:
        new_score -= 5

    return max(0, min(100, new_score))
