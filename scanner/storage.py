from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from scanner.config import logger

DB_PATH = "data/signals/scanner_history.db"

_NEW_COLS = [
    "ALTER TABLE signals ADD COLUMN first_seen_date TEXT",
    "ALTER TABLE signals ADD COLUMN price_at_signal REAL",
    "ALTER TABLE signals ADD COLUMN price_30d_later REAL",
    "ALTER TABLE signals ADD COLUMN return_30d REAL",
    "ALTER TABLE signals ADD COLUMN price_90d_later REAL",
    "ALTER TABLE signals ADD COLUMN return_90d REAL",
    "ALTER TABLE signals ADD COLUMN flags TEXT",
]


def init_db():
    """Initialise la base de données SQLite."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    cursor = conn.cursor()

    cursor.execute('''
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
    ''')

    cursor.execute('''
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
    ''')

    # T025: Migration schema — colonnes V1 (Lacune 11)
    for stmt in _NEW_COLS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()
    logger.info(f"Base de données SQLite initialisée à {DB_PATH}")


def get_first_seen_date(conn, symbol: str) -> str | None:
    """Retourne la première date où le ticker est apparu en signal (Lacune 11)."""
    row = conn.execute(
        "SELECT first_seen_date FROM signals WHERE symbol = ? "
        "AND first_seen_date IS NOT NULL ORDER BY id DESC LIMIT 1",
        (symbol,)
    ).fetchone()
    return row[0] if row else None


def save_scan_entry(market_data: dict):
    """Enregistre un scan sans signaux (cas panic/abort)."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    scan_date = datetime.now().strftime("%Y-%m-%d")
    try:
        cursor.execute(
            "INSERT INTO scans (scan_date, market_regime, spy_price, spy_ema200, vix, universe_size, eligible_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                scan_date,
                market_data.get("regime", "unknown"),
                market_data.get("spy_price"),
                market_data.get("spy_ema200"),
                market_data.get("vix"),
                0, 0
            )
        )
    except sqlite3.IntegrityError:
        cursor.execute(
            "UPDATE scans SET market_regime = ?, spy_price = ?, spy_ema200 = ?, vix = ? WHERE scan_date = ?",
            (market_data.get("regime"), market_data.get("spy_price"), market_data.get("spy_ema200"), market_data.get("vix"), scan_date)
        )
    conn.commit()
    conn.close()


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
            (scan_date, market_regime, spy_price, spy_ema200, current_vix, universe_size, len(top_stocks))
        )
        scan_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        cursor.execute("SELECT id FROM scans WHERE scan_date = ?", (scan_date,))
        scan_id = cursor.fetchone()[0]
        cursor.execute(
            "UPDATE scans SET market_regime = ?, spy_price = ?, spy_ema200 = ?, vix = ?, universe_size = ?, eligible_count = ? WHERE id = ?",
            (market_regime, spy_price, spy_ema200, current_vix, universe_size, len(top_stocks), scan_id)
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
            "score_momentum, pe, roe, margin, perf_6m, first_seen_date, price_at_signal) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                scan_id, symbol, row.get("name", ""), "stock", i + 1,
                row["score_global"], row["score_quality"], row.get("score_valuation"), row["score_momentum"],
                row.get("pe"), row.get("roe"), row.get("margin"), row.get("perf_6m"),
                first_seen, price_at_signal
            )
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
            "score_momentum, pe, roe, margin, perf_6m, first_seen_date, price_at_signal) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                scan_id, symbol, row.get("name", ""), "etf", i + 1,
                row["score_global"], 0, 0, 0,
                None, None, None, row.get("perf_6m"),
                first_seen, price_at_signal
            )
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
    import yfinance as yf

    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")

    rows_30d = conn.execute(
        "SELECT id, symbol, price_at_signal FROM signals "
        "WHERE price_30d_later IS NULL AND price_at_signal IS NOT NULL "
        "AND first_seen_date <= date('now', '-30 days')"
    ).fetchall()

    rows_90d = conn.execute(
        "SELECT id, symbol, price_at_signal FROM signals "
        "WHERE price_90d_later IS NULL AND price_at_signal IS NOT NULL "
        "AND first_seen_date <= date('now', '-90 days')"
    ).fetchall()

    updated = 0
    for row_id, symbol, price_at_signal in rows_30d:
        try:
            ticker = yf.Ticker(symbol)
            hist = await asyncio.to_thread(ticker.history, period="1d")
            if hist.empty:
                continue
            price_now = float(hist["Close"].iloc[-1])
            return_30d = (price_now - price_at_signal) / price_at_signal
            conn.execute(
                "UPDATE signals SET price_30d_later = ?, return_30d = ? WHERE id = ?",
                (price_now, return_30d, row_id)
            )
            updated += 1
        except Exception as e:
            logger.warning(f"update_signal_returns 30d: erreur pour {symbol}: {e}")

    for row_id, symbol, price_at_signal in rows_90d:
        try:
            ticker = yf.Ticker(symbol)
            hist = await asyncio.to_thread(ticker.history, period="1d")
            if hist.empty:
                continue
            price_now = float(hist["Close"].iloc[-1])
            return_90d = (price_now - price_at_signal) / price_at_signal
            conn.execute(
                "UPDATE signals SET price_90d_later = ?, return_90d = ? WHERE id = ?",
                (price_now, return_90d, row_id)
            )
            updated += 1
        except Exception as e:
            logger.warning(f"update_signal_returns 90d: erreur pour {symbol}: {e}")

    conn.commit()
    conn.close()
    logger.info(f"Retours 30j/90j mis à jour ({updated} mises à jour sur {len(rows_30d)+len(rows_90d)} signaux).")
