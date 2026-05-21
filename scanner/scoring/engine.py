from __future__ import annotations

from datetime import date as _date

import numpy as np
import pandas as pd

from scanner.config import CONFIG, logger
from scanner.filters import sanity_check_gate
from scanner.scoring.momentum import SECTOR_ETF_MAP, apply_momentum_penalties, calculate_momentum_metrics
from scanner.scoring.quality import apply_quality_gates, calculate_quality_metrics
from scanner.scoring.valuation import apply_valuation_gates, calculate_valuation_metrics
from scanner.universe import is_eligible_etf

RATIO_CLAMP: dict[str, tuple[float, float]] = {
    "roe": (0.0, 1.50),
    "margin": (-0.50, 0.60),
    "fcf_yield": (-0.20, 0.30),
    "debt_ebitda": (0.0, 10.0),
    "pe": (1.0, 60.0),
    "ev_ebitda": (0.0, 40.0),
    "peg": (-5.0, 5.0),
}


def winsorize(value: float, low: float, high: float) -> float:
    """Clamp value dans [low, high] — traite les anomalies de parsing FMP (0.001, 999) sans exclure le ticker."""
    return max(low, min(high, value))


def _apply_winsorization(df: pd.DataFrame) -> pd.DataFrame:
    """Applique RATIO_CLAMP sur toutes les colonnes de ratio présentes dans df."""
    for col, (lo, hi) in RATIO_CLAMP.items():
        if col in df.columns:
            _lo, _hi = lo, hi
            df[col] = df[col].apply(lambda v, lo=_lo, hi=_hi: winsorize(v, lo, hi) if pd.notna(v) else v)
    return df


def compute_percentile_ranks(df, column, ascending=True):
    """Calcule le percentile rank (0-100) pour une colonne."""
    if isinstance(df, pd.Series):
        if df.isnull().all():
            return pd.Series(index=df.index, data=np.nan)
        return df.rank(pct=True, ascending=ascending) * 100

    if column not in df.columns:
        if len(df.columns) == 1:
            return df.iloc[:, 0].rank(pct=True, ascending=ascending) * 100
        return pd.Series(index=df.index, data=np.nan)

    if df[column].isnull().all():
        return pd.Series(index=df.index, data=np.nan)
    return df[column].rank(pct=True, ascending=ascending) * 100


def compute_momentum_weights(surprise_date: str | None, base_weights: dict, today: _date) -> dict:
    """Calcule les poids momentum avec décroissance linéaire earnings surprise sur 90j (Lacune 6)."""
    w = base_weights.copy()
    if surprise_date:
        days_since = (today - _date.fromisoformat(surprise_date)).days
        # Clamp [0, 1] : date future (days_since < 0) garde poids plein ; > 90j → nul
        decay = max(0.0, min(1.0, 1.0 - days_since / 90))
        effective_surprise = w["surprise_earnings"] * decay
    else:
        effective_surprise = 0.0
    freed = w["surprise_earnings"] - effective_surprise
    w["surprise_earnings"] = effective_surprise
    if freed > 0:
        others = {k: v for k, v in w.items() if k != "surprise_earnings"}
        total_others = sum(others.values())
        for k in others:
            w[k] += freed * (w[k] / total_others)
    return w


def momentum_screening_pipeline(price_data, symbols):
    """Pipeline initial pour filtrer les tickers par momentum pur."""
    rows = []

    for symbol in symbols:
        prices = None
        if isinstance(price_data.columns, pd.MultiIndex):
            if symbol in price_data.columns.levels[0]:
                prices = price_data[symbol]

        if prices is None or len(prices) < 126:
            continue

        m_metrics = calculate_momentum_metrics(prices, {}, None)

        rows.append({"symbol": symbol, "perf_6m": m_metrics.get("perf_6m", 0), "perf_3m": m_metrics.get("perf_3m", 0)})

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["m_score"] = df["perf_6m"] * 0.6 + df["perf_3m"] * 0.4
    return df.sort_values("m_score", ascending=False)


def compute_valuation_score(row):
    vw = CONFIG["scoring"]["valuation_subweights"]

    v_ranks = [row["rank_pe"], row["rank_ev_ebitda"], row["rank_peg"]]
    nan_count = sum(1 for r in v_ranks if pd.isna(r))

    if nan_count >= 2:
        return None, False

    if pd.isna(row["rank_peg"]):
        v_score = (row["rank_pe"] or 0) * 0.56 + (row["rank_ev_ebitda"] or 0) * 0.44
    else:
        v_score = (
            (row["rank_pe"] or 0) * vw["pe_forward"]
            + (row["rank_ev_ebitda"] or 0) * vw["ev_ebitda"]
            + (row["rank_peg"] or 0) * vw["peg"]
        )

    if pd.notna(row.get("pe_flag")):
        v_score -= 5

    return max(0, v_score), True


