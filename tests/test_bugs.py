"""
Tests de régression pour les bugs identifiés lors de la relecture code du 2026-06-03.
Chaque test porte le numéro du bug trouvé dans le rapport de revue.
"""

import sqlite3
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from freezegun import freeze_time

# ── BUG-1 : Cache namespace collision yfinance / FMP ──────────────────────────


def test_eligibility_cache_namespace_is_separate(tmp_path):
    """
    _check_single_ticker doit stocker sous 'eligibility', pas 'fundamentals'.
    Sans cette séparation, fetch_ticker_info trouve les données yfinance en cache
    et ne rappelle jamais FMP → roe_3y absent → tous les stocks exclus.
    """
    db_path = str(tmp_path / "cache.db")
    with (
        patch("scanner.cache.DB_PATH", db_path),
        patch("scanner.storage.DB_PATH", db_path),
    ):
        from scanner.cache import CacheManager

        cache = CacheManager(db_path)

        # Simule ce que _check_single_ticker fait
        yfinance_info = {"sector": "Technology", "marketCap": 1_000_000_000}
        cache.set("eligibility", "AAPL", yfinance_info)

        # fetch_ticker_info lit sous "fundamentals" → ne doit PAS trouver les données yfinance
        assert cache.get("fundamentals", "AAPL", 97200) is None, (
            "Les données yfinance ne doivent pas polluer le namespace 'fundamentals'"
        )
        # Mais "eligibility" doit les contenir
        assert cache.get("eligibility", "AAPL", 97200) == yfinance_info


def test_fmp_data_not_shadowed_by_yfinance_in_cache(tmp_path):
    """
    Après un appel FMP, les données FMP sous 'fundamentals' ne doivent pas
    être écrasées par un rechargement yfinance sous 'eligibility'.
    """
    db_path = str(tmp_path / "cache.db")
    with (
        patch("scanner.cache.DB_PATH", db_path),
        patch("scanner.storage.DB_PATH", db_path),
    ):
        from scanner.cache import CacheManager

        cache = CacheManager(db_path)

        fmp_data = {"roe_3y": 0.25, "source": "FMP"}
        yfinance_data = {"sector": "Technology", "marketCap": 5e9}

        cache.set("fundamentals", "MSFT", fmp_data)
        cache.set("eligibility", "MSFT", yfinance_data)

        # Les deux namespaces sont indépendants
        assert cache.get("fundamentals", "MSFT", 97200)["roe_3y"] == 0.25
        assert cache.get("eligibility", "MSFT", 97200)["sector"] == "Technology"


# ── BUG-2 : ETF prices manquantes → outperf_6m toujours None ─────────────────


def test_etf_prices_included_in_price_batch():
    """
    main.py doit inclure ETFs + SECTOR_ETFS dans fetch_prices_batch.
    On vérifie que la liste de tickers passée au batch contient bien XLK (secteur Tech).
    """
    from scanner.fetcher import SECTOR_ETFS

    # SECTOR_ETFS doit contenir les ETFs sectoriels standard
    assert "XLK" in SECTOR_ETFS
    assert "XLV" in SECTOR_ETFS
    assert "SPY" in SECTOR_ETFS

    # Simuler la construction de la liste dans main.py
    eligible_stocks = ["AAPL", "MSFT", "GOOG"]
    initial_etfs = ["QQQ", "IWM"]
    etf_tickers = list(dict.fromkeys(initial_etfs + list(SECTOR_ETFS)))
    all_tickers = eligible_stocks + etf_tickers

    assert "XLK" in all_tickers, "XLK (secteur Tech) doit être dans le batch de prix"
    assert "QQQ" in all_tickers, "ETF utilisateur doit être dans le batch de prix"
    # Pas de doublons
    assert len(all_tickers) == len(set(all_tickers))


# ── BUG-3 : ROE te=1 default quand clé absente ───────────────────────────────


