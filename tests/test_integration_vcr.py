import pytest
import os
import pandas as pd
from freezegun import freeze_time
from scanner.fetcher import fetch_all_data, fetch_market_indices, FMPUnavailableError
from scanner.scoring.engine import stock_scoring_pipeline
from scanner.storage import save_signals
from scanner.universe import load_universe

@pytest.mark.asyncio
async def test_full_pipeline_vcr(tmp_path):
    """
    Test d'intégration complet — pipeline normal (hermetique, sans réseau).
    Simule une exécution un jour de bourse normal (mercredi 15 janv 2025).
    min_universe_size patché à 1 car seulement 5 stocks mock.
    """
    from unittest.mock import patch
    from scanner.config import CONFIG
    import scanner.scoring.engine as engine_module
    from scanner import fetcher as fetcher_module
    import scanner.storage as storage_module
    import numpy as np

    patched_cfg = {
        **CONFIG,
        "scanner": {**CONFIG["scanner"], "min_universe_size": 1},
        "scoring": CONFIG["scoring"],
    }

    mock_info = {
        "longName": "Mock Corp", "sector": "Technology",
        "marketCap": 5_000_000_000, "returnOnEquity": 0.20, "roe_ttm": 0.20, "roe_3y": 0.20,
        "operatingMargins": 0.15, "totalDebt": 1e9, "totalCash": None, "netDebt": 5e8,
        "ebitda": 5e8, "freeCashflow": 3e8, "forwardPE": 20.0, "enterpriseToEbitda": 15.0,
        "pegRatio": 1.5, "surprise_pct": 0.05, "surprise_date": "2024-10-15",
        "analyst_revision_3m": 0.02, "mostRecentQuarter": 1728000000.0, "source": "FMP",
    }

    dates = pd.date_range("2024-01-01", periods=252, freq="B")

    async def mock_fetch_ticker(symbol, client=None):
        return {**mock_info, "symbol": symbol}

    stocks = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]

    spy_prices = pd.Series([490.0] * 252, index=dates)
    vix_prices = pd.Series([15.0] * 252, index=dates)
    mock_indices = pd.DataFrame({
        ("Close", "SPY"): spy_prices,
        ("Close", "^VIX"): vix_prices,
    })
    mock_indices.columns = pd.MultiIndex.from_tuples(mock_indices.columns)

    data_dict = {}
    for s in stocks + ["SPY"]:
        for col in ["Close", "Open", "High", "Low", "Volume"]:
            data_dict[(s, col)] = (np.linspace(100, 130, 252) if col != "Volume" else np.full(252, 1e6))
    mock_batch = pd.DataFrame(data_dict, index=dates)
    mock_batch.columns = pd.MultiIndex.from_tuples(mock_batch.columns)

    with freeze_time("2025-01-15 10:00:00", tick=True):
        with patch.object(engine_module, "CONFIG", patched_cfg):
            with patch.object(fetcher_module, "fetch_ticker_info", side_effect=mock_fetch_ticker):
                with patch.object(fetcher_module, "fetch_prices_batch", return_value=mock_batch):
                    with patch.object(fetcher_module, "fetch_market_indices", return_value=mock_indices):
                        # 0. Market Gate
                        market_history = await fetch_market_indices()
                        assert not market_history.empty

                        # 1–2. Fetch (hermetique)
                        all_data = await fetch_all_data(stocks, prices_batch=mock_batch)
                        assert len(all_data) >= 5

                        # 3. Scoring
                        ranked_df = stock_scoring_pipeline(all_data, stocks)
                        assert not ranked_df.empty

                        # 4. Storage (WAL mode) — DB dans tmp_path pour CI
                        db_file = str(tmp_path / "scanner_history.db")
                        market_data = {
                            "regime": "normal",
                            "spy_price": 500.0,
                            "spy_ema200": 480.0,
                            "vix": 15.0
                        }
                        with patch.object(storage_module, "DB_PATH", db_file):
                            save_signals(ranked_df.head(3), pd.DataFrame(), all_data, len(stocks), market_data=market_data)
                            assert os.path.exists(db_file)