def stock_scoring_pipeline(all_data, symbols, exclusions_out: list | None = None):
    """Pipeline de scoring pour les actions."""
    rows = []
    for symbol in symbols:
        data = all_data.get(symbol)
        if not data or data["info"] is None or data["prices"] is None:
            continue

        info = data["info"]
        prices = data["prices"]

        # Sanity Check Gate (baisse < -45% ou hausse > +50% journalière)
        if not sanity_check_gate(prices, symbol):
            if exclusions_out is not None:
                exclusions_out.append(
                    {
                        "symbol": symbol,
                        "name": info.get("longName", symbol),
                        "gate": "sanity",
                        "reason": "Variation journalière anormale (split / glitch)",
                    }
                )
            continue

        # T022: Exclusion sector=None (Lacune 7)
        if info.get("sector") is None:
            logger.warning(f"Exclusion {symbol}: sector=None (sector_missing)")
            if exclusions_out is not None:
                exclusions_out.append(
                    {
                        "symbol": symbol,
                        "name": info.get("longName", symbol),
                        "gate": "données",
                        "reason": "Secteur inconnu",
                    }
                )
            continue

        q_metrics = calculate_quality_metrics(info)
        v_metrics = calculate_valuation_metrics(info)

        sector = v_metrics.get("sector")
        s_etf = SECTOR_ETF_MAP.get(sector, "SPY")
        s_data = all_data.get(s_etf, {}).get("prices")

        m_metrics = calculate_momentum_metrics(prices, info, s_data)

        q_ok, q_reason, q_flags = apply_quality_gates(q_metrics, ticker_info=info)
        v_excluded, v_ok, v_reason = apply_valuation_gates(v_metrics)

        if not q_ok:
            logger.info(f"Exclusion {symbol} (Qualité): {q_reason}")
            if exclusions_out is not None:
                exclusions_out.append(
                    {"symbol": symbol, "name": info.get("longName", symbol), "gate": "qualité", "reason": q_reason}
                )
            continue

        if v_excluded:
            logger.info(f"Exclusion {symbol} (Valorisation): {v_reason}")
            if exclusions_out is not None:
                exclusions_out.append(
                    {"symbol": symbol, "name": info.get("longName", symbol), "gate": "valorisation", "reason": v_reason}
                )
            continue

        row = {
            "symbol": symbol,
            "name": info.get("longName", symbol),
            "sector": sector,
            "mcap_b": info.get("marketCap", 0) / 1e9 if info.get("marketCap") else 0,
            "surprise_date": info.get("surprise_date"),
            "analyst_revision_3m": info.get("analyst_revision_3m"),
            "roe_capped": q_metrics.get("roe_capped", False),
            "quality_flags": q_flags,
            **q_metrics,
            **v_metrics,
            **m_metrics,
            "v_ok": v_ok,
            "pe_flag": v_metrics.get("pe_flag"),
        }
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Winsorisation des ratios bruts avant tout percentile ranking (anti-anomalies parsing FMP)
    df = _apply_winsorization(df)

    # Ranking intra-secteur
    df["rank_roe"] = compute_percentile_ranks(df, "roe")
    # Cap ROE au percentile 80 pour les tickers avec buyback-inflated ROE (spec §4.1)
    if "roe_capped" in df.columns:
        df.loc[df["roe_capped"].fillna(False), "rank_roe"] = df.loc[df["roe_capped"].fillna(False), "rank_roe"].clip(
            upper=80
        )
    df["rank_margin"] = df.groupby("sector")["margin"].transform(compute_percentile_ranks, column="margin")
    df["rank_debt"] = compute_percentile_ranks(df, "debt_ebitda", ascending=False)
    df["rank_fcf"] = compute_percentile_ranks(df, "fcf_yield")
    df["rank_pe"] = df.groupby("sector")["pe"].transform(compute_percentile_ranks, column="pe", ascending=False)
    df["rank_ev_ebitda"] = df.groupby("sector")["ev_ebitda"].transform(
        compute_percentile_ranks, column="ev_ebitda", ascending=False
    )
    df["rank_peg"] = compute_percentile_ranks(df, "peg", ascending=False)
    df["rank_perf_6m"] = compute_percentile_ranks(df, "perf_6m")
    # v1.1 — rank sur momentum ajusté volatilité (fallback rank_perf_6m si momentum_adj absent)
    if "momentum_adj" in df.columns and df["momentum_adj"].notna().any():
        df["rank_momentum_adj"] = compute_percentile_ranks(df, "momentum_adj")
    else:
        df["rank_momentum_adj"] = df["rank_perf_6m"]
    df["rank_outperf_6m"] = compute_percentile_ranks(df, "outperf_6m")
    df["rank_perf_3m"] = compute_percentile_ranks(df, "perf_3m")
    df["rank_surprise"] = compute_percentile_ranks(df, "surprise_pct")
    df["rank_analyst_revision"] = compute_percentile_ranks(df, "analyst_revision_3m")

    # T024: Intra-sector fallback pour secteurs < min_tickers_intra_sector (Lacune 8)
    min_s = CONFIG["scanner"]["min_tickers_intra_sector"]
    sector_counts = df["sector"].value_counts()
    small_sectors = set(sector_counts[sector_counts < min_s].index)
    df["use_cross_universe_ranking"] = df["sector"].isin(small_sectors)

    if small_sectors:
        cross_rank_pe = compute_percentile_ranks(df, "pe", ascending=False)
        cross_rank_ev = compute_percentile_ranks(df, "ev_ebitda", ascending=False)
        cross_rank_margin = compute_percentile_ranks(df, "margin")
        mask = df["sector"].isin(small_sectors)
        df.loc[mask, "rank_pe"] = cross_rank_pe[mask]
        df.loc[mask, "rank_ev_ebitda"] = cross_rank_ev[mask]
        df.loc[mask, "rank_margin"] = cross_rank_margin[mask]

    # Scores qualité
    qw = CONFIG["scoring"]["quality_subweights"]
    df["score_quality"] = (
        df["rank_roe"].fillna(0) * qw["roe"]
        + df["rank_margin"].fillna(0) * qw["margin"]
        + df["rank_fcf"].fillna(0) * qw["fcf_yield"]
        + df["rank_debt"].fillna(0) * qw["debt_ebitda"]
    )

    v_results = df.apply(compute_valuation_score, axis=1)
    df["score_valuation"] = v_results.apply(lambda x: x[0])
    df["v_ok"] = df["v_ok"] & v_results.apply(lambda x: x[1]).fillna(False)

    # T013: Score momentum per-row avec décroissance earnings (Lacune 6)
    base_mw = CONFIG["scoring"]["momentum_subweights"]
    today = _date.today()

    def _row_momentum_score(row):
        w = compute_momentum_weights(row.get("surprise_date"), base_mw, today)
        return (
            row.get("rank_momentum_adj", row.get("rank_perf_6m", 0)) * w["perf_6m"]
            + (row.get("rank_outperf_6m") or 0) * w["outperf_6m"]
            + (row.get("rank_perf_3m") or 0) * w["perf_3m"]
            + row.get("rank_surprise", 0) * w["surprise_earnings"]
            + (row.get("rank_analyst_revision") or 0) * w.get("analyst_revision", 0)
        )

    df["score_momentum"] = df.apply(_row_momentum_score, axis=1)
    df["score_momentum"] = df.apply(lambda r: apply_momentum_penalties(r["score_momentum"], r), axis=1)

    # Score global
    w = CONFIG["scoring"]["weights"]
    df["score_global"] = df.apply(
        lambda r: (
            (
                r["score_quality"] * w["quality"]
                + r["score_valuation"] * w["valuation"]
                + r["score_momentum"] * w["momentum"]
            )
            if r["v_ok"]
            else (r["score_quality"] * 0.5 + r["score_momentum"] * 0.5)
        ),
        axis=1,
    )
    return df.sort_values("score_global", ascending=False)


