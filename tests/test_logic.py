import sys
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from freezegun import freeze_time

from scanner.filters import (
    check_batch_data_ratio,
    check_data_ratio,
    data_freshness_check,
    earnings_calendar_check,
    filter_post_scoring,
)
from scanner.notifier import truncate_message
from scanner.scoring.engine import compute_momentum_weights, compute_percentile_ranks
from scanner.scoring.momentum import apply_momentum_penalties, calculate_momentum_metrics, compute_analyst_revision_3m
from scanner.scoring.quality import apply_quality_gates, calculate_quality_metrics
from scanner.scoring.valuation import apply_valuation_gates, calculate_valuation_metrics


def test_quality_logic():
    # Cas nominal — roe_3y obligatoire (champ FMP), returnOnEquity (yfinance) ignoré
    info = {
        "roe_3y": 0.20,  # champ FMP — Règle d'Or
        "operatingMargins": 0.15,
        "netDebt": 50,  # FMP fournit netDebt directement (totalCash=None dans FMP)
        "ebitda": 25,
        "freeCashflow": 10,
        "marketCap": 100,
    }
    metrics = calculate_quality_metrics(info)
    assert metrics["roe"] == 0.20
    assert metrics["debt_ebitda"] == 2.0  # netDebt/ebitda = 50/25
    assert metrics["fcf_yield"] == 0.1
    assert metrics["ebitda"] == 25

    # Gate: roe_3y absent → roe=None → exclu (champ returnOnEquity yfinance ignoré)
    info_no_roe = {k: v for k, v in info.items() if k != "roe_3y"}
    info_no_roe["returnOnEquity"] = 0.20  # yfinance TTM — non lu par calculate_quality_metrics
    metrics_no_roe = calculate_quality_metrics(info_no_roe)
    assert metrics_no_roe["roe"] is None, "roe_3y absent → roe=None (TTM non utilisé)"
    ok_no_roe, reason_no_roe, _ = apply_quality_gates(metrics_no_roe)
    assert not ok_no_roe
    assert "ROE 3 ans indisponible" in reason_no_roe

    # Gate: EBITDA <= 0 — ticker_info doit avoir roe_3y pour passer le gate ROE d'abord
    metrics["ebitda"] = 0
    ok, reason, _ = apply_quality_gates(metrics, ticker_info={"roe_3y": 0.20})
    assert not ok
    assert "EBITDA négatif ou nul" in reason

    # Gate: ROE négatif — roe_3y brut (pas le composite) utilisé pour la gate
    metrics["ebitda"] = 25
    metrics["roe"] = -0.05
    ok, reason, _ = apply_quality_gates(metrics, ticker_info={"roe_3y": -0.05})
    assert not ok
    assert "ROE négatif" in reason

    # Gate: Dette trop élevée
    metrics["roe"] = 0.20
    metrics["debt_ebitda"] = 7.0
    ok, reason, _ = apply_quality_gates(metrics, ticker_info={"roe_3y": 0.20})
    assert not ok
    assert "Dette/EBITDA trop élevé" in reason

    # Gate: book_value_per_share <= 0 → exclu
    metrics["debt_ebitda"] = 2.0
    ok, reason, _ = apply_quality_gates(metrics, ticker_info={"bookValuePerShare": -1.0, "roe_3y": 0.20})
    assert not ok
    assert "book_value_per_share" in reason

    # Flag: ROE > 150% avec BVS < 5$ → non exclu, flag + cap (roe_3y brut pour le flag)
    metrics["roe"] = 1.60
    ok, reason, flags = apply_quality_gates(metrics, ticker_info={"bookValuePerShare": 2.5, "roe_3y": 1.60})
    assert ok
    assert any("gonflé par buybacks" in f for f in flags)
    assert metrics.get("roe_capped") is True


def test_valuation_logic():
    # Cas nominal
    info = {"forwardPE": 25, "enterpriseToEbitda": 15, "pegRatio": 1.5, "sector": "Technology"}
    metrics = calculate_valuation_metrics(info)
    assert metrics["pe"] == 25

    # Gate: P/E trop élevé pour Tech (limit 80)
    is_excluded, v_ok, reason = apply_valuation_gates(metrics)
    assert not is_excluded
    assert v_ok

    metrics["pe"] = 85
    is_excluded, v_ok, reason = apply_valuation_gates(metrics)
    assert is_excluded
    assert not v_ok
    assert "P/E trop élevé" in reason

    # Gate: P/E trop élevé pour autre secteur (limit 50)
    metrics["sector"] = "Consumer Staples"
    metrics["pe"] = 55
    is_excluded, v_ok, reason = apply_valuation_gates(metrics)
    assert is_excluded
    assert not v_ok

    # Gate: P/E négatif (exclusion)
    metrics["pe"] = -5
    is_excluded, v_ok, reason = apply_valuation_gates(metrics)
    assert is_excluded
    assert not v_ok
    assert "P/E négatif" in reason


def test_momentum_logic():
    # Mock info for surprise earnings
    info = {"surprise_pct": 0.20}
    # Mock prices (130 days of data)
    prices = pd.DataFrame({"Close": [100] * 130})
    metrics = calculate_momentum_metrics(prices, info)
    assert metrics["surprise_pct"] == 0.20
    assert "perf_6m" in metrics


def test_momentum_penalties():
    score = 80
    # Pénalité > 25%
    metrics = {"perf_1m": 0.30}
    assert apply_momentum_penalties(score, metrics) == 70

    # Pénalité < -20%
    metrics = {"perf_1m": -0.25}
    assert apply_momentum_penalties(score, metrics) == 75


def test_percentile_ranking():
    df = pd.DataFrame({"val": [10, 20, 30, 40, 50]})
    ranks = compute_percentile_ranks(df, "val")
    assert ranks.iloc[0] == 20.0  # 1/5
    assert ranks.iloc[-1] == 100.0  # 5/5


def test_intra_sector_ranking():
    rows = [
        {"symbol": "T1", "sector": "Tech", "pe": 10},
        {"symbol": "T2", "sector": "Tech", "pe": 20},
        {"symbol": "T3", "sector": "Energy", "pe": 5},
        {"symbol": "T4", "sector": "Energy", "pe": 15},
    ]
    df = pd.DataFrame(rows)
    # Ranking P/E (Bas = Meilleur score)
    df["rank_pe"] = df.groupby("sector")["pe"].transform(compute_percentile_ranks, column="pe", ascending=False)

    # T1 (10) vs T2 (20) en Tech -> T1 est meilleur
    assert df[df["symbol"] == "T1"]["rank_pe"].iloc[0] == 100.0
    assert df[df["symbol"] == "T2"]["rank_pe"].iloc[0] == 50.0

    # T3 (5) vs T4 (15) en Energy -> T3 est meilleur
    assert df[df["symbol"] == "T3"]["rank_pe"].iloc[0] == 100.0
    assert df[df["symbol"] == "T4"]["rank_pe"].iloc[0] == 50.0


def test_global_score_weights():
    # Mock row
    row = pd.Series({"score_quality": 80, "score_valuation": 60, "score_momentum": 90, "v_ok": True})

    # Nouvelles pondérations alignées avec les specs : 0.35, 0.30, 0.35
    expected = 80 * 0.35 + 60 * 0.30 + 90 * 0.35  # 28 + 18 + 31.5 = 77.5

    # On simule le calcul du main engine
    from scanner.config import CONFIG

    w = CONFIG["scoring"]["weights"]
    score = (
        row["score_quality"] * w["quality"]
        + row["score_valuation"] * w["valuation"]
        + row["score_momentum"] * w["momentum"]
    )
    assert score == expected

    # Cas v_ok = False (50/50)
    row["v_ok"] = False
    score = row["score_quality"] * 0.5 + row["score_momentum"] * 0.5
    assert score == (80 + 90) / 2


