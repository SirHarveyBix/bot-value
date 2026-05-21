from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import datetime

import aiosqlite
import yfinance as yf

from scanner.config import CONFIG, logger

DB_PATH = "data/signals/scanner_history.db"

_NEW_COLS = [
    "ALTER TABLE signals ADD COLUMN first_seen_date TEXT",
    "ALTER TABLE signals ADD COLUMN price_at_signal REAL",
    "ALTER TABLE signals ADD COLUMN price_30d_later REAL",
    "ALTER TABLE signals ADD COLUMN return_30d REAL",
    "ALTER TABLE signals ADD COLUMN price_90d_later REAL",
    "ALTER TABLE signals ADD COLUMN return_90d REAL",
    "ALTER TABLE signals ADD COLUMN flags TEXT",
    "ALTER TABLE signals ADD COLUMN suggested_weight_pct REAL",
    "ALTER TABLE signals ADD COLUMN outperf_6m REAL",
]


def init_db():
    """Initialise la base de données SQLite."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date TEXT UNIQUE,
            market_regime TEXT,
            spy_price REAL,
            spy_ema200 REAL,
            vix REAL,
            universe_size INTEGER,
            eligible_count INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER,
            symbol TEXT NOT NULL,
            name TEXT,
            type TEXT,
            rank INTEGER,
            score_global REAL,
            score_quality REAL,
            score_valuation REAL,
            score_momentum REAL,
            pe REAL,
            roe REAL,
            margin REAL,
            perf_6m REAL,
            FOREIGN KEY (scan_id) REFERENCES scans(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS api_cache (
            key TEXT NOT NULL,
            category TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            data TEXT NOT NULL,
            PRIMARY KEY (category, key)
        )
    """)

    # Migration schema — colonnes V1
    for stmt in _NEW_COLS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass

    # Table scanned_universe — anti survivorship bias (backtesting out-of-sample)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scanned_universe (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date       TEXT NOT NULL,
            ticker          TEXT NOT NULL,
            score_momentum  REAL,
            rank_chalutier  INTEGER,
            in_shortlist    INTEGER DEFAULT 0,
            in_top10        INTEGER DEFAULT 0,
            market_cap      REAL,
            sector          TEXT,
            price_at_scan   REAL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_scanned_universe_date ON scanned_universe(scan_date)")

    conn.commit()
    conn.close()
    logger.info(f"Base de données SQLite initialisée à {DB_PATH}")


def get_first_seen_date(conn, symbol: str) -> str | None:
    """Retourne la première date où le ticker est apparu en signal (Lacune 11)."""
    row = conn.execute(
        "SELECT first_seen_date FROM signals WHERE symbol = ? AND first_seen_date IS NOT NULL ORDER BY id DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    return row[0] if row else None


async def save_scan_entry(market_data: dict):
    """Enregistre un scan sans signaux (cas panic/abort)."""
    init_db()
    scan_date = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        try:
            await db.execute(
                "INSERT INTO scans (scan_date, market_regime, spy_price, spy_ema200, vix, universe_size, eligible_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    scan_date,
                    market_data.get("regime", "unknown"),
                    market_data.get("spy_price"),
                    market_data.get("spy_ema200"),
                    market_data.get("vix"),
                    0,
                    0,
                ),
            )
        except sqlite3.IntegrityError:
            await db.execute(
                "UPDATE scans SET market_regime = ?, spy_price = ?, spy_ema200 = ?, vix = ? WHERE scan_date = ?",
                (
                    market_data.get("regime"),
                    market_data.get("spy_price"),
                    market_data.get("spy_ema200"),
                    market_data.get("vix"),
                    scan_date,
                ),
            )
        await db.commit()


