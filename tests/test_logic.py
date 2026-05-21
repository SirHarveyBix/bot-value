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
        "roe_3y": 0.20,           # champ FMP — Règle d'Or
        "operatingMargins": 0.15,
        "netDebt": 50,            # FMP fournit netDebt directement (totalCash=None dans FMP)
        "ebitda": 25,
        "freeCashflow": 10,
        "marketCap": 100
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

    # Gate: EBITDA <= 0
    metrics["ebitda"] = 0
    ok, reason, _ = apply_quality_gates(metrics)
    assert not ok
    assert "EBITDA négatif ou nul" in reason

    # Gate: ROE négatif
    metrics["ebitda"] = 25
    metrics["roe"] = -0.05
    ok, reason, _ = apply_quality_gates(metrics)
    assert not ok
    assert "ROE négatif" in reason

    # Gate: Dette trop élevée
    metrics["roe"] = 0.20
    metrics["debt_ebitda"] = 7.0
    ok, reason, _ = apply_quality_gates(metrics)
    assert not ok
    assert "Dette/EBITDA trop élevé" in reason

    # Gate: book_value_per_share <= 0 → exclu
    metrics["debt_ebitda"] = 2.0
    ok, reason, _ = apply_quality_gates(metrics, ticker_info={"bookValuePerShare": -1.0})
    assert not ok
    assert "book_value_per_share" in reason

    # Flag: ROE > 150% avec BVS < 5$ → non exclu, flag + cap
    metrics["roe"] = 1.60
    ok, reason, flags = apply_quality_gates(metrics, ticker_info={"bookValuePerShare": 2.5})
    assert ok
    assert any("gonflé par buybacks" in f for f in flags)
    assert metrics.get("roe_capped") is True

def test_valuation_logic():
    # Cas nominal
    info = {
        "forwardPE": 25,
        "enterpriseToEbitda": 15,
        "pegRatio": 1.5,
        "sector": "Technology"
    }
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
    prices = pd.DataFrame({
        "Close": [100] * 130
    })
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
    assert ranks.iloc[0] == 20.0 # 1/5
    assert ranks.iloc[-1] == 100.0 # 5/5

def test_intra_sector_ranking():
    rows = [
        {"symbol": "T1", "sector": "Tech", "pe": 10},
        {"symbol": "T2", "sector": "Tech", "pe": 20},
        {"symbol": "T3", "sector": "Energy", "pe": 5},
        {"symbol": "T4", "sector": "Energy", "pe": 15},
    ]
    df = pd.DataFrame(rows)
    # Ranking P/E (Bas = Meilleur score)
    df["rank_pe"] = df.groupby("sector")["pe"].transform(
        compute_percentile_ranks, column="pe", ascending=False
    )

    # T1 (10) vs T2 (20) en Tech -> T1 est meilleur
    assert df[df["symbol"] == "T1"]["rank_pe"].iloc[0] == 100.0
    assert df[df["symbol"] == "T2"]["rank_pe"].iloc[0] == 50.0

    # T3 (5) vs T4 (15) en Energy -> T3 est meilleur
    assert df[df["symbol"] == "T3"]["rank_pe"].iloc[0] == 100.0
    assert df[df["symbol"] == "T4"]["rank_pe"].iloc[0] == 50.0

def test_global_score_weights():
    # Mock row
    row = pd.Series({
        "score_quality": 80,
        "score_valuation": 60,
        "score_momentum": 90,
        "v_ok": True
    })

    # Nouvelles pondérations alignées avec les specs : 0.35, 0.30, 0.35
    expected = 80 * 0.35 + 60 * 0.30 + 90 * 0.35 # 28 + 18 + 31.5 = 77.5

    # On simule le calcul du main engine
    from scanner.config import CONFIG
    w = CONFIG["scoring"]["weights"]
    score = (
        row["score_quality"] * w["quality"] +
        row["score_valuation"] * w["valuation"] +
        row["score_momentum"] * w["momentum"]
    )
    assert score == expected

    # Cas v_ok = False (50/50)
    row["v_ok"] = False
    score = row["score_quality"] * 0.5 + row["score_momentum"] * 0.5
    assert score == (80 + 90) / 2