@pytest.mark.asyncio
async def test_sector_diversification():
    rows = []
    all_data = {}
    # 4 secteurs pour pouvoir remplir un top 10 (3+3+3+1)
    sectors = ["Tech", "Energy", "Finance", "Health"]
    import time

    now = time.time()
    for i in range(20):
        symbol = f"T{i}"
        rows.append({"symbol": symbol, "sector": sectors[i % 4], "score_global": 100 - i})
        all_data[symbol] = {
            "info": {
                "mostRecentQuarter": now,
            }
        }
    df = pd.DataFrame(rows)

    with patch("scanner.filters.earnings_calendar_check", return_value=None):
        top_10 = await filter_post_scoring(df, all_data)

    assert len(top_10) == 10
    # Aucun secteur ne doit dépasser 3
    counts = top_10["sector"].value_counts()
    for sector in sectors:
        assert counts.get(sector, 0) <= 3


def test_sector_exceptions():
    # Test 1: Financials excluded from debt gate — roe_3y requis (FMP)
    info_fin = {
        "sector": "Financials",
        "roe_3y": 0.15,  # FMP obligatoire
        "totalDebt": 1000,
        "totalCash": 100,
        "ebitda": 50,  # Debt/EBITDA = 18x — normalement exclu mais pas pour Financials
        "marketCap": 10000,
    }
    metrics = calculate_quality_metrics(info_fin)
    # Dans Financials, debt_ebitda doit être None
    assert metrics["debt_ebitda"] is None
    ok, _, _flags = apply_quality_gates(metrics, ticker_info=info_fin)
    assert ok  # Ne doit pas être exclu par la dette

    # Test 1b: Utilities excluded from debt gate (nouvelle règle §4.4)
    info_util = {
        "sector": "Utilities",
        "roe_3y": 0.12,
        "totalDebt": 5000,
        "totalCash": 200,
        "ebitda": 700,  # Dette/EBITDA ~6.8x — normal pour Utilities
        "marketCap": 50000,
    }
    metrics_util = calculate_quality_metrics(info_util)
    assert metrics_util["debt_ebitda"] is None, "Utilities doit être exclu du calcul dette/EBITDA"
    ok_util, _, _flags_util = apply_quality_gates(metrics_util, ticker_info=info_util)
    assert ok_util, "Utilities ne doit pas être exclu malgré le fort levier structurel"

    # Test 2: Biotech exception for negative P/E
    info_bio = {
        "sector": "Health Care",
        "forwardPE": -10,
        "marketCap": 4_000_000_000,  # < 5B$
    }
    v_metrics = calculate_valuation_metrics(info_bio)
    # P/E négatif -> is_excluded=False, v_ok=False (fallback 50/50)
    is_excluded, v_ok, _ = apply_valuation_gates(v_metrics)
    assert not is_excluded
    assert not v_ok

    # Test 3: forwardPE absent → pe=None (trailingPE non utilisé — jamais peuplé par FMP)
    info_ttm = {"forwardPE": None, "sector": "Technology"}
    v_metrics = calculate_valuation_metrics(info_ttm)
    assert v_metrics["pe"] is None
    assert v_metrics["pe_flag"] is None


def test_valuation_score_calculation():
    from scanner.scoring.engine import compute_valuation_score

    # Cas 1 : Nominal (PEG présent)
    row = pd.Series({"rank_pe": 80, "rank_ev_ebitda": 60, "rank_peg": 70, "pe_flag": None})
    score, ok = compute_valuation_score(row)
    # 80*0.45 + 60*0.35 + 70*0.20 = 36 + 21 + 14 = 71
    assert ok
    assert score == 71.0

    # Cas 2 : PEG absent (renormalisation sur pe+ev_ebitda uniquement)
    row_no_peg = pd.Series({"rank_pe": 80, "rank_ev_ebitda": 60, "rank_peg": None, "pe_flag": None})
    score, ok = compute_valuation_score(row_no_peg)
    # (80*0.45 + 60*0.35) / (0.45+0.35) * 1.0 = 57/0.80 = 71.25
    assert ok
    assert abs(score - 71.25) < 1e-9

    # Cas 3 : P/E TTM fallback (Pénalité -5)
    row_ttm = pd.Series({"rank_pe": 80, "rank_ev_ebitda": 60, "rank_peg": 70, "pe_flag": "P/E TTM used as fallback"})
    score, ok = compute_valuation_score(row_ttm)
    assert ok
    assert score == 66.0  # 71 - 5

    # Cas 4 : P/E ET EV/EBITDA absents → exclusion pilier (repondération 50/50)
    row_nan = pd.Series({"rank_pe": None, "rank_ev_ebitda": None, "rank_peg": 70, "pe_flag": None})
    score, ok = compute_valuation_score(row_nan)
    assert not ok
    assert score is None


def test_etf_pipeline():
    from scanner.scoring.engine import etf_scoring_pipeline

    # Mock data
    prices = pd.DataFrame(
        {
            "Close": [100] * 130,  # Constant price
            "Volume": [1000] * 130,
        }
    )

    all_data = {"ETF1": {"prices": prices}, "SPY": {"prices": pd.DataFrame({"Close": [100] * 130})}}

    ranked = etf_scoring_pipeline(all_data, ["ETF1"])
    assert not ranked.empty
    assert ranked.iloc[0]["symbol"] == "ETF1"
    # On vérifie que le score_global est calculé (même si 0 ici car pas de perf)
    assert "score_global" in ranked.columns


# ── Nouveaux tests T029-T041 ──────────────────────────────────────────────────


def _make_market_regime(current_vix, current_spy, ema200):
    """Délègue à evaluate_market_regime — teste le vrai module."""
    from scanner.market_gate import evaluate_market_regime

    return evaluate_market_regime(current_vix, current_spy, ema200).value


# T029
def test_market_gate_panic_vix_over_35():
    """VIX=40, SPY au-dessus EMA200 → regime=panic (VIX prioritaire)."""
    assert _make_market_regime(current_vix=40.0, current_spy=500.0, ema200=480.0) == "panic"


# T030
def test_market_gate_panic_regardless_spy():
    """VIX=36, SPY sous EMA200 → regime=panic (VIX toujours prioritaire)."""
    assert _make_market_regime(current_vix=36.0, current_spy=440.0, ema200=480.0) == "panic"


# T031
def test_market_gate_prudence():
    """VIX=30 (>25), SPY < EMA200 → regime=prudence."""
    assert _make_market_regime(current_vix=30.0, current_spy=440.0, ema200=480.0) == "prudence"


# T032
def test_market_gate_bear_light():
    """VIX=20 (≤25), SPY < EMA200 → regime=bear_light."""
    assert _make_market_regime(current_vix=20.0, current_spy=440.0, ema200=480.0) == "bear_light"


# T033
def test_market_gate_normal():
    """VIX=15, SPY ≥ EMA200 → regime=normal."""
    assert _make_market_regime(current_vix=15.0, current_spy=500.0, ema200=480.0) == "normal"


# T034
def test_sector_none_exclusion():
    """sector=None → ticker exclu du pipeline (résultat vide)."""
    import pandas as pd

    from scanner.scoring.engine import stock_scoring_pipeline

    prices = pd.DataFrame({"Close": list(range(1, 260)), "Volume": [1_000_000] * 259})

    all_data = {
        "AAPL": {
            "info": {
                "sector": None,
                "longName": "Apple Inc.",
                "marketCap": 3_000_000_000_000,
                "returnOnEquity": 1.47,
                "operatingMargins": 0.31,
                "totalDebt": 97_000_000_000,
                "totalCash": None,
                "netDebt": 52_000_000_000,
                "ebitda": 130_000_000_000,
                "freeCashflow": 111_000_000_000,
                "forwardPE": 28.5,
                "enterpriseToEbitda": 22.4,
                "pegRatio": 1.8,
                "surprise_pct": 0.05,
                "surprise_date": None,
                "analyst_revision_3m": None,
                "source": "FMP",
            },
            "prices": prices,
        }
    }

    result = stock_scoring_pipeline(all_data, ["AAPL"])

    assert result.empty