def save_signals_to_db(top_stocks, top_etfs, all_data, universe_size, market_data=None):
    """Sauvegarde les signaux dans SQLite."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    scan_date = datetime.now().strftime("%Y-%m-%d")
    today_str = scan_date

    market_regime = market_data.get("regime", "unknown") if market_data else "unknown"
    spy_price = market_data.get("spy_price") if market_data else None
    spy_ema200 = market_data.get("spy_ema200") if market_data else None
    current_vix = market_data.get("vix") if market_data else None

    try:
        cursor.execute(
            "INSERT INTO scans (scan_date, market_regime, spy_price, spy_ema200, vix, universe_size, eligible_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (scan_date, market_regime, spy_price, spy_ema200, current_vix, universe_size, len(top_stocks)),
        )
        scan_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        cursor.execute("SELECT id FROM scans WHERE scan_date = ?", (scan_date,))
        scan_id = cursor.fetchone()[0]
        cursor.execute(
            "UPDATE scans SET market_regime = ?, spy_price = ?, spy_ema200 = ?, vix = ?, universe_size = ?, eligible_count = ? WHERE id = ?",
            (market_regime, spy_price, spy_ema200, current_vix, universe_size, len(top_stocks), scan_id),
        )
        cursor.execute("DELETE FROM signals WHERE scan_id = ?", (scan_id,))

    # T026: Stocks avec first_seen_date conservée (Lacune 11)
    for i, (_, row) in enumerate(top_stocks.iterrows()):
        symbol = row["symbol"]
        first_seen = get_first_seen_date(conn, symbol) or today_str

        price_at_signal = None
        ticker_prices = all_data.get(symbol, {}).get("prices")
        if ticker_prices is not None and not ticker_prices.empty:
            try:
                price_at_signal = float(ticker_prices["Close"].iloc[-1])
            except Exception:
                pass

        cursor.execute(
            "INSERT INTO signals (scan_id, symbol, name, type, rank, score_global, score_quality, score_valuation, "
            "score_momentum, pe, roe, margin, perf_6m, outperf_6m, first_seen_date, price_at_signal) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                scan_id,
                symbol,
                row.get("name", ""),
                "stock",
                i + 1,
                row["score_global"],
                row["score_quality"],
                row.get("score_valuation"),
                row["score_momentum"],
                row.get("pe"),
                row.get("roe"),
                row.get("margin"),
                row.get("perf_6m"),
                row.get("outperf_6m"),
                first_seen,
                price_at_signal,
            ),
        )

    for i, (_, row) in enumerate(top_etfs.iterrows()):
        symbol = row["symbol"]
        first_seen = get_first_seen_date(conn, symbol) or today_str

        price_at_signal = None
        etf_prices = all_data.get(symbol, {}).get("prices")
        if etf_prices is not None and not etf_prices.empty:
            try:
                price_at_signal = float(etf_prices["Close"].iloc[-1])
            except Exception:
                pass

        cursor.execute(
            "INSERT INTO signals (scan_id, symbol, name, type, rank, score_global, score_quality, score_valuation, "
            "score_momentum, pe, roe, margin, perf_6m, outperf_6m, first_seen_date, price_at_signal) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                scan_id,
                symbol,
                row.get("name", ""),
                "etf",
                i + 1,
                row["score_global"],
                0,
                0,
                0,
                None,
                None,
                None,
                row.get("perf_6m"),
                row.get("outperf_6m"),
                first_seen,
                price_at_signal,
            ),
        )

    conn.commit()
    conn.close()
    logger.info(f"Signaux sauvegardés dans SQLite (Scan ID: {scan_id})")


def save_signals(top_stocks, top_etfs, all_data, universe_size, market_data=None):
    """Point d'entrée principal sauvegarde signaux SQLite."""
    save_signals_to_db(top_stocks, top_etfs, all_data, universe_size, market_data)


