import pandas as pd

from scanner.filters import filter_post_scoring
from scanner.scoring.engine import compute_percentile_ranks
from scanner.scoring.momentum import apply_momentum_penalties, calculate_momentum_metrics
from scanner.scoring.quality import apply_quality_gates, calculate_quality_metrics
from scanner.scoring.valuation import apply_valuation_gates, calculate_valuation_metrics


def test_quality_logic():
    # Cas nominal
    info = {
        "returnOnEquity": 0.20,
        "operatingMargins": 0.15,
        "totalDebt": 100,
        "totalCash": 50,
        "ebitda": 25,
        "freeCashflow": 10,
        "marketCap": 100
    }
    metrics = calculate_quality_metrics(info)
    assert metrics["roe"] == 0.20
    assert metrics["debt_ebitda"] == 2.0 # (100-50)/25
    assert metrics["fcf_yield"] == 0.1

    # Gate: ROE négatif
    metrics["roe"] = -0.05
    ok, reason = apply_quality_gates(metrics)
    assert not ok
    assert "ROE négatif" in reason

    # Gate: Dette trop élevée
    metrics["roe"] = 0.20
    metrics["debt_ebitda"] = 7.0
    ok, reason = apply_quality_gates(metrics)
    assert not ok
    assert "Dette/EBITDA trop élevé" in reason

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
    ok, reason = apply_valuation_gates(metrics)
    assert ok

    metrics["pe"] = 85
    ok, reason = apply_valuation_gates(metrics)
    assert not ok
    assert "P/E trop élevé" in reason

    # Gate: P/E trop élevé pour autre secteur (limit 50)
    metrics["sector"] = "Consumer Staples"
    metrics["pe"] = 55
    ok, reason = apply_valuation_gates(metrics)
    assert not ok

def test_momentum_logic():
    # Mock info for sales growth
    info = {"revenueGrowth": 0.20}
    # Mock prices (130 days of data)
    prices = pd.DataFrame({
        "Close": [100] * 130
    })
    metrics = calculate_momentum_metrics(prices, info)
    assert metrics["sales_growth"] == 0.20
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

    # Nouvelles pondérations du config.yaml : 0.40, 0.25, 0.35
    expected = 80 * 0.40 + 60 * 0.25 + 90 * 0.35 # 32 + 15 + 31.5 = 78.5

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
    # Test 1: Financials excluded from debt gate
    info_fin = {
        "sector": "Financials",
        "returnOnEquity": 0.15,
        "totalDebt": 1000,
        "totalCash": 100,
        "ebitda": 50, # Debt/EBITDA = 18x (Normally excluded)
        "marketCap": 10000
    }
    metrics = calculate_quality_metrics(info_fin)
    # Dans Financials, debt_ebitda doit être None
    assert metrics["debt_ebitda"] is None
    ok, _ = apply_quality_gates(metrics)
    assert ok # Ne doit pas être exclu par la dette

    # Test 2: Biotech exception for negative P/E
    info_bio = {
        "sector": "Health Care",
        "forwardPE": -10,
        "marketCap": 4_000_000_000, # < 5B$
    }
    v_metrics = calculate_valuation_metrics(info_bio)
    ok, _ = apply_valuation_gates(v_metrics)
    assert ok # Pas exclu malgré P/E négatif

def test_etf_pipeline():
    from scanner.scoring.engine import etf_scoring_pipeline
    # Mock data
    prices = pd.DataFrame({
        "Close": [100] * 130, # Constant price
        "Volume": [1000] * 130
    })
    # Variation volume
    prices.iloc[-20:, 1] = 2000 # Volume double récemment
    
    all_data = {
        "ETF1": {"prices": prices},
        "SPY": {"prices": pd.DataFrame({"Close": [100] * 130})}
    }
    
    ranked = etf_scoring_pipeline(all_data, ["ETF1"])
    assert not ranked.empty
    assert ranked.iloc[0]["symbol"] == "ETF1"
    assert ranked.iloc[0]["vol_trend"] > 0