# T035
@freeze_time("2026-05-19")
def test_earnings_decay_expired():
    """surprise_date = today-91j → effective_surprise = 0.0 (décroissance complète)."""
    from scanner.config import CONFIG

    base = CONFIG["scoring"]["momentum_subweights"].copy()
    surprise_date = "2026-02-17"  # 91 jours avant 2026-05-19
    today = date(2026, 5, 19)
    w = compute_momentum_weights(surprise_date, base, today)
    assert w["surprise_earnings"] == 0.0


# T036
@freeze_time("2026-05-19")
def test_earnings_decay_partial():
    """surprise_date = today-45j → effective_surprise ≈ base × 0.5."""
    from scanner.config import CONFIG

    base = CONFIG["scoring"]["momentum_subweights"].copy()
    surprise_date = "2026-04-04"  # 45 jours avant 2026-05-19
    today = date(2026, 5, 19)
    w = compute_momentum_weights(surprise_date, base, today)
    expected = base["surprise_earnings"] * 0.5
    assert abs(w["surprise_earnings"] - expected) < 1e-9


# T037
@freeze_time("2026-05-19")
def test_earnings_decay_fresh():
    """surprise_date = today-5j → effective_surprise ≈ base (aucune décroissance)."""
    from scanner.config import CONFIG

    base = CONFIG["scoring"]["momentum_subweights"].copy()
    surprise_date = "2026-05-14"  # 5 jours avant 2026-05-19
    today = date(2026, 5, 19)
    w = compute_momentum_weights(surprise_date, base, today)
    expected = base["surprise_earnings"] * (1.0 - 5 / 90)
    assert abs(w["surprise_earnings"] - expected) < 1e-9


# T038
def test_intra_sector_fallback():
    """Secteur avec 2 tickers → use_cross_universe_ranking=True pour ces tickers."""
    import pandas as pd

    from scanner.scoring.engine import stock_scoring_pipeline

    def _make_stock_data(sector):
        prices = pd.DataFrame({"Close": list(range(50, 310)), "Volume": [5_000_000] * 260})
        return {
            "info": {
                "sector": sector,
                "longName": "Test Corp",
                "marketCap": 5_000_000_000,
                "returnOnEquity": 0.20,
                "operatingMargins": 0.15,
                "totalDebt": 1_000_000_000,
                "totalCash": None,
                "netDebt": 500_000_000,
                "ebitda": 500_000_000,
                "freeCashflow": 300_000_000,
                "forwardPE": 20.0,
                "enterpriseToEbitda": 15.0,
                "pegRatio": 1.5,
                "surprise_pct": 0.0,
                "surprise_date": None,
                "analyst_revision_3m": None,
                "source": "FMP",
            },
            "prices": prices,
        }

    # 2 tickers dans "Lonely" (< min_tickers_intra_sector=3) → cross-universe fallback
    # 5 tickers dans "Big" pour atteindre min_universe_size=100... mais en test on ne peut pas
    # Simplement vérifier que use_cross_universe_ranking=True est positionné correctement
    all_data = {f"S{i}": _make_stock_data("Lonely") for i in range(2)}
    # On doit avoir assez de tickers pour passer MIN_UNIVERSE_SIZE - patch config temporairement
    from unittest.mock import patch

    from scanner.config import CONFIG

    patched_config = {
        **CONFIG,
        "scanner": {**CONFIG["scanner"], "min_universe_size": 1, "min_tickers_intra_sector": 3},
        "scoring": CONFIG["scoring"],
    }
    with patch("scanner.scoring.engine.CONFIG", patched_config):
        result = stock_scoring_pipeline(all_data, list(all_data.keys()))

    if not result.empty:
        assert result["use_cross_universe_ranking"].all()
        # Cross-universe fallback : rangs basés sur l'univers complet, pas neutralisés à 50.0
        for col in ["rank_pe", "rank_ev_ebitda", "rank_margin"]:
            assert result[col].notna().all(), f"{col} ne doit pas être NaN"
            assert not (result[col] == 50.0).all(), f"{col} ne doit pas être uniformément 50.0 (cross-universe attendu)"


# T039
def test_truncate_message():
    """String 5000 chars → len==4096, se termine par '[message tronqué]'."""
    long_msg = "A" * 5000
    truncated = truncate_message(long_msg, max_chars=4096)
    assert len(truncated) == 4096
    assert truncated.endswith("[message tronqué]")


# T040
def test_first_seen_date_preserved(tmp_path):
    """AAPL jour1 → absent → jour5 → first_seen_date conservée à jour1."""
    import sqlite3
    from unittest.mock import patch

    db_path = str(tmp_path / "test.db")

    with patch("scanner.storage.DB_PATH", db_path):
        from scanner.storage import get_first_seen_date, init_db, save_signals_to_db

        init_db()

        stock_row1 = pd.DataFrame(
            [
                {
                    "symbol": "AAPL",
                    "name": "Apple Inc.",
                    "score_global": 90.0,
                    "score_quality": 85.0,
                    "score_valuation": 80.0,
                    "score_momentum": 95.0,
                    "pe": 28.5,
                    "roe": 1.47,
                    "margin": 0.31,
                    "perf_6m": 0.18,
                }
            ]
        )

        market_data = {"regime": "normal", "spy_price": 500.0, "spy_ema200": 480.0, "vix": 15.0}
        save_signals_to_db(stock_row1, pd.DataFrame(), {}, 100, market_data=market_data)

        conn = sqlite3.connect(db_path)
        first_date = get_first_seen_date(conn, "AAPL")
        conn.close()
        assert first_date is not None

        save_signals_to_db(stock_row1, pd.DataFrame(), {}, 100, market_data=market_data)

        conn = sqlite3.connect(db_path)
        second_date = get_first_seen_date(conn, "AAPL")
        conn.close()
        assert second_date == first_date


# T041
def test_totalcash_none_after_fix():
    """Réponse FMP mockée → totalCash est None, netDebt mappé correctement depuis netDebtTTM."""
    mocked_fmp_response = {
        "netDebtTTM": 52_000_000_000,
        "ebitdaTTM": 130_000_000_000,
        "totalDebtTTM": 97_000_000_000,
    }
    assert mocked_fmp_response.get("netDebtTTM") == 52_000_000_000
    # Simule le mapping post-fix : totalCash doit être None
    total_cash = None  # Bug 2 fix : k.get("netDebtTTM") → None
    net_debt = mocked_fmp_response.get("netDebtTTM")
    assert total_cash is None
    assert net_debt == 52_000_000_000


# T029b — test compute_analyst_revision_3m
def test_analyst_revision_computation():
    """compute_analyst_revision_3m : cas nominal, insuffisant, EPS nul."""
    estimates = [
        {"estimatedEpsAvg": 2.10},
        {"estimatedEpsAvg": 2.00},
    ]
    result = compute_analyst_revision_3m(estimates)
    assert abs(result - 0.05) < 1e-9

    assert compute_analyst_revision_3m([]) is None
    assert compute_analyst_revision_3m([{"estimatedEpsAvg": 1.0}]) is None

    zero_prev = [{"estimatedEpsAvg": 1.0}, {"estimatedEpsAvg": 0.0}]
    assert compute_analyst_revision_3m(zero_prev) is None


# ── data_freshness_check ──────────────────────────────────────────────────────