async def update_signal_returns():
    """
    Job de fond 18h00 ET : met à jour price_30d_later/return_30d et price_90d_later/return_90d.
    Utilise yfinance uniquement — aucun appel FMP.
    """

    init_db()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")

        async with db.execute(
            "SELECT id, symbol, price_at_signal FROM signals "
            "WHERE price_30d_later IS NULL AND price_at_signal IS NOT NULL "
            "AND first_seen_date <= date('now', '-30 days')"
        ) as cur:
            rows_30d = await cur.fetchall()

        async with db.execute(
            "SELECT id, symbol, price_at_signal FROM signals "
            "WHERE price_90d_later IS NULL AND price_at_signal IS NOT NULL "
            "AND first_seen_date <= date('now', '-90 days')"
        ) as cur:
            rows_90d = await cur.fetchall()

        chunk_size = CONFIG["scanner"].get("yfinance_chunk_size", 100)
        chunk_delay = CONFIG["scanner"].get("yfinance_chunk_delay_s", 2.0)

        async def _fetch_prices_batch(rows: list) -> dict[str, float]:
            """Fetch current prices for a list of (id, symbol, price_at_signal) rows via chunked yf.download."""
            import pandas as pd

            prices: dict[str, float] = {}
            symbols = [r[1] for r in rows]
            chunks = [symbols[i : i + chunk_size] for i in range(0, len(symbols), chunk_size)]
            for idx, chunk in enumerate(chunks):
                try:
                    data = await asyncio.wait_for(
                        asyncio.to_thread(
                            yf.download,
                            tickers=" ".join(chunk),
                            period="2d",
                            group_by="ticker",
                            auto_adjust=True,
                            progress=False,
                            threads=False,
                        ),
                        timeout=60.0,
                    )
                    if data.empty:
                        continue
                    for sym in chunk:
                        try:
                            if isinstance(data.columns, pd.MultiIndex):
                                close = data[sym]["Close"].dropna()
                            else:
                                close = data["Close"].dropna()
                            if not close.empty:
                                prices[sym] = float(close.iloc[-1])
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning(f"update_signal_returns batch chunk {idx + 1}: {e}")
                if idx < len(chunks) - 1:
                    await asyncio.sleep(chunk_delay)
            return prices

        updated = 0
        prices_30d = await _fetch_prices_batch(rows_30d)
        for row_id, symbol, price_at_signal in rows_30d:
            price_now = prices_30d.get(symbol)
            if price_now is None:
                # Sentinel -1.0 : ticker délisté/introuvable — ne plus retenter
                await db.execute("UPDATE signals SET price_30d_later = -1.0 WHERE id = ?", (row_id,))
                updated += 1
                continue
            return_30d = (price_now - price_at_signal) / price_at_signal
            await db.execute(
                "UPDATE signals SET price_30d_later = ?, return_30d = ? WHERE id = ?", (price_now, return_30d, row_id)
            )
            updated += 1

        prices_90d = await _fetch_prices_batch(rows_90d)
        for row_id, symbol, price_at_signal in rows_90d:
            price_now = prices_90d.get(symbol)
            if price_now is None:
                # Sentinel -1.0 : ticker délisté/introuvable — ne plus retenter
                await db.execute("UPDATE signals SET price_90d_later = -1.0 WHERE id = ?", (row_id,))
                updated += 1
                continue
            return_90d = (price_now - price_at_signal) / price_at_signal
            await db.execute(
                "UPDATE signals SET price_90d_later = ?, return_90d = ? WHERE id = ?", (price_now, return_90d, row_id)
            )
            updated += 1

        await db.commit()
    logger.info(f"Retours 30j/90j mis à jour ({updated} mises à jour sur {len(rows_30d) + len(rows_90d)} signaux).")