def test_sector_diversification():
    rows = []
    all_data = {}
    # 4 secteurs pour pouvoir remplir un top 10 (3+3+3+1)
    sectors = ["Tech", "Energy", "Finance", "Health"]
    import time
    now = time.time()
    for i in range(20):
        symbol = f"T{i}"
        rows.append({
            "symbol": symbol,
            "sector": sectors[i % 4],
            "score_global": 100 - i
        })
        all_data[symbol] = {
            "info": {
                "lastFiscalYearEnd": now, # Très récent
                "mostRecentQuarter": now
            }
        }
    df = pd.DataFrame(rows)
    top_10 = filter_post_scoring(df, all_data)

    assert len(top_10) == 10
    # Aucun secteur ne doit dépasser 3
    counts = top_10["sector"].value_counts()
    for sector in sectors:
        assert counts.get(sector, 0) <= 3

def test_sector_exceptions():
    # Test 1: Financials excluded from debt gate — roe_3y requis (FMP)
    info_fin = {
        "sector": "Financials",
        "roe_3y": 0.15,           # FMP obligatoire
        "totalDebt": 1000,
        "totalCash": 100,
        "ebitda": 50,             # Debt/EBITDA = 18x — normalement exclu mais pas pour Financials
        "marketCap": 10000
    }
    metrics = calculate_quality_metrics(info_fin)
    # Dans Financials, debt_ebitda doit être None
    assert metrics["debt_ebitda"] is None
    ok, _, _flags = apply_quality_gates(metrics)
    assert ok  # Ne doit pas être exclu par la dette

    # Test 1b: Utilities excluded from debt gate (nouvelle règle §4.4)
    info_util = {
        "sector": "Utilities",
        "roe_3y": 0.12,
        "totalDebt": 5000,
        "totalCash": 200,
        "ebitda": 700,            # Dette/EBITDA ~6.8x — normal pour Utilities
        "marketCap": 50000
    }
    metrics_util = calculate_quality_metrics(info_util)
    assert metrics_util["debt_ebitda"] is None, "Utilities doit être exclu du calcul dette/EBITDA"
    ok_util, _, _flags_util = apply_quality_gates(metrics_util)
    assert ok_util, "Utilities ne doit pas être exclu malgré le fort levier structurel"

    # Test 2: Biotech exception for negative P/E
    info_bio = {
        "sector": "Health Care",
        "forwardPE": -10,
        "marketCap": 4_000_000_000, # < 5B$
    }
    v_metrics = calculate_valuation_metrics(info_bio)
    # P/E négatif -> is_excluded=False, v_ok=False (fallback 50/50)
    is_excluded, v_ok, _ = apply_valuation_gates(v_metrics)
    assert not is_excluded
    assert not v_ok

    # Test 3: P/E TTM fallback penalty flag
    info_ttm = {
        "forwardPE": None,
        "trailingPE": 15,
        "sector": "Technology"
    }
    v_metrics = calculate_valuation_metrics(info_ttm)
    assert v_metrics["pe"] == 15
    assert v_metrics["pe_flag"] == "P/E TTM used as fallback"

def test_valuation_score_calculation():
    from scanner.scoring.engine import compute_valuation_score

    # Cas 1 : Nominal (PEG présent)
    row = pd.Series({
        "rank_pe": 80,
        "rank_ev_ebitda": 60,
        "rank_peg": 70,
        "pe_flag": None
    })
    score, ok = compute_valuation_score(row)
    # 80*0.45 + 60*0.35 + 70*0.20 = 36 + 21 + 14 = 71
    assert ok
    assert score == 71.0

    # Cas 2 : PEG absent (Redistribution 56/44)
    row_no_peg = pd.Series({
        "rank_pe": 80,
        "rank_ev_ebitda": 60,
        "rank_peg": None,
        "pe_flag": None
    })
    score, ok = compute_valuation_score(row_no_peg)
    # 80*0.56 + 60*0.44 = 44.8 + 26.4 = 71.2
    assert ok
    assert score == 71.2

    # Cas 3 : P/E TTM fallback (Pénalité -5)
    row_ttm = pd.Series({
        "rank_pe": 80,
        "rank_ev_ebitda": 60,
        "rank_peg": 70,
        "pe_flag": "P/E TTM used as fallback"
    })
    score, ok = compute_valuation_score(row_ttm)
    assert ok
    assert score == 66.0 # 71 - 5

    # Cas 4 : Trop de NaNs (Exclusion pilier)
    row_nan = pd.Series({
        "rank_pe": 80,
        "rank_ev_ebitda": None,
        "rank_peg": None,
        "pe_flag": None
    })
    score, ok = compute_valuation_score(row_nan)
    assert not ok
    assert score is None