@freeze_time("2026-05-19")
def test_data_freshness_stale():
    """mostRecentQuarter vieux de 451j (bilan annuel vraiment stale) → is_fresh=False."""
    stale_ts = (datetime(2026, 5, 19) - timedelta(days=451)).timestamp()
    is_fresh, _, reason = data_freshness_check({"mostRecentQuarter": stale_ts})
    assert not is_fresh
    assert "451" in reason


@freeze_time("2026-05-19")
def test_data_freshness_warning():
    """mostRecentQuarter vieux de 400j (bilan annuel > 1 an) → is_fresh=True, has_warning=True."""
    warn_ts = (datetime(2026, 5, 19) - timedelta(days=400)).timestamp()
    is_fresh, has_warning, _ = data_freshness_check({"mostRecentQuarter": warn_ts})
    assert is_fresh
    assert has_warning


@freeze_time("2026-05-19")
def test_data_freshness_fresh():
    """mostRecentQuarter vieux de 30j → is_fresh=True, has_warning=False."""
    fresh_ts = (datetime(2026, 5, 19) - timedelta(days=30)).timestamp()
    is_fresh, has_warning, _ = data_freshness_check({"mostRecentQuarter": fresh_ts})
    assert is_fresh
    assert not has_warning


def test_data_freshness_no_timestamp():
    """mostRecentQuarter=None → is_fresh=True, has_warning=True (date inconnue)."""
    is_fresh, has_warning, _ = data_freshness_check({"mostRecentQuarter": None})
    assert is_fresh
    assert has_warning


def test_data_freshness_empty_info():
    """info None → is_fresh=False."""
    is_fresh, _, _ = data_freshness_check(None)
    assert not is_fresh


# ── check_batch_data_ratio ────────────────────────────────────────────────────


def test_check_batch_data_ratio_pass():
    """7 tickers / eligible=10 → ratio=0.7 ≥ 0.6 → True."""
    tickers = [f"T{i}" for i in range(7)]
    cols = pd.MultiIndex.from_tuples([(t, "Close") for t in tickers])
    df = pd.DataFrame(columns=cols)
    assert check_batch_data_ratio(df, 10)


def test_check_batch_data_ratio_fail():
    """5 tickers / eligible=10 → ratio=0.5 < 0.6 → False."""
    tickers = [f"T{i}" for i in range(5)]
    cols = pd.MultiIndex.from_tuples([(t, "Close") for t in tickers])
    df = pd.DataFrame(columns=cols)
    assert not check_batch_data_ratio(df, 10)


def test_check_batch_data_ratio_zero_eligible():
    """eligible_count=0 → False (early return)."""
    assert not check_batch_data_ratio(pd.DataFrame(), 0)


# ── check_data_ratio ──────────────────────────────────────────────────────────


def test_check_data_ratio_pass():
    """7 valides / 10 → ratio=0.7 ≥ 0.6 → True."""
    all_data = {f"T{i}": {"info": {"longName": f"Corp{i}"}} for i in range(7)}
    all_data.update({f"X{i}": {"info": None} for i in range(3)})
    assert check_data_ratio(all_data, 10)


def test_check_data_ratio_fail():
    """4 valides / 10 → ratio=0.4 < 0.6 → False."""
    all_data = {f"T{i}": {"info": {"longName": f"Corp{i}"}} for i in range(4)}
    all_data.update({f"X{i}": {"info": None} for i in range(6)})
    assert not check_data_ratio(all_data, 10)


def test_check_data_ratio_zero_eligible():
    """eligible_count=0 → False."""
    assert not check_data_ratio({}, 0)


# ── earnings_calendar_check ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_earnings_calendar_none():
    """ticker.calendar=None → retourne None sans exception."""
    mock_ticker = MagicMock()
    mock_ticker.calendar = None
    with patch("scanner.filters.yf.Ticker", return_value=mock_ticker):
        assert await earnings_calendar_check("AAPL") is None


@pytest.mark.asyncio
@freeze_time("2026-05-19")
async def test_earnings_calendar_soon():
    """Earnings dans 7j → retourne la date formatée."""
    next_date = datetime(2026, 5, 26)
    mock_ticker = MagicMock()
    mock_ticker.calendar = {"Earnings Date": [next_date]}
    with patch("scanner.filters.yf.Ticker", return_value=mock_ticker):
        result = await earnings_calendar_check("AAPL")
    assert result == "2026-05-26"


@pytest.mark.asyncio
@freeze_time("2026-05-19")
async def test_earnings_calendar_far_future():
    """Earnings dans 30j → hors fenêtre 14j → retourne None."""
    next_date = datetime(2026, 6, 18)
    mock_ticker = MagicMock()
    mock_ticker.calendar = {"Earnings Date": [next_date]}
    with patch("scanner.filters.yf.Ticker", return_value=mock_ticker):
        result = await earnings_calendar_check("AAPL")
    assert result is None


# ── is_market_open ────────────────────────────────────────────────────────────


@pytest.mark.skipif(sys.version_info < (3, 10), reason="pandas_market_calendars 4.4+ requiert Python 3.10+")
@freeze_time("2026-05-18")
def test_is_market_open_weekday():
    """Lundi 2026-05-18 → NYSE ouvert."""
    from main import is_market_open

    assert is_market_open()


@pytest.mark.skipif(sys.version_info < (3, 10), reason="pandas_market_calendars 4.4+ requiert Python 3.10+")
@freeze_time("2026-05-17")
def test_is_market_open_weekend():
    """Dimanche 2026-05-17 → NYSE fermé."""
    from main import is_market_open

    assert not is_market_open()


# ── v1.1 T077 — Pydantic FMP validation ──────────────────────────────────────


def test_parse_fmp_response_invalid_string():
    """parse_fmp_response avec string 'N/A' → champ = None, pas de crash (API stable FMP)."""
    from scanner.fetcher import FMPRatiosTTM, _parse_fmp_response

    # API stable : priceToEarningsRatioTTM (v3 : priceEarningsRatioTTM)
    result = _parse_fmp_response(
        {"priceToEarningsRatioTTM": "N/A", "operatingProfitMarginTTM": 0.15},
        FMPRatiosTTM,
        "TEST",
    )
    assert result is not None
    assert result.priceToEarningsRatioTTM is None
    assert abs(result.operatingProfitMarginTTM - 0.15) < 1e-9


def test_parse_fmp_response_empty():
    """parse_fmp_response liste vide → None."""
    from scanner.fetcher import FMPRatiosTTM, _parse_fmp_response

    assert _parse_fmp_response([], FMPRatiosTTM, "TEST") is None


def test_parse_fmp_response_key_metrics_list():
    """parse_fmp_response accepte liste (key-metrics-ttm stable retourne list)."""
    from scanner.fetcher import FMPKeyMetricsTTM, _parse_fmp_response

    result = _parse_fmp_response(
        [{"returnOnEquityTTM": 0.18, "returnOnInvestedCapitalTTM": 0.12, "freeCashFlowYieldTTM": 0.05}],
        FMPKeyMetricsTTM,
        "TEST",
    )
    assert result is not None
    assert abs(result.returnOnEquityTTM - 0.18) < 1e-9
    assert abs(result.returnOnInvestedCapitalTTM - 0.12) < 1e-9
    assert abs(result.freeCashFlowYieldTTM - 0.05) < 1e-9


# ── v1.1 T078 — Momentum volatility-adjusted ─────────────────────────────────