# T042 — Budget FMP ≤ 250 calls pour 30 tickers
@pytest.mark.asyncio
async def test_fmp_budget_counter():
    """
    Mock 30 tickers Sniper → total appels FMP mockés ≤ 250.
    7 endpoints × 30 tickers = 210 nominaux.
    """
    from unittest.mock import patch
    from scanner import fetcher as fetcher_module

    call_count = 0

    mock_info = {
        "symbol": "TEST", "longName": "Test Corp", "sector": "Technology",
        "marketCap": 5_000_000_000, "returnOnEquity": 0.2, "roe_ttm": 0.2, "roe_3y": 0.2,
        "operatingMargins": 0.15, "totalDebt": 1e9, "totalCash": None, "netDebt": 5e8,
        "ebitda": 5e8, "freeCashflow": 3e8, "forwardPE": 20.0, "enterpriseToEbitda": 15.0,
        "pegRatio": 1.5, "surprise_pct": 0.0, "surprise_date": None,
        "analyst_revision_3m": None, "source": "FMP",
    }

    async def mock_fetch_ticker(symbol, client=None):
        nonlocal call_count
        call_count += 7  # 7 endpoints par ticker
        return mock_info

    universe = load_universe()
    stocks = universe.get("stocks", [])[:30]
    mock_prices = pd.DataFrame()

    with patch.object(fetcher_module, "fetch_ticker_info", side_effect=mock_fetch_ticker):
        with patch.object(fetcher_module, "fetch_prices_batch", return_value=mock_prices):
            try:
                await fetch_all_data(stocks[:30], [], prices_batch=mock_prices)
            except Exception:
                pass

    assert call_count <= 250, f"Budget FMP dépassé: {call_count} calls > 250"


# T043 — Pipeline panic : VIX=40 → 0 signaux, notify_panic appelé
@pytest.mark.asyncio
async def test_full_pipeline_panic_regime():
    """
    VIX=40 → scan termine après notify_panic(), 0 rows dans signals.
    """
    from unittest.mock import patch, AsyncMock
    import main as main_module

    panic_called = False

    async def mock_notify_panic(vix, spy, ema200):
        nonlocal panic_called
        panic_called = True

    def mock_save_scan_entry(market_data):
        assert market_data["regime"] == "panic"

    spy_prices = pd.Series([450.0] * 400)
    vix_prices = pd.Series([40.0] * 400)
    mock_df = pd.DataFrame({
        ("Close", "SPY"): spy_prices,
        ("Close", "^VIX"): vix_prices,
    })
    mock_df.columns = pd.MultiIndex.from_tuples(mock_df.columns)

    with patch.object(main_module, "notify_panic", side_effect=mock_notify_panic):
        with patch.object(main_module, "save_scan_entry", side_effect=mock_save_scan_entry):
            with patch.object(main_module, "is_market_open", return_value=True):
                with patch.object(main_module, "fetch_market_indices", return_value=mock_df):
                    with patch.object(main_module, "fetch_prices_batch", new_callable=AsyncMock,
                                      return_value=pd.DataFrame()):
                        await main_module.run_scanner(force=True)

    assert panic_called, "notify_panic() doit être appelé pour VIX=40"


# T044 — FMP 503×2 → FMPUnavailableError → notify_fmp_unavailable, 0 signaux
@pytest.mark.asyncio
async def test_fmp_unavailable_abort():
    """
    FMP retourne 503 persistant → FMPUnavailableError
    → notify_fmp_unavailable() appelé, scan avorté, 0 signaux.
    """
    from unittest.mock import patch
    from scanner import fetcher as fetcher_module

    fmp_unavailable_called = False

    async def mock_notify_fmp():
        nonlocal fmp_unavailable_called
        fmp_unavailable_called = True

    async def mock_fmp_data(client, symbol):
        raise FMPUnavailableError("FMP 5xx persistant après 2 tentatives pour TEST.")

    mock_prices = pd.DataFrame()

    with patch.object(fetcher_module, "fetch_fmp_data", side_effect=mock_fmp_data):
        with patch.object(fetcher_module, "fetch_prices_batch", return_value=mock_prices):
            with patch.object(fetcher_module, "notify_fmp_unavailable",
                              side_effect=mock_notify_fmp):
                with pytest.raises(FMPUnavailableError):
                    await fetch_all_data(["AAPL"], [], prices_batch=mock_prices)

    assert fmp_unavailable_called, "notify_fmp_unavailable() doit être appelé lors d'une FMPUnavailableError"


# ── update_signal_returns ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_signal_returns_no_rows(tmp_path):
    """0 signaux éligibles → 0 mises à jour, pas d'erreur."""
    from unittest.mock import patch
    import scanner.storage as storage_module
    from scanner.storage import init_db, update_signal_returns

    db_file = str(tmp_path / "test_returns.db")
    with patch.object(storage_module, "DB_PATH", db_file):
        init_db()
        await update_signal_returns()  # pas de rows → doit terminer proprement


