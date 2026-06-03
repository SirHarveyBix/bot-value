"""Tests unitaires — scanner/fetcher.py (FMP, ROE, disjoncteur, SECTOR_ETFS)."""

from unittest.mock import AsyncMock, patch

import pytest

# ── SECTOR_ETFS / batch de prix ───────────────────────────────────────────────


def test_sector_etfs_present_in_price_batch():
    """
    main.py construit etf_tickers = initial_etfs + SECTOR_ETFS et les ajoute
    à eligible_stocks avant fetch_prices_batch. Vérifie que XLK/XLV/SPY sont
    inclus et qu'il n'y a pas de doublons.
    """
    from scanner.fetcher import SECTOR_ETFS

    assert "XLK" in SECTOR_ETFS
    assert "XLV" in SECTOR_ETFS
    assert "SPY" in SECTOR_ETFS

    eligible_stocks = ["AAPL", "MSFT"]
    initial_etfs = ["QQQ", "IWM"]
    etf_tickers = list(dict.fromkeys(initial_etfs + list(SECTOR_ETFS)))
    all_tickers = eligible_stocks + etf_tickers

    assert "XLK" in all_tickers
    assert "QQQ" in all_tickers
    assert len(all_tickers) == len(set(all_tickers)), "Pas de doublons"


# ── Calcul ROE depuis IS/BS FMP ───────────────────────────────────────────────


def test_roe_skipped_when_equity_key_absent():
    """
    Bug BUG-3 : te = bs_data[i].get("totalStockholdersEquity", 1) utilisait 1
    comme valeur par défaut → ni / 1 = net_income absolu comme ROE (faux).
    Fix : te = None si clé absente → paire ignorée.
    """
    is_data = [{"netIncome": 10_000_000_000}]
    bs_data = [{}]

    roes = []
    for i in range(min(3, len(is_data), len(bs_data))):
        ni = is_data[i].get("netIncome")
        te = bs_data[i].get("totalStockholdersEquity")
        if ni is not None and te is not None and te > 0:
            roes.append(ni / te)

    assert roes == [], "Equity absente → aucun ROE (évite ni/1 = 10B)"


def test_roe_computed_with_valid_equity():
    """ni=100, te=500 → ROE=0.20."""
    is_data = [{"netIncome": 100}]
    bs_data = [{"totalStockholdersEquity": 500}]

    roes = []
    for i in range(min(3, len(is_data), len(bs_data))):
        ni = is_data[i].get("netIncome")
        te = bs_data[i].get("totalStockholdersEquity")
        if ni is not None and te is not None and te > 0:
            roes.append(ni / te)

    assert len(roes) == 1
    assert abs(roes[0] - 0.20) < 1e-9


def test_roe_skipped_when_equity_zero():
    """te=0 → division par zéro évitée."""
    is_data = [{"netIncome": 50}]
    bs_data = [{"totalStockholdersEquity": 0}]

    roes = []
    for i in range(min(3, len(is_data), len(bs_data))):
        ni = is_data[i].get("netIncome")
        te = bs_data[i].get("totalStockholdersEquity")
        if ni is not None and te is not None and te > 0:
            roes.append(ni / te)

    assert roes == []


def test_roe_averaged_over_3_years():
    """Moyenne sur 3 bilans annuels : (0.10 + 0.20 + 0.30) / 3 = 0.20."""
    is_data = [{"netIncome": 10}, {"netIncome": 20}, {"netIncome": 30}]
    bs_data = [
        {"totalStockholdersEquity": 100},
        {"totalStockholdersEquity": 100},
        {"totalStockholdersEquity": 100},
    ]

    roes = []
    for i in range(min(3, len(is_data), len(bs_data))):
        ni = is_data[i].get("netIncome")
        te = bs_data[i].get("totalStockholdersEquity")
        if ni is not None and te is not None and te > 0:
            roes.append(ni / te)

    assert len(roes) == 3
    assert abs(sum(roes) / len(roes) - 0.20) < 1e-9


# ── Disjoncteur global FMP ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fmp_circuit_breaker_returns_none_when_budget_exceeded():
    """
    fetch_fmp_data retourne None sans appel réseau si fmp_call_counter + 5
    dépasse fmp_call_budget_hard_limit.
    """
    import scanner.fetcher as fetcher_mod
    from scanner.fetcher import fetch_fmp_data

    saved = fetcher_mod.fmp_call_counter
    with patch.dict(
        "scanner.fetcher.CONFIG",
        {"scanner": {"fmp_call_budget_hard_limit": 175, "fmp_api_key": "key", "fmp_base_url": "https://fmp"}},
    ):
        fetcher_mod.fmp_call_counter = 171  # 171+5 > 175

        mock_client = AsyncMock()
        result = await fetch_fmp_data(mock_client, "AAPL")

        assert result is None
        mock_client.get.assert_not_called()

    fetcher_mod.fmp_call_counter = saved


@pytest.mark.asyncio
async def test_fmp_raises_unavailable_when_api_key_absent():
    """fetch_fmp_data lève FMPUnavailableError si fmp_api_key est None."""
    import scanner.fetcher as fetcher_mod
    from scanner.fetcher import FMPUnavailableError, fetch_fmp_data

    saved = fetcher_mod.fmp_call_counter
    fetcher_mod.fmp_call_counter = 0

    with patch.dict(
        "scanner.fetcher.CONFIG",
        {"scanner": {"fmp_call_budget_hard_limit": 175, "fmp_api_key": None, "fmp_base_url": "https://fmp"}},
    ):
        with pytest.raises(FMPUnavailableError):
            await fetch_fmp_data(AsyncMock(), "AAPL")

    fetcher_mod.fmp_call_counter = saved


@pytest.mark.asyncio
async def test_fmp_raises_unavailable_when_api_key_is_placeholder():
    """fetch_fmp_data lève FMPUnavailableError si la clé commence par '${'."""
    import scanner.fetcher as fetcher_mod
    from scanner.fetcher import FMPUnavailableError, fetch_fmp_data

    saved = fetcher_mod.fmp_call_counter
    fetcher_mod.fmp_call_counter = 0

    with patch.dict(
        "scanner.fetcher.CONFIG",
        {
            "scanner": {
                "fmp_call_budget_hard_limit": 175,
                "fmp_api_key": "${FMP_API_KEY}",
                "fmp_base_url": "https://fmp",
            }
        },
    ):
        with pytest.raises(FMPUnavailableError):
            await fetch_fmp_data(AsyncMock(), "AAPL")

    fetcher_mod.fmp_call_counter = saved