def etf_scoring_pipeline(all_data, etfs):
    """Pipeline de scoring simplifié pour les ETFs (Pur Prix)."""
    rows = []
    spy_data = all_data.get("SPY", {}).get("prices")

    for symbol in etfs:
        data = all_data.get(symbol)
        if not data or data["prices"] is None:
            continue

        name = (data.get("info") or {}).get("longName", "")
        if not is_eligible_etf(symbol, name):
            logger.debug(f"ETF exclu (levier/inverse): {symbol} ({name})")
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

        rows.append({"symbol": symbol, "perf_6m": perf_6m, "outperf_spy": outperf_spy})

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["rank_perf_6m"] = compute_percentile_ranks(df, "perf_6m")
    df["rank_outperf_spy"] = compute_percentile_ranks(df, "outperf_spy")

    df["score_global"] = df["rank_perf_6m"].fillna(0) * 0.50 + df["rank_outperf_spy"].fillna(0) * 0.50

    return df.sort_values("score_global", ascending=False)


def compute_inverse_vol_weights(ranked_df: pd.DataFrame, all_data: dict) -> pd.DataFrame:
    """
    v1.1 — Pondération inverse de la volatilité pour les signaux Top 10.
    Calcule suggested_weight_pct = (1/σ_i) / Σ(1/σ_j) × 100.
    σ = écart-type des rendements journaliers sur 63j.
    Tickers sans historique suffisant reçoivent le poids moyen.
    """
    symbols = list(ranked_df["symbol"])
    inv_vols: dict[str, float] = {}

    for sym in symbols:
        prices = all_data.get(sym, {}).get("prices")
        if prices is not None and len(prices) >= 60:
            daily_ret = prices["Close"].iloc[-60:].pct_change().dropna()
            sigma = float(daily_ret.std())
            if sigma > 1e-9:
                inv_vols[sym] = 1.0 / sigma

    if not inv_vols:
        ranked_df["suggested_weight_pct"] = 100.0 / len(symbols) if symbols else None
        return ranked_df

    mean_inv_vol = sum(inv_vols.values()) / len(inv_vols)
    total_inv_vol = sum(inv_vols.get(s, mean_inv_vol) for s in symbols)

    weights = {s: (inv_vols.get(s, mean_inv_vol) / total_inv_vol) * 100.0 for s in symbols}
    ranked_df = ranked_df.copy()
    ranked_df["suggested_weight_pct"] = ranked_df["symbol"].map(weights)
    return ranked_df