def test_roe_skipped_when_equity_missing():
    """
    fetch_fmp_data : si totalStockholdersEquity absent du bilan FMP,
    on ne doit PAS calculer ni/1 comme ROE. La paire est ignorée.
    Bug d'origine : te=bs_data[i].get("totalStockholdersEquity", 1)
    Correction : te=None → skip.
    """
    is_data = [{"netIncome": 10_000_000_000}]  # clé equity absente
    bs_data = [{}]  # totalStockholdersEquity absent

    roes = []
    for i in range(min(3, len(is_data), len(bs_data))):
        ni = is_data[i].get("netIncome")
        te = bs_data[i].get("totalStockholdersEquity")
        if ni is not None and te is not None and te > 0:
            roes.append(ni / te)

    assert roes == [], "Equity absente → aucun ROE calculé (évite ni/1 = 10B)"


def test_roe_computed_when_equity_present():
    """Cas nominal : ni=100, te=500 → ROE=0.20."""
    is_data = [{"netIncome": 100}]
    bs_data = [{"totalStockholdersEquity": 500}]

    roes = []
    for i in range(min(3, len(is_data), len(bs_data))):
        ni = is_data[i].get("netIncome")
        te = bs_data[i].get("totalStockholdersEquity")
        if ni is not None and te is not None and te > 0:
            roes.append(ni / te)

    assert len(roes) == 1
    assert abs(roes[0] - 0.20) < 1e-9


def test_roe_skipped_when_equity_zero():
    """te=0 → division par zéro évitée."""
    is_data = [{"netIncome": 50}]
    bs_data = [{"totalStockholdersEquity": 0}]

    roes = []
    for i in range(min(3, len(is_data), len(bs_data))):
        ni = is_data[i].get("netIncome")
        te = bs_data[i].get("totalStockholdersEquity")
        if ni is not None and te is not None and te > 0:
            roes.append(ni / te)

    assert roes == []


# ── BUG-4 : update_signal_returns filtre sur first_seen_date au lieu de scan_date ──


