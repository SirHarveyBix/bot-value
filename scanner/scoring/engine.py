import numpy as np
import pandas as pd

from scanner.config import CONFIG, logger
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

def momentum_screening_pipeline(price_data, symbols):
    """Pipeline initial pour filtrer les tickers par momentum pur."""
    rows = []
    # Fetch SPY for relative performance benchmark
    spy_prices = price_data["SPY"] if "SPY" in price_data.columns.levels[0] else None

    for symbol in symbols:
        # Extraire les prix du batch
        prices = None
        if isinstance(price_data.columns, pd.MultiIndex):
            if symbol in price_data.columns.levels[0]:
                prices = price_data[symbol]
        
        if prices is None or len(prices) < 126:
            continue

        # Calcul momentum simplifié (Section 4.1)
        m_metrics = calculate_momentum_metrics(prices, {}, None) # Pas de secteur à ce stade
        
        rows.append({
            "symbol": symbol,
            "perf_6m": m_metrics.get("perf_6m", 0),
            "perf_3m": m_metrics.get("perf_3m", 0)
        })
    
    if not rows:
        return pd.DataFrame()
    
    df = pd.DataFrame(rows)
    # Score momentum rapide : 60% Perf 6M + 40% Perf 3M
    df["m_score"] = df["perf_6m"] * 0.6 + df["perf_3m"] * 0.4
    return df.sort_values("m_score", ascending=False)

def compute_valuation_score(row):
    vw = CONFIG["scoring"]["valuation_subweights"]
    
    # Compter les NaNs dans le pilier valorisation
    # (pe est garanti présent si v_ok=True, mais vérifions quand même)
    v_ranks = [row["rank_pe"], row["rank_ev_ebitda"], row["rank_peg"]]
    nan_count = sum(1 for r in v_ranks if pd.isna(r))
    
    if nan_count >= 2:
        # Si plus de 2 critères sur 3 sont NaN, on invalide le pilier
        return None, False

    # Redistribution du poids si PEG est manquant (Section 4.1)
    if pd.isna(row["rank_peg"]):
        # P/E Forward -> 56%, EV/EBITDA -> 44%
        v_score = (row["rank_pe"] or 0) * 0.56 + (row["rank_ev_ebitda"] or 0) * 0.44
    else:
        v_score = (
            (row["rank_pe"] or 0) * vw["pe_forward"] +
            (row["rank_ev_ebitda"] or 0) * vw["ev_ebitda"] +
            (row["rank_peg"] or 0) * vw["peg"]
        )
    
    # Pénalité P/E TTM (Section 4.1)
    if pd.notna(row.get("pe_flag")):
        v_score -= 5
        
    return max(0, v_score), True


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
        v_excluded, v_ok, v_reason = apply_valuation_gates(v_metrics)

        if not q_ok:
            logger.debug(f"Exclusion {symbol} (Qualité): {q_reason}")
            continue
        
        if v_excluded:
            logger.debug(f"Exclusion {symbol} (Valorisation): {v_reason}")
            continue

        row = {
            "symbol": symbol,
            "name": info.get("longName", symbol),
            "sector": sector,
            "mcap_b": info.get("marketCap", 0) / 1e9 if info.get("marketCap") else 0,
            **q_metrics,
            **v_metrics,
            **m_metrics,
            "v_ok": v_ok,
            "pe_flag": v_metrics.get("pe_flag")
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
    df["rank_sales_growth"] = compute_percentile_ranks(df, "sales_growth")

    # Scores
    qw = CONFIG["scoring"]["quality_subweights"]
    df["score_quality"] = (df["rank_roe"].fillna(0) * qw["roe"] + df["rank_margin"].fillna(0) * qw["margin"] +
                          df["rank_fcf"].fillna(0) * qw["fcf_yield"] + df["rank_debt"].fillna(0) * qw["debt_ebitda"])

    # Appliquer le calcul du score de valorisation
    v_results = df.apply(compute_valuation_score, axis=1)
    df["score_valuation"] = v_results.apply(lambda x: x[0])
    # Mettre à jour v_ok si le score a été invalidé par manque de données
    df["v_ok"] = df["v_ok"] & v_results.apply(lambda x: x[1])

    mw = CONFIG["scoring"]["momentum_subweights"]
    df["score_momentum"] = (
        df["rank_perf_6m"].fillna(0) * mw["perf_6m"] +
        df["rank_outperf_6m"].fillna(0) * mw["outperf_6m"] +
        df["rank_perf_3m"].fillna(0) * mw["perf_3m"] +
        df["rank_sales_growth"].fillna(0) * mw["sales_growth"]
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
    """Pipeline de scoring simplifié pour les ETFs (Pur Prix)."""
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

        rows.append({
            "symbol": symbol,
            "perf_6m": perf_6m,
            "outperf_spy": outperf_spy
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["rank_perf_6m"] = compute_percentile_ranks(df, "perf_6m")
    df["rank_outperf_spy"] = compute_percentile_ranks(df, "outperf_spy")

    # Nouveau scoring 50/50 validé
    df["score_global"] = (df["rank_perf_6m"].fillna(0) * 0.50 +
                         df["rank_outperf_spy"].fillna(0) * 0.50)

    return df.sort_values("score_global", ascending=False)
