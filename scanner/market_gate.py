from __future__ import annotations

from enum import Enum

from scanner.config import CONFIG


class MarketRegime(Enum):
    PANIC = "panic"
    PRUDENCE = "prudence"
    BEAR_LIGHT = "bear_light"
    NORMAL = "normal"


def evaluate_market_regime(vix: float, spy_price: float, spy_ema200: float) -> MarketRegime:
    """Cascade first-match : VIX prime EMA200 (§Market Gate spec)."""
    vix_panic = CONFIG["scanner"]["vix_panic_threshold"]
    vix_warn = CONFIG["scanner"]["vix_warning_threshold"]

    if vix > vix_panic:
        return MarketRegime.PANIC
    if vix > vix_warn:
        return MarketRegime.PRUDENCE
    if spy_price < spy_ema200:
        return MarketRegime.BEAR_LIGHT
    return MarketRegime.NORMAL