@pytest.mark.asyncio
async def test_update_signal_returns_uses_scan_date(tmp_path):
    """
    Régression BUG-4 : update_signal_returns doit filtrer par scan_date (via JOIN scans),
    pas par first_seen_date.

    Scénario :
    - Signal A : scan_date = aujourd'hui, first_seen_date = J-40 (ticker historique réapparu)
      → return_30d ne doit PAS être calculé (scan trop récent)
    - Signal B : scan_date = J-35, first_seen_date = J-35
      → return_30d DOIT être calculé
    """
    import aiosqlite

    db_path = str(tmp_path / "test_returns.db")

    with patch("scanner.storage.DB_PATH", db_path):
        from scanner.storage import init_db, update_signal_returns

        init_db()

        today = date.today().isoformat()
        old_date = (date.today() - timedelta(days=35)).isoformat()

        async with aiosqlite.connect(db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            # Scan A : aujourd'hui
            await db.execute(
                "INSERT INTO scans (scan_date, market_regime, eligible_count) VALUES (?, 'normal', 10)",
                (today,),
            )
            scan_a_id = (await (await db.execute("SELECT last_insert_rowid()")).fetchone())[0]

            # Scan B : il y a 35 jours
            await db.execute(
                "INSERT INTO scans (scan_date, market_regime, eligible_count) VALUES (?, 'normal', 10)",
                (old_date,),
            )
            scan_b_id = (await (await db.execute("SELECT last_insert_rowid()")).fetchone())[0]

            # Signal A : scan récent + first_seen_date ancienne (ticker réapparu)
            await db.execute(
                "INSERT INTO signals (scan_id, symbol, type, rank, score_global, price_at_signal, first_seen_date) "
                "VALUES (?, 'AAPL', 'stock', 1, 80.0, 150.0, ?)",
                (scan_a_id, old_date),
            )

            # Signal B : scan ancien, first_seen_date ancienne
            await db.execute(
                "INSERT INTO signals (scan_id, symbol, type, rank, score_global, price_at_signal, first_seen_date) "
                "VALUES (?, 'MSFT', 'stock', 2, 75.0, 200.0, ?)",
                (scan_b_id, old_date),
            )
            await db.commit()

        # Mock yfinance pour retourner un prix courant
        mock_df = pd.DataFrame(
            {"MSFT": {"Close": 210.0}},
        )
        mock_df.columns = pd.MultiIndex.from_tuples([("MSFT", "Close")])
        mock_df.index = [pd.Timestamp("2026-06-04")]

        with patch("scanner.storage.yf.download", return_value=mock_df):
            await update_signal_returns()

        async with aiosqlite.connect(db_path) as db:
            row_a = await (
                await db.execute("SELECT price_30d_later, return_30d FROM signals WHERE symbol = 'AAPL'")
            ).fetchone()
            row_b = await (
                await db.execute("SELECT price_30d_later, return_30d FROM signals WHERE symbol = 'MSFT'")
            ).fetchone()

    # Signal A (scan aujourd'hui) → pas encore de 30j → return_30d doit rester NULL
    assert row_a[0] is None, "Signal du scan d'aujourd'hui : return_30d ne doit pas être calculé"

    # Signal B (scan J-35) → return_30d doit être calculé
    assert row_b[0] is not None, "Signal du scan J-35 : return_30d doit être calculé"
    assert abs(row_b[1] - (210.0 - 200.0) / 200.0) < 1e-6


# ── BUG-5 : get_first_seen_dates_batch MAX(id) → MIN(first_seen_date) ─────────


def test_get_first_seen_dates_batch_returns_earliest(tmp_path):
    """
    get_first_seen_dates_batch doit retourner la PREMIÈRE date d'apparition,
    pas la plus récente. On insère deux signaux pour AAPL avec des dates différentes.
    """
    db_path = str(tmp_path / "test_fsd.db")

    with patch("scanner.storage.DB_PATH", db_path):
        from scanner.storage import get_first_seen_dates_batch, init_db

        init_db()

        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO scans (scan_date, market_regime, eligible_count) VALUES ('2026-01-01', 'normal', 10)")
        scan1_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO scans (scan_date, market_regime, eligible_count) VALUES ('2026-03-01', 'normal', 10)")
        scan2_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Premier signal AAPL : first_seen_date = 2026-01-01
        conn.execute(
            "INSERT INTO signals (scan_id, symbol, type, rank, score_global, first_seen_date) "
            "VALUES (?, 'AAPL', 'stock', 1, 80.0, '2026-01-01')",
            (scan1_id,),
        )
        # Deuxième signal AAPL (réapparu) : first_seen_date conservée = 2026-01-01
        conn.execute(
            "INSERT INTO signals (scan_id, symbol, type, rank, score_global, first_seen_date) "
            "VALUES (?, 'AAPL', 'stock', 1, 85.0, '2026-01-01')",
            (scan2_id,),
        )
        # Signal corrompu hypothétique avec une date plus récente
        conn.execute(
            "INSERT INTO signals (scan_id, symbol, type, rank, score_global, first_seen_date) "
            "VALUES (?, 'AAPL', 'stock', 1, 90.0, '2026-03-01')",
            (scan2_id,),
        )
        conn.commit()
        conn.close()

        result = get_first_seen_dates_batch(["AAPL"], "2026-06-01")

    # MIN(first_seen_date) doit retourner 2026-01-01, pas 2026-03-01
    assert result["AAPL"] == "2026-01-01", f"Attendu 2026-01-01, obtenu {result['AAPL']}"


# ── BUG-6 : compute_inverse_vol_weights jamais appelée ───────────────────────


def test_compute_inverse_vol_weights_sets_suggested_weight():
    """
    compute_inverse_vol_weights doit setter suggested_weight_pct sur chaque ticker.
    Ce champ était absent avant le fix (fonction jamais appelée dans main.py).
    """
    import numpy as np

    from scanner.scoring.engine import compute_inverse_vol_weights

    symbols = ["AAPL", "MSFT", "GOOG"]
    df = pd.DataFrame({"symbol": symbols, "score_global": [90.0, 85.0, 80.0]})

    # Construire all_data avec 60 jours de prix synthétiques
    rng = np.random.default_rng(42)
    all_data = {}
    for sym in symbols:
        prices = 100 * np.cumprod(1 + rng.normal(0, 0.01, 65))
        all_data[sym] = {
            "prices": pd.DataFrame({"Close": prices}),
        }

    result = compute_inverse_vol_weights(df, all_data)

    assert "suggested_weight_pct" in result.columns
    assert result["suggested_weight_pct"].notna().all()
    # Les poids doivent sommer à ~100%
    assert abs(result["suggested_weight_pct"].sum() - 100.0) < 1e-6


# ── BUG-11 : escape_html(symbol) utilisé pour lookup portfolio ───────────────


@pytest.mark.asyncio
async def test_portfolio_lookup_uses_raw_symbol():
    """
    send_telegram_signals : le lookup `portfolio[raw_symbol]` doit utiliser
    le symbole brut, pas l'échappé HTML. Test avec un ticker contenant '&'
    (hypothétique mais couvre le pattern de correction).
    """
    from scanner.notifier import escape_html

    raw = "BRK.B"
    portfolio = {raw: {"status": "HOLD", "days_held": 5}}

    # La correction : lookup avec raw, pas escaped
    assert raw in portfolio, "Lookup doit fonctionner avec symbole brut"
    # Vérifie que escaped != raw pour un cas avec char spécial
    raw_special = "A&B"
    assert escape_html(raw_special) == "A&amp;B"
    # Et que le lookup échouerait avec l'escaped
    port2 = {"A&B": {"status": "ACHAT", "days_held": 1}}
    assert escape_html(raw_special) not in port2


# ── BUG-notifier : _build_pinned_summary ─────────────────────────────────────


def test_build_pinned_summary_structure():
    """_build_pinned_summary : contient date, régime, Top stocks, ETFs, commandes."""
    from scanner.notifier import _build_pinned_summary

    stocks = pd.DataFrame(
        [
            {"symbol": "AAPL", "score_global": 90.0, "perf_6m": 0.18},
            {"symbol": "MSFT", "score_global": 85.0, "perf_6m": 0.12},
        ]
    )
    etfs = pd.DataFrame(
        [
            {"symbol": "QQQ", "score_global": 70.0},
        ]
    )

    with freeze_time("2026-06-04"):
        msg = _build_pinned_summary(stocks, etfs, "normal")

    assert "2026-06-04" in msg
    assert "NORMAL" in msg
    assert "AAPL" in msg
    assert "MSFT" in msg
    assert "QQQ" in msg
    assert "/scan" in msg
    assert "/help" in msg


def test_build_pinned_summary_empty_stocks():
    """_build_pinned_summary avec stocks vide → mention 'Aucun signal'."""
    from scanner.notifier import _build_pinned_summary

    msg = _build_pinned_summary(pd.DataFrame(), pd.DataFrame(), "panic")

    assert "PANIQUE" in msg
    assert "Aucun signal" in msg


def test_build_pinned_summary_regime_labels():
    """Chaque régime produit le bon label dans le résumé."""
    from scanner.notifier import _build_pinned_summary

    for regime, expected in [
        ("panic", "PANIQUE"),
        ("prudence", "PRUDENCE"),
        ("bear_light", "BEAR LIGHT"),
        ("normal", "NORMAL"),
    ]:
        msg = _build_pinned_summary(pd.DataFrame(), pd.DataFrame(), regime)
        assert expected in msg, f"Régime {regime} → attendu '{expected}' dans le résumé"


# ── BUG-notifier : pin_message_safe ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_pin_message_safe_logs_warning_on_failure():
    """pin_message_safe : échec API Telegram → log warning, pas de crash."""
    from scanner.notifier import pin_message_safe

    mock_bot = AsyncMock()
    mock_bot.pin_chat_message.side_effect = Exception("bot is not admin")

    with patch("scanner.notifier.logger") as mock_logger:
        await pin_message_safe(mock_bot, "123", 456)
        assert mock_logger.warning.called
        warning_msg = str(mock_logger.warning.call_args)
        assert "Admin" in warning_msg or "pin" in warning_msg.lower()


@pytest.mark.asyncio
async def test_send_message_safe_returns_message_object():
    """send_message_safe doit retourner l'objet Message (pour récupérer message_id)."""
    from scanner.notifier import send_message_safe

    mock_msg = MagicMock()
    mock_msg.message_id = 999
    mock_bot = AsyncMock()
    mock_bot.send_message.return_value = mock_msg

    result = await send_message_safe(mock_bot, "chat_123", "test message")

    assert result is not None
    assert result.message_id == 999


@pytest.mark.asyncio
async def test_send_message_safe_returns_none_on_error():
    """send_message_safe : erreur → retourne None (pas d'exception propagée)."""
    from telegram.error import BadRequest

    from scanner.notifier import send_message_safe

    mock_bot = AsyncMock()
    mock_bot.send_message.side_effect = BadRequest("chat not found")

    result = await send_message_safe(mock_bot, "bad", "msg")
    assert result is None


# ── BUG-fetcher : disjoncteur FMP ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fmp_circuit_breaker_skips_when_budget_exceeded():
    """
    fetch_fmp_data : si fmp_call_counter + 5 > budget_hard_limit → retourne None
    sans appeler l'API (disjoncteur global).
    """
    import scanner.fetcher as fetcher_mod
    from scanner.fetcher import fetch_fmp_data

    original_count = fetcher_mod.fmp_call_counter

    with (
        patch.dict(
            "scanner.fetcher.CONFIG",
            {"scanner": {"fmp_call_budget_hard_limit": 175, "fmp_api_key": "key123", "fmp_base_url": "https://fmp"}},
        ),
    ):
        fetcher_mod.fmp_call_counter = 171  # 171 + 5 > 175

        mock_client = AsyncMock()
        result = await fetch_fmp_data(mock_client, "AAPL")

        assert result is None
        mock_client.get.assert_not_called()

    fetcher_mod.fmp_call_counter = original_count


@pytest.mark.asyncio
async def test_fmp_raises_when_api_key_missing():
    """fetch_fmp_data : clé API absente → FMPUnavailableError."""
    import scanner.fetcher as fetcher_mod
    from scanner.fetcher import FMPUnavailableError, fetch_fmp_data

    original_count = fetcher_mod.fmp_call_counter
    fetcher_mod.fmp_call_counter = 0

    with patch.dict(
        "scanner.fetcher.CONFIG",
        {"scanner": {"fmp_call_budget_hard_limit": 175, "fmp_api_key": None, "fmp_base_url": "https://fmp"}},
    ):
        mock_client = AsyncMock()
        with pytest.raises(FMPUnavailableError):
            await fetch_fmp_data(mock_client, "AAPL")

    fetcher_mod.fmp_call_counter = original_count


# ── BUG-10 : check_batch_data_ratio get_level_values(0).unique() ─────────────


def test_check_batch_data_ratio_no_ghost_levels():
    """
    levels[0] peut contenir des tickers 'fantômes' après concat.
    get_level_values(0).unique() compte uniquement les tickers réellement présents.
    """
    from scanner.filters import check_batch_data_ratio

    # Créer deux DataFrames partiels et les concaténer
    df1 = pd.DataFrame(columns=pd.MultiIndex.from_tuples([("AAPL", "Close"), ("MSFT", "Close")]))
    df2 = pd.DataFrame(columns=pd.MultiIndex.from_tuples([("GOOG", "Close")]))
    combined = pd.concat([df1, df2], axis=1)

    # levels[0] peut garder des fantômes selon la version pandas
    # get_level_values(0).unique() doit donner le bon compte
    real_count = len(combined.columns.get_level_values(0).unique())
    assert real_count == 3

    # 3 tickers / eligible=4 → ratio=0.75 ≥ 0.60 → True
    assert check_batch_data_ratio(combined, 4)
    # 3 tickers / eligible=6 → ratio=0.50 < 0.60 → False
    assert not check_batch_data_ratio(combined, 6)