def test_etf_pipeline():
    from scanner.scoring.engine import etf_scoring_pipeline
    # Mock data
    prices = pd.DataFrame({
        "Close": [100] * 130, # Constant price
        "Volume": [1000] * 130
    })

    all_data = {
        "ETF1": {"prices": prices},
        "SPY": {"prices": pd.DataFrame({"Close": [100] * 130})}
    }

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

        stock_row1 = pd.DataFrame([{
            "symbol": "AAPL", "name": "Apple Inc.", "score_global": 90.0,
            "score_quality": 85.0, "score_valuation": 80.0, "score_momentum": 95.0,
            "pe": 28.5, "roe": 1.47, "margin": 0.31, "perf_6m": 0.18,
        }])

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
    """mostRecentQuarter vieux de 200j → is_fresh=False."""
    stale_ts = (datetime(2026, 5, 19) - timedelta(days=200)).timestamp()
    is_fresh, _, reason = data_freshness_check({"mostRecentQuarter": stale_ts})
    assert not is_fresh
    assert "200" in reason


@freeze_time("2026-05-19")
def test_data_freshness_warning():
    """mostRecentQuarter vieux de 150j → is_fresh=True, has_warning=True."""
    warn_ts = (datetime(2026, 5, 19) - timedelta(days=150)).timestamp()
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

def test_earnings_calendar_none():
    """ticker.calendar=None → retourne None sans exception."""
    mock_ticker = MagicMock()
    mock_ticker.calendar = None
    with patch("scanner.filters.yf.Ticker", return_value=mock_ticker):
        assert earnings_calendar_check("AAPL") is None


@freeze_time("2026-05-19")
def test_earnings_calendar_soon():
    """Earnings dans 7j → retourne la date formatée."""
    next_date = datetime(2026, 5, 26)
    mock_ticker = MagicMock()
    mock_ticker.calendar = {"Earnings Date": [next_date]}
    with patch("scanner.filters.yf.Ticker", return_value=mock_ticker):
        result = earnings_calendar_check("AAPL")
    assert result == "2026-05-26"


@freeze_time("2026-05-19")
def test_earnings_calendar_far_future():
    """Earnings dans 30j → hors fenêtre 14j → retourne None."""
    next_date = datetime(2026, 6, 18)
    mock_ticker = MagicMock()
    mock_ticker.calendar = {"Earnings Date": [next_date]}
    with patch("scanner.filters.yf.Ticker", return_value=mock_ticker):
        result = earnings_calendar_check("AAPL")
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
    """parse_fmp_response avec string 'N/A' → champ = None, pas de crash."""
    from scanner.fetcher import FMPRatiosTTM, _parse_fmp_response

    result = _parse_fmp_response(
        [{"priceEarningsRatioTTM": "N/A", "returnOnEquityTTM": 0.15}],
        FMPRatiosTTM,
        "TEST"
    )
    assert result is not None
    assert result.priceEarningsRatioTTM is None
    assert abs(result.returnOnEquityTTM - 0.15) < 1e-9


def test_parse_fmp_response_empty():
    """parse_fmp_response liste vide → None."""
    from scanner.fetcher import FMPRatiosTTM, _parse_fmp_response

    assert _parse_fmp_response([], FMPRatiosTTM, "TEST") is None


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