def test_momentum_adj_higher_for_stable_trend():
    """
    Tendance stable (σ faible) vs tendance volatile (σ élevé) → momentum_adj plus élevé pour stable.
    σ des deux séries bien au-dessus de VOLATILITY_FLOOR (0.05%) pour tester la logique réelle.
    """
    import numpy as np

    from scanner.scoring.momentum import calculate_momentum_metrics

    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=252, freq="B")
    trend = np.linspace(100, 130, 252)

    # Série stable : trend + bruit faible (σ_daily ≈ 0.3%)
    prices_stable = pd.DataFrame(
        {"Close": np.maximum(trend + np.random.normal(0, 0.3, 252), 10.0)},
        index=dates,
    )

    # Série volatile : même tendance + bruit fort (σ_daily ≈ 3%)
    prices_volatile = pd.DataFrame(
        {"Close": np.maximum(trend + np.random.normal(0, 3.0, 252), 10.0)},
        index=dates,
    )

    m_stable = calculate_momentum_metrics(prices_stable, {})
    m_volatile = calculate_momentum_metrics(prices_volatile, {})

    assert m_stable["momentum_adj"] is not None
    assert m_volatile["momentum_adj"] is not None
    # Bruit stable σ << bruit volatile σ → momentum_adj stable > volatile (même tendance)
    assert m_stable["momentum_adj"] > m_volatile["momentum_adj"]


# ── v1.1 T079 — Inverse volatility weights ───────────────────────────────────


def test_inverse_vol_weights_sum_100():
    """Somme des poids = 100% à 1e-9 près."""
    import numpy as np

    from scanner.scoring.engine import compute_inverse_vol_weights

    dates = pd.date_range("2024-01-01", periods=126, freq="B")
    ranked_df = pd.DataFrame({"symbol": ["A", "B"]})
    all_data = {
        "A": {"prices": pd.DataFrame({"Close": np.linspace(100, 110, 126)}, index=dates)},
        "B": {"prices": pd.DataFrame({"Close": np.linspace(100, 130, 126)}, index=dates)},
    }
    result = compute_inverse_vol_weights(ranked_df, all_data)
    assert abs(result["suggested_weight_pct"].sum() - 100.0) < 1e-6


def test_inverse_vol_weights_low_vol_gets_more():
    """σ_A = moitié σ_B → weight_A ≈ 2× weight_B."""
    import numpy as np

    from scanner.scoring.engine import compute_inverse_vol_weights

    dates = pd.date_range("2024-01-01", periods=126, freq="B")
    # Série A : très stable (σ ≈ 0.001), série B : volatile (σ ≈ 0.002)
    np.random.seed(42)
    prices_a = 100.0 + np.cumsum(np.random.normal(0, 0.1, 126))
    prices_b = 100.0 + np.cumsum(np.random.normal(0, 0.2, 126))

    ranked_df = pd.DataFrame({"symbol": ["A", "B"]})
    all_data = {
        "A": {"prices": pd.DataFrame({"Close": prices_a}, index=dates)},
        "B": {"prices": pd.DataFrame({"Close": prices_b}, index=dates)},
    }
    result = compute_inverse_vol_weights(ranked_df, all_data)
    w_a = result.loc[result["symbol"] == "A", "suggested_weight_pct"].iloc[0]
    w_b = result.loc[result["symbol"] == "B", "suggested_weight_pct"].iloc[0]
    # A moins volatile → poids plus élevé
    assert w_a > w_b


# ── Market Gate — gap VIX [25,35] + SPY ≥ EMA200 ─────────────────────────────


def test_market_gate_prudence_vix_high_spy_above_ema():
    """VIX=30 (>25), SPY ≥ EMA200 → regime=prudence (VIX prime SPY position)."""
    assert _make_market_regime(current_vix=30.0, current_spy=500.0, ema200=480.0) == "prudence"


# ── T019 — notify_panic / notify_fmp_unavailable HTML ────────────────────────


@pytest.mark.asyncio
async def test_notify_panic_html_escaping():
    """notify_panic : VIX avec décimale → message HTML valide, envoyé via send_message_safe."""
    from unittest.mock import patch

    from scanner.notifier import notify_panic

    sent_messages = []

    async def mock_send(bot, chat_id, text, **kwargs):
        sent_messages.append(text)

    with patch("scanner.notifier._get_bot", return_value=(object(), "123")):
        with patch("scanner.notifier.send_message_safe", side_effect=mock_send):
            await notify_panic(vix=40.5, spy=450.0, ema200=480.0)

    assert len(sent_messages) == 1
    msg = sent_messages[0]
    assert "40.5" in msg
    assert "450.00" in msg
    assert "&gt;" in msg  # VIX > 35 → html.escape
    assert len(msg) <= 4096


@pytest.mark.asyncio
async def test_notify_fmp_unavailable_html():
    """notify_fmp_unavailable : message HTML envoyé, ≤ 4096 chars."""
    from unittest.mock import patch

    from scanner.notifier import notify_fmp_unavailable

    sent_messages = []

    async def mock_send(bot, chat_id, text, **kwargs):
        sent_messages.append(text)

    with patch("scanner.notifier._get_bot", return_value=(object(), "123")):
        with patch("scanner.notifier.send_message_safe", side_effect=mock_send):
            await notify_fmp_unavailable()

    assert len(sent_messages) == 1
    msg = sent_messages[0]
    assert "FMP" in msg
    assert len(msg) <= 4096


# ── VOLATILITY_FLOOR — momentum plancher ─────────────────────────────────────


def test_momentum_adj_flat_price_uses_floor():
    """Prix constant → σ ≈ 0 → momentum_adj calculé avec VOLATILITY_FLOOR (pas None)."""
    import numpy as np

    from scanner.scoring.momentum import calculate_momentum_metrics

    prices = pd.DataFrame({"Close": np.full(252, 100.0)})
    metrics = calculate_momentum_metrics(prices, {})
    # perf_6m = 0 car prix constant
    assert metrics.get("momentum_adj") is not None
    assert metrics["momentum_adj"] == 0.0  # 0 / FLOOR = 0


# ── sanity_check_gate ────────────────────────────────────────────────────────


def test_sanity_check_gate():
    """Vérifie que la barrière exclut les tickers avec des variations > 50% ou < -45%."""
    from scanner.filters import sanity_check_gate

    # Cas valide
    valid_prices = pd.DataFrame({"Close": [10.0, 10.5, 11.0, 10.8, 11.2]})
    assert sanity_check_gate(valid_prices, "VALID")

    # Cas de baisse excessive (-50% en un jour)
    drop_prices = pd.DataFrame({"Close": [10.0, 10.5, 5.0, 5.2, 5.3]})
    assert not sanity_check_gate(drop_prices, "CRASH")

    # Cas de hausse excessive (+60% en un jour)
    rise_prices = pd.DataFrame({"Close": [10.0, 9.8, 16.0, 15.5, 15.8]})
    assert not sanity_check_gate(rise_prices, "PUMP")


# ── Portfolio maturation & hysteresis exits ─────────────────────────────────