async def save_scanned_universe(eligible_df, shortlist_symbols: list[str], top10_symbols: list[str], scan_date: str):
    """
    Stocke TOUS les tickers post-éligibilité Chalutier (pré-shortlist) dans scanned_universe.
    Anti survivorship bias : permet le backtesting out-of-sample en comparant Top 10 vs univers entier.
    Appelé dans main.py AVANT shortlisting, avec les champs momentum + flags in_shortlist/in_top10.
    """
    init_db()
    if eligible_df is None or eligible_df.empty:
        return

    shortlist_set = set(shortlist_symbols)
    top10_set = set(top10_symbols)

    rows = []
    for rank, row in enumerate(eligible_df.itertuples(), start=1):
        symbol = getattr(row, "symbol", None)
        if not symbol:
            continue
        rows.append(
            (
                scan_date,
                symbol,
                getattr(row, "m_score", None),
                rank,
                1 if symbol in shortlist_set else 0,
                1 if symbol in top10_set else 0,
                getattr(row, "market_cap", None),
                getattr(row, "sector", None),
                getattr(row, "price_at_scan", None),
            )
        )

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.executemany(
            "INSERT INTO scanned_universe "
            "(scan_date, ticker, score_momentum, rank_chalutier, in_shortlist, in_top10, market_cap, sector, price_at_scan) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        await db.commit()
    logger.info(f"scanned_universe : {len(rows)} tickers enregistrés pour {scan_date}")


def update_portfolio_flags(scan_date: str, portfolio: dict, exits_today: list) -> None:
    """Persiste les flags ACHAT/MATURATION/HOLD et insère les EXIT dans signals pour scan_date."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM scans WHERE scan_date = ?", (scan_date,))
        row = cursor.fetchone()
        if row:
            scan_id = row[0]
            for symbol, port_item in portfolio.items():
                cursor.execute(
                    "UPDATE signals SET flags = ? WHERE scan_id = ? AND symbol = ?",
                    (port_item["status"], scan_id, symbol),
                )
            for ex_item in exits_today:
                cursor.execute(
                    "INSERT INTO signals (scan_id, symbol, name, type, rank, score_global, flags) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (scan_id, ex_item["symbol"], ex_item["name"], "stock", ex_item["rank"], ex_item["score"], "EXIT"),
                )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"update_portfolio_flags: {e}")


def get_first_seen_dates_batch(symbols: list[str], today_str: str) -> dict[str, str]:
    """Retourne {symbol: first_seen_date} pour une liste de symboles via une seule requête IN."""
    result: dict[str, str] = {s: today_str for s in symbols}
    if not symbols:
        return result
    try:
        conn = sqlite3.connect(DB_PATH)
        placeholders = ",".join("?" * len(symbols))
        rows = conn.execute(
            f"SELECT symbol, first_seen_date FROM signals s "
            f"WHERE symbol IN ({placeholders}) AND first_seen_date IS NOT NULL "
            f"AND id = (SELECT MAX(id) FROM signals WHERE symbol = s.symbol AND first_seen_date IS NOT NULL)",
            symbols,
        ).fetchall()
        conn.close()
        for sym, fsd in rows:
            if fsd:
                result[sym] = fsd
    except Exception as e:
        logger.warning(f"get_first_seen_dates_batch: {e}")
    return result


def reconstruct_portfolio_and_maturation(conn):
    """
    Simule chronologiquement l'histoire des scans SQLite pour tracer le portefeuille :
      - Un ticker entre dans le portefeuille s'il est au Top 10 (rank <= 10).
      - Durant ses maturation_days (3 jours) de détention consécutifs, il ne peut pas être vendu (⏳ MATURATION).
      - À partir de days_held >= maturation_days, il passe en mode normal (HOLD).
      - Il sort s'il a dépassé la maturation et remplit un critère de sortie :
        rank > exit_rank_threshold (15) ou score_global < exit_score_threshold (70) (ou s'il est absent du scan).

    Retourne :
      - current_portfolio : dict {symbol: {
            "symbol": str,
            "days_held": int,
            "status": str,  # 'ACHAT', 'MATURATION', 'HOLD'
            "rank": int,
            "score": float,
            "name": str
        }}
      - exits_today : list de dicts représentant les positions sorties lors du dernier scan.
    """
    exit_rank_threshold = CONFIG["scanner"].get("exit_rank_threshold", 15)
    exit_score_threshold = CONFIG["scanner"].get("exit_score_threshold", 70.0)
    maturation_days = CONFIG["scanner"].get("maturation_days", 3)

    scans_rows = conn.execute("SELECT id, scan_date FROM scans ORDER BY scan_date ASC").fetchall()

    portfolio = {}  # symbol -> {"days_held": int, "last_rank": int, "last_score": float, "name": str}
    exits_today = []

    for idx, (scan_id, _scan_date) in enumerate(scans_rows):
        is_last_scan = idx == len(scans_rows) - 1
        if is_last_scan:
            exits_today = []

        # Récupère tous les signaux de type stock pour ce scan
        signals_rows = conn.execute(
            "SELECT symbol, rank, score_global, name FROM signals WHERE scan_id = ? AND type = 'stock'", (scan_id,)
        ).fetchall()
        scan_signals = {row[0]: {"rank": row[1], "score": row[2], "name": row[3]} for row in signals_rows}

        # 1. Met à jour et incrémente days_held des tickers déjà en portefeuille
        to_check_exit = list(portfolio.keys())
        for symbol in to_check_exit:
            portfolio[symbol]["days_held"] += 1
            if symbol in scan_signals:
                portfolio[symbol]["last_rank"] = scan_signals[symbol]["rank"]
                portfolio[symbol]["last_score"] = scan_signals[symbol]["score"]
                portfolio[symbol]["name"] = scan_signals[symbol]["name"]
            else:
                portfolio[symbol]["last_rank"] = 999
                portfolio[symbol]["last_score"] = 0.0

            # 2. Vérifie la sortie (exit) : seulement après la période de maturation (strictement supérieur à maturation_days)
            if portfolio[symbol]["days_held"] > maturation_days:
                rank = portfolio[symbol]["last_rank"]
                score = portfolio[symbol]["last_score"]
                if rank > exit_rank_threshold or score < exit_score_threshold:
                    ex_data = {
                        "symbol": symbol,
                        "name": portfolio[symbol]["name"],
                        "days_held": portfolio[symbol]["days_held"],
                        "rank": rank,
                        "score": score,
                    }
                    if is_last_scan:
                        exits_today.append(ex_data)
                    del portfolio[symbol]

        # 3. Traite les nouveaux achats : Top 10 du scan actuel
        for symbol, sig in scan_signals.items():
            if sig["rank"] <= 10:
                if symbol not in portfolio:
                    portfolio[symbol] = {
                        "days_held": 1,
                        "last_rank": sig["rank"],
                        "last_score": sig["score"],
                        "name": sig["name"],
                    }

    # Construit le résultat final pour le portefeuille actuel
    current_portfolio = {}
    for symbol, data in portfolio.items():
        days = data["days_held"]
        if days == 1:
            status = "ACHAT"
        elif days < maturation_days:
            status = "MATURATION"
        else:
            status = "HOLD"

        current_portfolio[symbol] = {
            "symbol": symbol,
            "days_held": days,
            "status": status,
            "rank": data["last_rank"],
            "score": data["last_score"],
            "name": data["name"],
        }

    return current_portfolio, exits_today


JSON_PATH = "data/signals/signals_latest.json"


def export_signals_json(top_stocks, top_etfs, universe_size: int, market_data: dict | None = None) -> None:
    """Écrit data/signals/signals_latest.json pour le dashboard web."""
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)

    stocks_list = []
    for _, row in top_stocks.iterrows():
        stocks_list.append(
            {
                "symbol": row.get("symbol", ""),
                "name": row.get("name", ""),
                "sector": row.get("sector", ""),
                "score_global": float(row.get("score_global", 0)),
                "score_quality": float(row.get("score_quality", 0)),
                "score_valuation": float(row.get("score_valuation") or 0),
                "score_momentum": float(row.get("score_momentum", 0)),
                "pe": float(row["pe"]) if row.get("pe") is not None else None,
                "roe": float(row["roe"]) if row.get("roe") is not None else None,
                "perf_6m": float(row["perf_6m"]) if row.get("perf_6m") is not None else None,
                "mcap_b": float(row.get("mcap_b", 0)),
                "flags": row.get("quality_flags") or [],
                "first_seen_date": row.get("first_seen_date"),
                "suggested_weight_pct": float(row["suggested_weight_pct"])
                if row.get("suggested_weight_pct") is not None
                else None,
            }
        )

    etfs_list = []
    for _, row in top_etfs.iterrows():
        etfs_list.append(
            {
                "symbol": row.get("symbol", ""),
                "score_global": float(row.get("score_global", 0)),
                "perf_6m": float(row["perf_6m"]) if row.get("perf_6m") is not None else None,
                "vol_trend": float(row["outperf_spy"]) if row.get("outperf_spy") is not None else None,
            }
        )

    payload = {
        "scan_timestamp": datetime.now().isoformat(),
        "universe_size": universe_size,
        "market_regime": (market_data or {}).get("regime"),
        "vix": (market_data or {}).get("vix"),
        "spy_price": (market_data or {}).get("spy_price"),
        "spy_ema200": (market_data or {}).get("spy_ema200"),
        "top_stocks": stocks_list,
        "top_etfs": etfs_list,
    }

    with open(JSON_PATH, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    logger.info(f"signals_latest.json exporté ({len(stocks_list)} stocks, {len(etfs_list)} ETFs)")
