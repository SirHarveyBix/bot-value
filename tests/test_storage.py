"""Tests unitaires — scanner/storage.py (signals, retours 30j/90j, portfolio)."""

import sqlite3
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

# ── update_signal_returns : filtre scan_date via JOIN ────────────────────────


@pytest.mark.asyncio
async def test_update_signal_returns_filters_by_scan_date_not_first_seen(tmp_path):
    """
    BUG-4 : le filtre doit être sur scans.scan_date (JOIN), pas sur first_seen_date.

    Scénario :
    - Signal AAPL : scan_date = aujourd'hui, first_seen_date = J-40 (réapparu)
      → return_30d ne doit PAS être calculé (scan trop récent)
    - Signal MSFT : scan_date = J-35, first_seen_date = J-35
      → return_30d DOIT être calculé
    """
    import aiosqlite

    db_path = str(tmp_path / "test.db")
    with patch("scanner.storage.DB_PATH", db_path):
        from scanner.storage import init_db, update_signal_returns

        init_db()

        today = date.today().isoformat()
        old_date = (date.today() - timedelta(days=35)).isoformat()

        async with aiosqlite.connect(db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute(
                "INSERT INTO scans (scan_date, market_regime, eligible_count) VALUES (?, 'normal', 10)",
                (today,),
            )
            scan_a_id = (await (await db.execute("SELECT last_insert_rowid()")).fetchone())[0]
            await db.execute(
                "INSERT INTO scans (scan_date, market_regime, eligible_count) VALUES (?, 'normal', 10)",
                (old_date,),
            )
            scan_b_id = (await (await db.execute("SELECT last_insert_rowid()")).fetchone())[0]
            await db.execute(
                "INSERT INTO signals (scan_id, symbol, type, rank, score_global, price_at_signal, first_seen_date) "
                "VALUES (?, 'AAPL', 'stock', 1, 80.0, 150.0, ?)",
                (scan_a_id, old_date),
            )
            await db.execute(
                "INSERT INTO signals (scan_id, symbol, type, rank, score_global, price_at_signal, first_seen_date) "
                "VALUES (?, 'MSFT', 'stock', 2, 75.0, 200.0, ?)",
                (scan_b_id, old_date),
            )
            await db.commit()

        mock_df = pd.DataFrame({"Close": [210.0]}, index=[pd.Timestamp("2026-06-04")])
        mock_df.columns = pd.MultiIndex.from_tuples([("MSFT", "Close")])

        with patch("scanner.storage.yf.download", return_value=mock_df):
            await update_signal_returns()

        async with aiosqlite.connect(db_path) as db:
            row_a = await (
                await db.execute("SELECT price_30d_later, return_30d FROM signals WHERE symbol='AAPL'")
            ).fetchone()
            row_b = await (
                await db.execute("SELECT price_30d_later, return_30d FROM signals WHERE symbol='MSFT'")
            ).fetchone()

    assert row_a[0] is None, "Scan aujourd'hui : return_30d ne doit pas être calculé"
    assert row_b[0] is not None, "Scan J-35 : return_30d doit être calculé"
    assert abs(row_b[1] - (210.0 - 200.0) / 200.0) < 1e-6


# ── get_first_seen_dates_batch : MIN(first_seen_date) ────────────────────────


def test_get_first_seen_dates_batch_returns_earliest_date(tmp_path):
    """
    BUG-5 : la requête utilise MIN(first_seen_date) au lieu de MAX(id).
    Même si un enregistrement récent a une date corrompue plus tardive,
    MIN retourne la vraie première apparition.
    """
    db_path = str(tmp_path / "test.db")
    with patch("scanner.storage.DB_PATH", db_path):
        from scanner.storage import get_first_seen_dates_batch, init_db

        init_db()

        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO scans (scan_date, market_regime, eligible_count) VALUES ('2026-01-01', 'normal', 10)")
        s1 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO scans (scan_date, market_regime, eligible_count) VALUES ('2026-03-01', 'normal', 10)")
        s2 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        conn.execute(
            "INSERT INTO signals (scan_id, symbol, type, rank, score_global, first_seen_date) "
            "VALUES (?, 'AAPL', 'stock', 1, 80.0, '2026-01-01')",
            (s1,),
        )
        conn.execute(
            "INSERT INTO signals (scan_id, symbol, type, rank, score_global, first_seen_date) "
            "VALUES (?, 'AAPL', 'stock', 1, 85.0, '2026-01-01')",
            (s2,),
        )
        # Enregistrement corrompu avec date tardive (id plus élevé)
        conn.execute(
            "INSERT INTO signals (scan_id, symbol, type, rank, score_global, first_seen_date) "
            "VALUES (?, 'AAPL', 'stock', 1, 90.0, '2026-03-01')",
            (s2,),
        )
        conn.commit()
        conn.close()

        result = get_first_seen_dates_batch(["AAPL"], "2026-06-01")

    assert result["AAPL"] == "2026-01-01", f"Attendu 2026-01-01, obtenu {result['AAPL']}"


def test_get_first_seen_dates_batch_fallback_to_today(tmp_path):
    """Symbole absent de la DB → fallback sur today_str fourni."""
    db_path = str(tmp_path / "test.db")
    with patch("scanner.storage.DB_PATH", db_path):
        from scanner.storage import get_first_seen_dates_batch, init_db

        init_db()
        result = get_first_seen_dates_batch(["UNKNOWN"], "2026-06-04")

    assert result["UNKNOWN"] == "2026-06-04"


def test_get_first_seen_dates_batch_empty_list(tmp_path):
    """Liste vide → dict vide."""
    db_path = str(tmp_path / "test.db")
    with patch("scanner.storage.DB_PATH", db_path):
        from scanner.storage import get_first_seen_dates_batch, init_db

        init_db()
        result = get_first_seen_dates_batch([], "2026-06-04")

    assert result == {}


# ── export_signals_json : copie dans web/ ────────────────────────────────────


def test_export_signals_json_copies_to_web(tmp_path):
    """export_signals_json écrit dans data/signals/ ET dans web/."""

    data_dir = tmp_path / "data" / "signals"
    data_dir.mkdir(parents=True)

    with (
        patch("scanner.storage.JSON_PATH", str(data_dir / "signals_latest.json")),
        patch("scanner.storage.os.makedirs"),
    ):
        # Patch open pour capturer les deux écritures
        written_paths = []
        original_open = open

        def mock_open(path, mode="r", **kwargs):
            if mode == "w" and "signals_latest" in str(path):
                written_paths.append(str(path))
            return original_open(path, mode, **kwargs)

        from scanner.storage import export_signals_json

        with patch("builtins.open", side_effect=mock_open):
            export_signals_json(pd.DataFrame(), pd.DataFrame(), 500)

    assert any("web" in p for p in written_paths), f"web/ non écrit. Paths: {written_paths}"
    assert any("data" in p and "signals" in p for p in written_paths), "data/signals/ non écrit"


def test_export_signals_json_includes_insider_buy_fields(tmp_path):
    """Le JSON exporté contient insider_buy_value et insider_buy_date si présents."""
    import json

    data_dir = tmp_path / "data" / "signals"
    data_dir.mkdir(parents=True)
    json_path = str(data_dir / "signals_latest.json")

    stock = pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "name": "Apple",
                "sector": "Technology",
                "score_global": 85.0,
                "score_quality": 80.0,
                "score_valuation": 75.0,
                "score_momentum": 90.0,
                "pe": 25.0,
                "roe": 0.35,
                "perf_6m": 0.15,
                "mcap_b": 2800.0,
                "quality_flags": [],
                "first_seen_date": "2026-06-01",
                "insider_buy_value": 250_000.0,
                "insider_buy_date": "2026-06-15",
                "suggested_weight_pct": 12.5,
            }
        ]
    )

    with (
        patch("scanner.storage.JSON_PATH", json_path),
        patch(
            "scanner.storage.os.makedirs",
        ),
    ):
        from scanner.storage import export_signals_json

        export_signals_json(stock, pd.DataFrame(), 500)

    with open(json_path) as f:
        data = json.load(f)

    assert data["top_stocks"][0]["insider_buy_value"] == 250_000.0
    assert data["top_stocks"][0]["insider_buy_date"] == "2026-06-15"