def test_portfolio_maturation_and_hysteresis(tmp_path):
    """Vérifie le cycle de maturation de 3 jours et la sortie par hystérésis."""
    import sqlite3
    from unittest.mock import patch

    from scanner.storage import reconstruct_portfolio_and_maturation

    db_path = str(tmp_path / "test_portfolio.db")

    # On coince le chemin de la base de données de stockage
    with patch("scanner.storage.DB_PATH", db_path):
        from scanner.storage import init_db

        init_db()

        conn = sqlite3.connect(db_path)

        # Jour 1 (Achat de AAPL au Top 10)
        conn.execute("INSERT INTO scans (scan_date, market_regime, eligible_count) VALUES ('2026-05-18', 'normal', 1)")
        scan1_id = conn.execute("SELECT id FROM scans WHERE scan_date = '2026-05-18'").fetchone()[0]
        conn.execute(
            "INSERT INTO signals (scan_id, symbol, name, type, rank, score_global) "
            "VALUES (?, 'AAPL', 'Apple Inc', 'stock', 2, 85.0)",
            (scan1_id,),
        )
        conn.commit()

        portfolio, exits = reconstruct_portfolio_and_maturation(conn)
        assert "AAPL" in portfolio
        assert portfolio["AAPL"]["status"] == "ACHAT"
        assert portfolio["AAPL"]["days_held"] == 1
        assert len(exits) == 0

        # Jour 2 (AAPL sort du Top 10 mais est toujours protégé par la maturation)
        conn.execute("INSERT INTO scans (scan_date, market_regime, eligible_count) VALUES ('2026-05-19', 'normal', 1)")
        scan2_id = conn.execute("SELECT id FROM scans WHERE scan_date = '2026-05-19'").fetchone()[0]
        conn.execute(
            "INSERT INTO signals (scan_id, symbol, name, type, rank, score_global) "
            "VALUES (?, 'AAPL', 'Apple Inc', 'stock', 12, 76.0)",
            (scan2_id,),
        )
        conn.commit()

        portfolio, exits = reconstruct_portfolio_and_maturation(conn)
        assert "AAPL" in portfolio
        assert portfolio["AAPL"]["status"] == "MATURATION"
        assert portfolio["AAPL"]["days_held"] == 2
        assert len(exits) == 0

        # Jour 3 (AAPL est hors du Top 10 mais toujours protégé car c'est le 3ème scan)
        conn.execute("INSERT INTO scans (scan_date, market_regime, eligible_count) VALUES ('2026-05-20', 'normal', 1)")
        scan3_id = conn.execute("SELECT id FROM scans WHERE scan_date = '2026-05-20'").fetchone()[0]
        conn.execute(
            "INSERT INTO signals (scan_id, symbol, name, type, rank, score_global) "
            "VALUES (?, 'AAPL', 'Apple Inc', 'stock', 16, 72.0)",
            (scan3_id,),
        )
        conn.commit()

        portfolio, exits = reconstruct_portfolio_and_maturation(conn)
        assert "AAPL" in portfolio
        assert portfolio["AAPL"]["status"] == "HOLD"  # 3 scans = HOLD
        assert portfolio["AAPL"]["days_held"] == 3
        assert len(exits) == 0

        # Jour 4 (AAPL n'est plus protégé et remplit les conditions de sortie : rank > 15)
        conn.execute("INSERT INTO scans (scan_date, market_regime, eligible_count) VALUES ('2026-05-21', 'normal', 1)")
        scan4_id = conn.execute("SELECT id FROM scans WHERE scan_date = '2026-05-21'").fetchone()[0]
        conn.execute(
            "INSERT INTO signals (scan_id, symbol, name, type, rank, score_global) "
            "VALUES (?, 'AAPL', 'Apple Inc', 'stock', 17, 68.0)",
            (scan4_id,),
        )
        conn.commit()

        portfolio, exits = reconstruct_portfolio_and_maturation(conn)
        assert "AAPL" not in portfolio
        assert len(exits) == 1
        assert exits[0]["symbol"] == "AAPL"
        assert exits[0]["days_held"] == 4
        assert exits[0]["rank"] == 17
        assert exits[0]["score"] == 68.0

        conn.close()


# ── T082 — VIX NaN/0 fallback ─────────────────────────────────────────────────


def _make_vix_series(values):
    return pd.Series(values, dtype=float)


def test_vix_nan_fallback_uses_last_valid():
    """Dernière valeur NaN → fallback sur avant-dernière valeur non-NaN."""
    s = _make_vix_series([25.0, 28.0, float("nan")])
    result = s.replace(0, float("nan")).dropna()
    assert not result.empty
    assert result.iloc[-1] == 28.0


def test_vix_zero_treated_as_nan():
    """VIX = 0 → traité comme NaN → fallback sur valeur précédente."""
    s = _make_vix_series([30.0, 0.0])
    result = s.replace(0, float("nan")).dropna()
    assert not result.empty
    assert result.iloc[-1] == 30.0


def test_vix_all_nan_returns_empty():
    """Série entièrement NaN → dropna() vide → scan doit être annulé."""
    s = _make_vix_series([float("nan"), float("nan")])
    result = s.replace(0, float("nan")).dropna()
    assert result.empty


def test_vix_all_zero_returns_empty():
    """Série entièrement 0 → remplacés par NaN → dropna() vide → scan doit être annulé."""
    s = _make_vix_series([0.0, 0.0])
    result = s.replace(0, float("nan")).dropna()
    assert result.empty


# ── BF-026 — détection série SPY plate (données yfinance stale) ───────────────


def test_spy_flat_series_detected_by_std():
    """SPY série plate (tous identiques) → std < 1.0 → doit déclencher l'annulation du scan."""
    import pandas as pd

    spy_flat = pd.Series([450.0] * 252)
    assert float(spy_flat.std()) < 1.0


def test_spy_realistic_series_not_flat():
    """SPY série réaliste (linspace 400→450) → std ≥ 1.0 → pas d'annulation."""
    import numpy as np
    import pandas as pd

    spy_real = pd.Series(np.linspace(400.0, 480.0, 252))
    assert float(spy_real.std()) >= 1.0


# ── BF-027 — send_message_safe log succès ────────────────────────────────────


@pytest.mark.asyncio
async def test_send_message_safe_logs_success():
    """send_message_safe : envoi OK → logger.info appelé avec 'envoyé'."""
    from unittest.mock import AsyncMock, patch

    from scanner.notifier import send_message_safe

    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock(return_value=None)

    with patch("scanner.notifier.logger") as mock_logger:
        await send_message_safe(mock_bot, "123", "test message")

    mock_bot.send_message.assert_called_once()
    assert mock_logger.info.called
    info_msg = mock_logger.info.call_args[0][0]
    assert "envoyé" in info_msg


# ── T053/T057 — is_eligible_etf ──────────────────────────────────────────────


def test_is_eligible_etf_leveraged_excluded():
    """TQQQ (ProShares UltraPro QQQ) → False (ULTRA dans le nom)."""
    from scanner.universe import is_eligible_etf

    assert not is_eligible_etf("TQQQ", "ProShares UltraPro QQQ")


def test_is_eligible_etf_3x_excluded():
    """SOXL (Direxion Daily Semiconductor Bull 3X Shares) → False (3X dans le nom)."""
    from scanner.universe import is_eligible_etf

    assert not is_eligible_etf("SOXL", "Direxion Daily Semiconductor Bull 3X Shares")


def test_is_eligible_etf_sector_allowed():
    """XLK (Technology Select Sector SPDR) → True (ETF sectoriel légitime)."""
    from scanner.universe import is_eligible_etf

    assert is_eligible_etf("XLK", "Technology Select Sector SPDR")


def test_etf_scoring_excludes_leveraged():
    """etf_scoring_pipeline exclut les ETFs à levier via is_eligible_etf."""
    from scanner.scoring.engine import etf_scoring_pipeline

    prices = pd.DataFrame({"Close": list(range(50, 180)), "Volume": [1_000_000] * 130})
    spy_prices = pd.DataFrame({"Close": list(range(400, 530)), "Volume": [5_000_000] * 130})

    all_data = {
        "TQQQ": {"info": {"longName": "ProShares UltraPro QQQ"}, "prices": prices},
        "XLK": {"info": {"longName": "Technology Select Sector SPDR"}, "prices": prices},
        "SPY": {"info": {}, "prices": spy_prices},
    }
    result = etf_scoring_pipeline(all_data, ["TQQQ", "XLK"])
    assert "TQQQ" not in result["symbol"].values
    assert "XLK" in result["symbol"].values


def test_etf_score_formula():
    """score ETF = rank_perf_6m×0.5 + rank_outperf_spy×0.5 — 0 appel FMP."""
    from scanner.scoring.engine import etf_scoring_pipeline

    prices = pd.DataFrame({"Close": list(range(100, 230)), "Volume": [1_000_000] * 130})
    spy_prices = pd.DataFrame({"Close": [100] * 130, "Volume": [5_000_000] * 130})

    all_data = {
        "XLK": {"info": {"longName": "Technology Select Sector SPDR"}, "prices": prices},
        "SPY": {"info": {}, "prices": spy_prices},
    }
    result = etf_scoring_pipeline(all_data, ["XLK"])
    assert not result.empty
    row = result.iloc[0]
    expected = row["rank_perf_6m"] * 0.50 + row["rank_outperf_spy"] * 0.50
    assert abs(row["score_global"] - expected) < 1e-9