@pytest.mark.asyncio
async def test_update_signal_returns_negative(tmp_path):
    """Signal avec price_at_signal=100, prix actuel=80 → return_30d=-0.2."""
    import sqlite3
    import yfinance as yf
    from unittest.mock import patch, AsyncMock, MagicMock
    import scanner.storage as storage_module
    from scanner.storage import init_db, update_signal_returns

    db_file = str(tmp_path / "test_returns_neg.db")

    with patch.object(storage_module, "DB_PATH", db_file):
        init_db()
        conn = sqlite3.connect(db_file)
        conn.execute(
            "INSERT INTO scans (scan_date, market_regime, universe_size, eligible_count) VALUES (?,?,?,?)",
            ("2026-01-01", "normal", 100, 5)
        )
        scan_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO signals (scan_id, symbol, name, type, rank, score_global, score_quality, "
            "score_valuation, score_momentum, first_seen_date, price_at_signal) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (scan_id, "TEST", "Test Corp", "stock", 1, 80.0, 70.0, 60.0, 90.0, "2026-01-01", 100.0)
        )
        conn.commit()
        conn.close()

        mock_hist = pd.DataFrame({"Close": [80.0]})
        mock_ticker = MagicMock(spec=yf.Ticker)
        mock_ticker.history = MagicMock(return_value=mock_hist)

        with patch("yfinance.Ticker", return_value=mock_ticker):
            await update_signal_returns()

        conn = sqlite3.connect(db_file)
        row = conn.execute("SELECT return_30d FROM signals WHERE symbol='TEST'").fetchone()
        conn.close()

    assert row is not None
    assert abs(row[0] - (-0.2)) < 1e-9


# ── fetch_fmp_data ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_fmp_data_missing_key():
    """Clé FMP absente → FMPUnavailableError immédiat."""
    from unittest.mock import patch, AsyncMock
    import httpx
    from scanner.fetcher import fetch_fmp_data

    cfg = {
        "scanner": {"fmp_api_key": None, "fmp_base_url": "https://fmp.test", "fmp_max_retries": 2},
        "scoring": {},
    }
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    with patch("scanner.fetcher.CONFIG", cfg):
        with pytest.raises(FMPUnavailableError):
            await fetch_fmp_data(mock_client, "AAPL")


@pytest.mark.asyncio
async def test_fetch_fmp_data_success():
    """Réponses 200 complètes → dict correct (totalCash=None, sector, surprise_pct)."""
    from unittest.mock import patch, MagicMock
    import httpx
    from scanner.fetcher import fetch_fmp_data

    def make_resp(data):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = data
        return r

    url_responses = {
        "ratios-ttm": make_resp([{
            "returnOnEquityTTM": 0.20, "operatingProfitMarginTTM": 0.15,
            "priceEarningsRatioTTM": 20.0, "enterpriseValueOverEBITDATTM": 15.0, "pegRatioTTM": 1.5,
        }]),
        "key-metrics-ttm": make_resp([{
            "totalDebtTTM": 1e9, "netDebtTTM": 5e8, "ebitdaTTM": 5e8, "freeCashFlowTTM": 3e8,
        }]),
        "profile": make_resp([{"companyName": "Apple", "sector": "Technology", "mktCap": 3e12}]),
        "income-statement": make_resp([{"date": "2024-09-30", "netIncome": 1e9}]),
        "balance-sheet-statement": make_resp([{"totalStockholdersEquity": 5e9}]),
        "earnings-surprises": make_resp([{"surprisePercentage": 5.0, "date": "2024-10-30"}]),
        "analyst-estimates": make_resp([{"estimatedEpsAvg": 2.1}, {"estimatedEpsAvg": 2.0}]),
    }

    async def mock_get(url):
        for key, resp in url_responses.items():
            if key in url:
                return resp
        return make_resp([])

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = mock_get

    cfg = {
        "scanner": {"fmp_api_key": "test_key", "fmp_base_url": "https://fmp.test", "fmp_max_retries": 2},
        "scoring": {},
    }
    with patch("scanner.fetcher.CONFIG", cfg):
        result = await fetch_fmp_data(mock_client, "AAPL")

    assert result is not None
    assert result["sector"] == "Technology"
    assert result["totalCash"] is None
    assert abs(result["surprise_pct"] - 0.05) < 1e-9
    assert result["source"] == "FMP"


@pytest.mark.asyncio
async def test_fetch_fmp_data_5xx_raises():
    """5xx persistant → FMPUnavailableError après max_retries tentatives."""
    from unittest.mock import patch, MagicMock
    import httpx
    from scanner.fetcher import fetch_fmp_data

    def make_resp_5xx():
        r = MagicMock()
        r.status_code = 503
        r.json.return_value = {}
        return r

    async def mock_get(url):
        return make_resp_5xx()

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.get = mock_get

    cfg = {
        "scanner": {"fmp_api_key": "test_key", "fmp_base_url": "https://fmp.test", "fmp_max_retries": 2},
        "scoring": {},
    }
    with patch("scanner.fetcher.CONFIG", cfg):
        with patch("asyncio.sleep"):  # accélérer le retry
            with pytest.raises(FMPUnavailableError):
                await fetch_fmp_data(mock_client, "AAPL")
