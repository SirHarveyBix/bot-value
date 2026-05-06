import numpy as np
import pandas as pd

from scanner.config import CONFIG
from scanner.scoring.momentum import SECTOR_ETF_MAP, apply_momentum_penalties, calculate_momentum_metrics
from scanner.scoring.quality import apply_quality_gates, calculate_quality_metrics
from scanner.scoring.valuation import apply_valuation_gates, calculate_valuation_metrics


def compute_percentile_ranks(df, column, ascending=True):
    """Calcule le percentile rank (0-100) pour une colonne."""
    # Si df est en fait une série (via transform), on l'utilise directement
    if isinstance(df, pd.Series):
        if df.isnull().all():
            return pd.Series(index=df.index, data=np.nan)
        return df.rank(pct=True, ascending=ascending) * 100

    # Si df est un DataFrame
    if column not in df.columns:
        # Fallback si le DataFrame n'a qu'une colonne (cas fréquent en transform)
        if len(df.columns) == 1:
            return df.iloc[:, 0].rank(pct=True, ascending=ascending) * 100
        return pd.Series(index=df.index, data=np.nan)

    if df[column].isnull().all():
        return pd.Series(index=df.index, data=np.nan)
    return df[column].rank(pct=True, ascending=ascending) * 100

def stock_scoring_pipeline(all_data, symbols):
    """Pipeline de scoring pour les actions."""
    rows = []
    for symbol in symbols:
        data = all_data.get(symbol)
        if not data or data["info"] is None or data["prices"] is None:
            continue

        info = data["info"]
        prices = data["prices"]

        q_metrics = calculate_quality_metrics(info)
        v_metrics = calculate_valuation_metrics(info)

        # Récupérer l'ETF sectoriel
        sector = v_metrics.get("sector")
        s_etf = SECTOR_ETF_MAP.get(sector, "SPY")
        s_data = all_data.get(s_etf, {}).get("prices")

        m_metrics = calculate_momentum_metrics(prices, info, s_data)

        q_ok, q_reason = apply_quality_gates(q_metrics)
        v_ok, v_reason = apply_valuation_gates(v_metrics)

        if not q_ok:
            continue

        row = {
            "symbol": symbol,
            "sector": sector,
            **q_metrics,
            **v_metrics,
            **m_metrics,
            "v_ok": v_ok
        }
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Ranking
    df["rank_roe"] = compute_percentile_ranks(df, "roe")
    df["rank_margin"] = df.groupby("sector")["margin"].transform(
        compute_percentile_ranks, column="margin"
    )
    df["rank_debt"] = compute_percentile_ranks(df, "debt_ebitda", ascending=False)
    df["rank_fcf"] = compute_percentile_ranks(df, "fcf_yield")
    df["rank_pe"] = df.groupby("sector")["pe"].transform(
        compute_percentile_ranks, column="pe", ascending=False
    )
    df["rank_ev_ebitda"] = df.groupby("sector")["ev_ebitda"].transform(
        compute_percentile_ranks, column="ev_ebitda", ascending=False
    )
    df["rank_peg"] = compute_percentile_ranks(df, "peg", ascending=False)
    df["rank_perf_6m"] = compute_percentile_ranks(df, "perf_6m")
    df["rank_outperf_6m"] = compute_percentile_ranks(df, "outperf_6m")
    df["rank_perf_3m"] = compute_percentile_ranks(df, "perf_3m")
    df["rank_eps_rev"] = compute_percentile_ranks(df, "eps_revision")

    # Scores
    qw = CONFIG["scoring"]["quality_subweights"]
    df["score_quality"] = (df["rank_roe"].fillna(0) * qw["roe"] + df["rank_margin"].fillna(0) * qw["margin"] +
                          df["rank_fcf"].fillna(0) * qw["fcf_yield"] + df["rank_debt"].fillna(0) * qw["debt_ebitda"])

    vw = CONFIG["scoring"]["valuation_subweights"]
    df["score_valuation"] = (
        df["rank_pe"].fillna(0) * vw["pe_forward"] +
        df["rank_ev_ebitda"].fillna(0) * vw["ev_ebitda"] +
        df["rank_peg"].fillna(0) * vw["peg"]
    )
    mw = CONFIG["scoring"]["momentum_subweights"]
    df["score_momentum"] = (
        df["rank_perf_6m"].fillna(0) * mw["perf_6m"] +
        df["rank_outperf_6m"].fillna(0) * mw["outperf_6m"] +
        df["rank_perf_3m"].fillna(0) * mw["perf_3m"] +
        df["rank_eps_rev"].fillna(0) * mw["eps_revision"]
    )

    df["score_momentum"] = df.apply(lambda r: apply_momentum_penalties(r["score_momentum"], r), axis=1)

    # Global
    w = CONFIG["scoring"]["weights"]
    df["score_global"] = df.apply(
        lambda r: (
            r["score_quality"] * w["quality"] +
            r["score_valuation"] * w["valuation"] +
            r["score_momentum"] * w["momentum"]
        ) if r["v_ok"] else (r["score_quality"] * 0.5 + r["score_momentum"] * 0.5),
        axis=1
    )
    return df.sort_values("score_global", ascending=False)

def etf_scoring_pipeline(all_data, etfs):
    """Pipeline de scoring simplifié pour les ETFs."""
    rows = []
    spy_data = all_data.get("SPY", {}).get("prices")

    for symbol in etfs:
        data = all_data.get(symbol)
        if not data or data["prices"] is None:
            continue

        prices = data["prices"]
        if len(prices) < 126:
            continue

        p_now = prices["Close"].iloc[-1]
        perf_6m = (p_now - prices["Close"].iloc[-126]) / prices["Close"].iloc[-126]

        outperf_spy = None
        if spy_data is not None and len(spy_data) >= 126:
            spy_perf = (spy_data["Close"].iloc[-1] - spy_data["Close"].iloc[-126]) / spy_data["Close"].iloc[-126]
            outperf_spy = perf_6m - spy_perf

        # Volume trend
        vol_moy_20j = prices["Volume"].iloc[-20:].mean()
        vol_moy_hist = prices["Volume"].iloc[-63:-43].mean() if len(prices) >= 63 else vol_moy_20j
        vol_trend = (vol_moy_20j - vol_moy_hist) / vol_moy_hist if vol_moy_hist > 0 else 0

        rows.append({
            "symbol": symbol,
            "perf_6m": perf_6m,
            "outperf_spy": outperf_spy,
            "vol_trend": vol_trend
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["rank_perf_6m"] = compute_percentile_ranks(df, "perf_6m")
    df["rank_outperf_spy"] = compute_percentile_ranks(df, "outperf_spy")
    df["rank_vol_trend"] = compute_percentile_ranks(df, "vol_trend")

    df["score_global"] = (df["rank_perf_6m"].fillna(0) * 0.40 +
                         df["rank_outperf_spy"].fillna(0) * 0.35 +
                         df["rank_vol_trend"].fillna(0) * 0.25)

    return df.sort_values("score_global", ascending=False)