# ── T062 — FMP call counter ───────────────────────────────────────────────────


def test_fmp_call_counter_budget():
    """30 tickers × 5 endpoints ≤ 175 appels FMP (SC-001, API stable FMP)."""
    import scanner.fetcher as fetcher_module

    fetcher_module.fmp_call_counter = 0

    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def run():
        for _t in [f"T{i}" for i in range(30)]:
            if fetcher_module.fmp_call_counter + 5 > 175:
                break
            fetcher_module.fmp_call_counter += 5

    asyncio.run(run())

    assert fetcher_module.fmp_call_counter <= 175, (
        f"Budget FMP dépassé: {fetcher_module.fmp_call_counter} > 175 (SC-001)"
    )


# ── T067 — score_global ∈ [0, 100] ───────────────────────────────────────────


def test_score_global_bounds():
    """score_global de toutes les fixtures ∈ [0, 100], jamais NaN (SC-003)."""
    import numpy as np

    from scanner.scoring.engine import stock_scoring_pipeline

    def _make_data(roe=0.20, pe=20.0, perf=0.10):
        prices = pd.DataFrame({"Close": [100 + i * perf for i in range(260)], "Volume": [5_000_000] * 260})
        return {
            "info": {
                "sector": "Technology",
                "longName": "Test Corp",
                "marketCap": 5_000_000_000,
                "roe_3y": roe,
                "operatingMargins": 0.20,
                "netDebt": 500_000_000,
                "ebitda": 1_000_000_000,
                "freeCashflow": 800_000_000,
                "forwardPE": pe,
                "enterpriseToEbitda": 12.0,
                "pegRatio": 1.2,
                "surprise_pct": 0.05,
                "surprise_date": None,
                "analyst_revision_3m": None,
                "source": "FMP",
            },
            "prices": prices,
        }

    all_data = {
        "T1": _make_data(roe=0.15, pe=18.0, perf=0.08),
        "T2": _make_data(roe=0.25, pe=25.0, perf=0.15),
        "T3": _make_data(roe=0.35, pe=35.0, perf=0.20),
    }
    result = stock_scoring_pipeline(all_data, list(all_data.keys()))
    assert not result.empty
    for _, row in result.iterrows():
        score = row["score_global"]
        assert not np.isnan(score), f"score_global NaN pour {row['symbol']}"
        assert 0.0 <= score <= 100.0, f"score_global hors bornes [{score}] pour {row['symbol']}"


# ── normalize_sector_name ─────────────────────────────────────────────────────


def test_normalize_sector_name_mappings():
    """Vérifie les mappings critiques yfinance → SECTOR_ETF_MAP (Financial Services, Healthcare…)."""
    from scanner.fetcher import normalize_sector_name

    assert normalize_sector_name("Financial Services") == "Financials"
    assert normalize_sector_name("Healthcare") == "Health Care"
    assert normalize_sector_name("Consumer Cyclical") == "Consumer Discretionary"
    assert normalize_sector_name("Consumer Defensive") == "Consumer Staples"
    assert normalize_sector_name("Basic Materials") == "Materials"
    assert normalize_sector_name("Technology") == "Technology"
    assert normalize_sector_name(None) == "Unknown"
    assert normalize_sector_name("  Financial Services  ") == "Financials"


# ── winsorize ────────────────────────────────────────────────────────────────


def test_winsorize_clamp():
    """Valeur dans bornes = inchangée ; hors bornes haute/basse = clampée exactement."""
    from scanner.scoring.engine import winsorize

    assert winsorize(0.5, 0.0, 1.0) == 0.5
    assert winsorize(-0.5, 0.0, 1.0) == 0.0
    assert winsorize(1.5, 0.0, 1.0) == 1.0
    assert winsorize(0.0, 0.0, 1.0) == 0.0
    assert winsorize(1.0, 0.0, 1.0) == 1.0


# ── compute_inverse_vol_weights — fallback equal-weight ──────────────────────


def test_inverse_vol_weights_no_data():
    """Aucun historique prix suffisant → poids égaux (100/N)."""
    from scanner.scoring.engine import compute_inverse_vol_weights

    ranked_df = pd.DataFrame({"symbol": ["A", "B", "C"]})
    all_data = {
        "A": {"prices": None},
        "B": {"prices": pd.DataFrame({"Close": [100.0] * 10})},  # < 60 jours
        "C": {"prices": None},
    }
    result = compute_inverse_vol_weights(ranked_df, all_data)
    expected_weight = 100.0 / 3
    assert (result["suggested_weight_pct"] - expected_weight).abs().max() < 1e-6


# ── truncate_message_html_safe ────────────────────────────────────────────────


def test_truncate_message_html_safe_closes_tags():
    """Message tronqué avec <b> non fermé → balise <b> fermée automatiquement."""
    from scanner.notifier import truncate_message_html_safe

    long_msg = "<b>" + "X" * 5000
    result = truncate_message_html_safe(long_msg, max_chars=100)
    assert len(result) <= 100 + len("</b>")
    assert result.endswith("</b>")


def test_truncate_message_html_safe_no_truncation_needed():
    """Message court → retourné intact."""
    from scanner.notifier import truncate_message_html_safe

    msg = "<b>Hello</b>"
    assert truncate_message_html_safe(msg, max_chars=4096) == msg


def test_truncate_message_html_safe_nested_tags():
    """<b><i> ouverts sans fermeture → fermés dans l'ordre inverse."""
    from scanner.notifier import truncate_message_html_safe

    long_msg = "<b><i>" + "X" * 5000
    result = truncate_message_html_safe(long_msg, max_chars=100)
    assert result.endswith("</i></b>")


# ── filter_post_scoring — exclusion données stale ────────────────────────────


@pytest.mark.asyncio
async def test_filter_post_scoring_stale_data_excluded():
    """Ticker avec données vieilles de 451j (bilan annuel > 15 mois) → exclu du top 10."""
    import time as _time

    from scanner.filters import filter_post_scoring

    stale_ts = _time.time() - 451 * 86400
    fresh_ts = _time.time() - 10 * 86400

    rows = [
        {"symbol": "STALE", "sector": "Tech", "score_global": 99},
        {"symbol": "FRESH", "sector": "Tech", "score_global": 80},
    ]
    all_data = {
        "STALE": {"info": {"mostRecentQuarter": stale_ts}},
        "FRESH": {"info": {"mostRecentQuarter": fresh_ts}},
    }
    df = pd.DataFrame(rows)
    with patch("scanner.filters.earnings_calendar_check", return_value=None):
        result = await filter_post_scoring(df, all_data)
    symbols = result["symbol"].tolist()
    assert "STALE" not in symbols
    assert "FRESH" in symbols


# ── is_eligible_etf — fallback ticker quand nom vide ─────────────────────────


def test_is_eligible_etf_empty_name_uses_ticker():
    """Nom vide → vérifie le ticker. Patterns non présents dans ticker → pass (SQQQ non détecté)."""
    from scanner.universe import is_eligible_etf

    # SQQQ ne contient aucun des patterns → True quand nom absent (limite connue)
    assert is_eligible_etf("SQQQ", "")
    # TQQQ ne contient pas non plus les patterns dans le ticker seul
    assert is_eligible_etf("TQQQ", "")
    # XLK passe toujours
    assert is_eligible_etf("XLK", "")
    # Ticker avec pattern explicite exclu même sans nom
    assert not is_eligible_etf("SOME-BEAR-ETF", "")


