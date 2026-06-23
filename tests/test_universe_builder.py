from unittest.mock import MagicMock, patch

from scanner.universe import build_eligible_universe, get_eligibility_filters


def _valid_info():
    return {
        "marketCap": 10_000_000_000,
        "currentPrice": 150.0,
        "averageVolume": 50_000_000,
        "exchange": "NMS",
    }


def test_get_eligibility_filters_valid():
    """Ticker valide → (True, None)."""
    ok, reason = get_eligibility_filters(_valid_info())
    assert ok is True
    assert reason is None


def test_get_eligibility_filters_rejects_low_mcap():
    """Market cap < 2B → rejeté."""
    ok, reason = get_eligibility_filters({**_valid_info(), "marketCap": 1_000_000_000})
    assert ok is False
    assert "Market Cap" in reason


def test_get_eligibility_filters_rejects_low_price():
    """Prix < 5 → rejeté."""
    ok, reason = get_eligibility_filters({**_valid_info(), "currentPrice": 3.0})
    assert ok is False
    assert "Prix" in reason


def test_get_eligibility_filters_rejects_invalid_exchange():
    """Exchange non supporté → rejeté."""
    ok, reason = get_eligibility_filters({**_valid_info(), "exchange": "PINK"})
    assert ok is False
    assert "Exchange" in reason


def test_build_eligible_universe_filters_tickers():
    """build_eligible_universe retourne seulement les tickers éligibles."""

    def fake_ticker(symbol):
        mock = MagicMock()
        mock.info = _valid_info() if symbol == "AAPL" else {**_valid_info(), "marketCap": 500_000_000}
        return mock

    with (
        patch("scanner.universe.yf.Ticker", side_effect=fake_ticker),
        patch("scanner.universe.cache.get", return_value=None),
        patch("scanner.universe.cache.set"),
        patch("scanner.universe.time.sleep"),
    ):
        result = build_eligible_universe(["AAPL", "TINY"])

    assert "AAPL" in result
    assert "TINY" not in result
    assert len(result) == 1