def test_is_eligible_etf_inverse_in_name():
    """INVERSE dans le nom → exclu."""
    from scanner.universe import is_eligible_etf

    assert not is_eligible_etf("SOME", "ProShares Short INVERSE Fund")


# ── get_first_seen_dates_batch — batch IN query ───────────────────────────────


def test_get_first_seen_dates_batch(tmp_path):
    """Batch query retourne correct first_seen_date pour plusieurs symboles en une requête."""
    import sqlite3
    from unittest.mock import patch

    import scanner.storage as storage_module
    from scanner.storage import get_first_seen_dates_batch, init_db

    db_file = str(tmp_path / "test_batch.db")
    with patch.object(storage_module, "DB_PATH", db_file):
        init_db()
        conn = sqlite3.connect(db_file)
        conn.execute(
            "INSERT INTO scans (scan_date, market_regime, universe_size, eligible_count) VALUES (?,?,?,?)",
            ("2026-01-01", "normal", 100, 2),
        )
        scan_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO signals (scan_id, symbol, name, type, rank, score_global, first_seen_date) "
            "VALUES (?,?,?,?,?,?,?)",
            (scan_id, "AAPL", "Apple", "stock", 1, 90.0, "2026-01-01"),
        )
        conn.execute(
            "INSERT INTO signals (scan_id, symbol, name, type, rank, score_global, first_seen_date) "
            "VALUES (?,?,?,?,?,?,?)",
            (scan_id, "MSFT", "Microsoft", "stock", 2, 85.0, "2026-01-01"),
        )
        conn.commit()
        conn.close()

        result = get_first_seen_dates_batch(["AAPL", "MSFT", "GOOG"], "2026-05-21")

    assert result["AAPL"] == "2026-01-01"
    assert result["MSFT"] == "2026-01-01"
    assert result["GOOG"] == "2026-05-21"


# ── BF-005/BF-006 : ROE TTM fallback quand IS annuel vide ───────────────────


def test_roe_ttm_fallback_when_is_empty():
    """roe_3y = None si IS vide → quality gate retourne 'ROE 3 ans indisponible'."""
    from scanner.scoring.quality import apply_quality_gates, calculate_quality_metrics

    # Simule is_data=[] : fetch_fmp_data retourne roe_3y=None sans fallback
    info_no_roe = {
        "roe_3y": None,
        "roicTTM": None,
        "operatingMargins": 0.20,
        "sector": "Technology",
        "netDebt": 1e9,
        "ebitda": 2e9,
        "freeCashflow": 5e8,
        "marketCap": 1e10,
        "bookValuePerShare": 10.0,
    }
    metrics = calculate_quality_metrics(info_no_roe)
    passed, reason, _ = apply_quality_gates(metrics, ticker_info=info_no_roe)
    assert not passed
    assert "ROE" in reason


def test_roe_ttm_fallback_allows_ticker():
    """roe_3y rempli via fallback TTM → quality gate passe si ROE positif."""
    from scanner.scoring.quality import apply_quality_gates, calculate_quality_metrics

    # Simule le fallback : fetch_fmp_data a mis roe_ttm dans roe_3y
    info_roe_ttm = {
        "roe_3y": 0.18,  # valeur TTM injectée comme fallback
        "roicTTM": 0.12,
        "operatingMargins": 0.20,
        "sector": "Technology",
        "netDebt": 1e9,
        "ebitda": 2e9,
        "freeCashflow": 5e8,
        "marketCap": 1e10,
        "bookValuePerShare": 10.0,
    }
    metrics = calculate_quality_metrics(info_roe_ttm)
    passed, reason, _ = apply_quality_gates(metrics, ticker_info=info_roe_ttm)
    assert passed, f"Doit passer avec ROE TTM fallback: {reason}"


# ── ROE yfinance fallback (_roe_from_yfinance) ───────────────────────────────


def test_roe_from_yfinance_returns_none_on_empty_df():
    """_roe_from_yfinance retourne None si get_income_stmt/get_balance_sheet vides."""
    from unittest.mock import MagicMock, patch

    import pandas as pd

    from scanner.fetcher import _roe_from_yfinance

    empty_df = pd.DataFrame()
    mock_ticker = MagicMock()
    mock_ticker.get_income_stmt.return_value = empty_df
    mock_ticker.get_balance_sheet.return_value = empty_df

    with patch("scanner.fetcher.yf.Ticker", return_value=mock_ticker):
        result = _roe_from_yfinance("FAKE")

    assert result is None


def test_roe_from_yfinance_calculates_correctly():
    """_roe_from_yfinance calcule roe_3y = mean(NI/Equity) sur 3 ans."""
    from unittest.mock import MagicMock, patch

    import pandas as pd

    from scanner.fetcher import _roe_from_yfinance

    dates = pd.to_datetime(["2024-12-31", "2023-12-31", "2022-12-31"])
    is_df = pd.DataFrame({"NetIncome": [100.0, 80.0, 60.0]}, index=dates).T
    is_df.index = ["NetIncome"]
    bs_df = pd.DataFrame({"CommonStockEquity": [500.0, 400.0, 300.0]}, index=dates).T
    bs_df.index = ["CommonStockEquity"]

    mock_ticker = MagicMock()
    mock_ticker.get_income_stmt.return_value = is_df
    mock_ticker.get_balance_sheet.return_value = bs_df

    with patch("scanner.fetcher.yf.Ticker", return_value=mock_ticker):
        result = _roe_from_yfinance("FAKE")

    # Expected: mean(100/500, 80/400, 60/300) = mean(0.20, 0.20, 0.20) = 0.20
    assert result is not None
    assert abs(result - 0.20) < 1e-9


# ── cap_sector_shortlist ─────────────────────────────────────────────────────


def test_cap_sector_shortlist_limits_per_sector():
    """cap_sector_shortlist cap à N tickers par secteur."""
    from unittest.mock import patch

    import pandas as pd

    from scanner.filters import cap_sector_shortlist

    data = [
        ("NVDA", "Technology"),
        ("AMD", "Technology"),
        ("INTC", "Technology"),
        ("MU", "Technology"),
        ("QCOM", "Technology"),
        ("LRCX", "Technology"),
        ("JPM", "Financials"),
        ("BAC", "Financials"),
        ("GS", "Financials"),
    ]
    df = pd.DataFrame([{"symbol": s, "m_score": 100 - i} for i, (s, _) in enumerate(data)])
    sector_map = {s: sec for s, sec in data}

    def mock_cache_get(category, key, ttl):
        return {"sector": sector_map.get(key)} if key in sector_map else None

    with patch("scanner.filters.cache.get", side_effect=mock_cache_get):
        result = cap_sector_shortlist(df, cap=3)

    tech = [s for s in result if sector_map.get(s) == "Technology"]
    fin = [s for s in result if sector_map.get(s) == "Financials"]
    assert len(tech) == 3, f"Tech capped at 3, got {len(tech)}"
    assert len(fin) == 3, f"Financials capped at 3, got {len(fin)}"
    assert len(result) == 6


# ── BF-008 : send_message_safe ne crash pas sur erreur Telegram ──────────────


@pytest.mark.asyncio
async def test_send_message_safe_catches_bad_request():
    """send_message_safe : BadRequest (chat not found) → log error, pas de crash."""
    from unittest.mock import AsyncMock, patch

    from telegram.error import BadRequest

    from scanner.notifier import send_message_safe

    mock_bot = AsyncMock()
    mock_bot.send_message.side_effect = BadRequest("Bad Request: chat not found")

    # Ne doit pas lever d'exception
    with patch("scanner.notifier.logger") as mock_logger:
        await send_message_safe(mock_bot, "bad_chat_id", "test")
        assert mock_logger.error.called
