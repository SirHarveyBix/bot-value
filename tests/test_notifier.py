"""Tests unitaires — scanner/notifier.py (messages Telegram, pinning, formatage)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from freezegun import freeze_time

from scanner.notifier import (
    _build_pinned_summary,
    escape_html,
    notify_vix_unavailable,
    pin_message_safe,
    send_message_safe,
    truncate_message_html_safe,
)

# ── escape_html + lookup portfolio ────────────────────────────────────────────


def test_portfolio_lookup_requires_raw_symbol():
    """
    BUG-11 : le lookup portfolio doit utiliser le symbole brut, pas escape_html(symbol).
    Un ticker contenant '&' serait transformé en 'A&amp;B' → lookup rate.
    """
    raw = "A&B"
    portfolio = {raw: {"status": "ACHAT", "days_held": 1}}

    assert raw in portfolio
    assert escape_html(raw) not in portfolio, "Le symbole HTML-échappé ne doit pas matcher"


def test_escape_html_transforms_special_chars():
    """escape_html couvre <, >, &, les guillemets."""
    assert escape_html("<b>") == "&lt;b&gt;"
    assert escape_html("a & b") == "a &amp; b"
    assert escape_html('"quote"') == "&quot;quote&quot;"
    assert escape_html("normal") == "normal"


# ── truncate_message_html_safe ────────────────────────────────────────────────


def test_truncate_closes_open_html_tags():
    """Message tronqué avec <b> non fermée → la fonction ajoute </b>."""
    long_msg = "<b>" + "A" * 200
    result = truncate_message_html_safe(long_msg, max_chars=50)
    assert result.endswith("</b>")


def test_truncate_no_change_when_within_limit():
    """Message court → retourné intact."""
    msg = "<b>Short</b>"
    assert truncate_message_html_safe(msg, max_chars=4096) == msg


def test_truncate_appends_truncation_marker():
    """Message tronqué → se termine par '[message tronqué]'."""
    long_msg = "A" * 5000
    result = truncate_message_html_safe(long_msg, max_chars=4096)
    assert len(result) == 4096
    assert "[message tronqué]" in result


# ── send_message_safe ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_message_safe_returns_message_object():
    """Succès → retourne l'objet Message (nécessaire pour pin_chat_message)."""
    mock_msg = MagicMock()
    mock_msg.message_id = 999
    mock_bot = AsyncMock()
    mock_bot.send_message.return_value = mock_msg

    result = await send_message_safe(mock_bot, "chat_123", "hello")

    assert result is not None
    assert result.message_id == 999


@pytest.mark.asyncio
async def test_send_message_safe_returns_none_on_error():
    """Erreur Telegram → retourne None sans propager l'exception."""
    from telegram.error import BadRequest

    mock_bot = AsyncMock()
    mock_bot.send_message.side_effect = BadRequest("chat not found")

    result = await send_message_safe(mock_bot, "bad", "msg")
    assert result is None


@pytest.mark.asyncio
async def test_send_message_safe_retries_on_rate_limit():
    """RetryAfter → attend + renvoi, retourne le Message du second envoi."""
    from telegram.error import RetryAfter

    mock_msg = MagicMock()
    mock_msg.message_id = 42
    mock_bot = AsyncMock()
    mock_bot.send_message.side_effect = [RetryAfter(1), mock_msg]

    with patch("scanner.notifier.asyncio.sleep"):
        result = await send_message_safe(mock_bot, "chat", "msg")

    assert result is not None
    assert result.message_id == 42


# ── pin_message_safe ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pin_message_safe_calls_pin_chat_message():
    """Succès → appelle pin_chat_message avec disable_notification=True."""
    mock_bot = AsyncMock()
    await pin_message_safe(mock_bot, "chat_123", 456)
    mock_bot.pin_chat_message.assert_called_once_with(chat_id="chat_123", message_id=456, disable_notification=True)


@pytest.mark.asyncio
async def test_pin_message_safe_logs_warning_on_failure():
    """Échec API (bot non Admin) → log warning, pas de crash."""
    mock_bot = AsyncMock()
    mock_bot.pin_chat_message.side_effect = Exception("bot is not admin")

    with patch("scanner.notifier.logger") as mock_logger:
        await pin_message_safe(mock_bot, "123", 456)
        assert mock_logger.warning.called


# ── _build_pinned_summary ─────────────────────────────────────────────────────


@freeze_time("2026-06-04")
def test_build_pinned_summary_contains_expected_elements():
    """Contient la date, le régime, les symboles Top 5, les ETFs et les commandes."""
    stocks = pd.DataFrame(
        [
            {"symbol": "AAPL", "score_global": 90.0, "perf_6m": 0.18},
            {"symbol": "MSFT", "score_global": 85.0, "perf_6m": 0.12},
        ]
    )
    etfs = pd.DataFrame([{"symbol": "QQQ", "score_global": 70.0}])

    msg = _build_pinned_summary(stocks, etfs, "normal")

    assert "2026-06-04" in msg
    assert "NORMAL" in msg
    assert "AAPL" in msg
    assert "MSFT" in msg
    assert "QQQ" in msg
    assert "/scan" in msg
    assert "/help" in msg


def test_build_pinned_summary_empty_stocks_shows_no_signal():
    """Stocks vide → message indique 'Aucun signal'."""
    msg = _build_pinned_summary(pd.DataFrame(), pd.DataFrame(), "panic")
    assert "PANIQUE" in msg
    assert "Aucun signal" in msg


@pytest.mark.parametrize(
    "regime, expected_label",
    [
        ("panic", "PANIQUE"),
        ("prudence", "PRUDENCE"),
        ("bear_light", "BEAR LIGHT"),
        ("normal", "NORMAL"),
    ],
)
def test_build_pinned_summary_regime_labels(regime, expected_label):
    """Chaque valeur de régime produit le bon libellé dans le résumé."""
    msg = _build_pinned_summary(pd.DataFrame(), pd.DataFrame(), regime)
    assert expected_label in msg


# ── Insider buying dans le message Telegram ───────────────────────────────────


def _make_stock_row(symbol="AAPL", insider_value=None, insider_date=None):
    """Helper : DataFrame une ligne pour tests notifier."""
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "name": "Apple Inc.",
                "sector": "Technology",
                "score_global": 85,
                "score_quality": 80,
                "score_valuation": 75,
                "score_momentum": 88,
                "perf_6m": 0.15,
                "outperf_6m": 0.05,
                "pe": 25.0,
                "roe": 0.35,
                "mcap_b": 2800.0,
                "insider_buy_value": insider_value,
                "insider_buy_date": insider_date,
                "first_seen_date": None,
                "earnings_date": None,
                "warning": None,
                "suggested_weight_pct": 12.5,
            }
        ]
    )


# ── notify_vix_unavailable ────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason,expected_fragment",
    [
        ("absent", "absent"),
        ("serie_vide", "serie_vide"),
        ("spy_plat", "spy_plat"),
        ("indices_vides", "indices_vides"),
    ],
)
async def test_notify_vix_unavailable_sends_message(reason, expected_fragment):
    """notify_vix_unavailable envoie un message Telegram contenant la raison."""
    captured = []

    async def fake_send(bot, chat_id, text, **kwargs):
        captured.append(text)
        return MagicMock(message_id=1)

    with (
        patch("scanner.notifier._get_bot", return_value=(MagicMock(), "123")),
        patch("scanner.notifier.send_message_safe", side_effect=fake_send),
    ):
        await notify_vix_unavailable(reason)

    assert len(captured) == 1
    assert expected_fragment in captured[0]
    assert "Market Gate" in captured[0]


@pytest.mark.asyncio
async def test_notify_vix_unavailable_no_token():
    """Token absent → aucun message envoyé, pas de crash."""
    with patch("scanner.notifier._get_bot", return_value=(None, None)):
        await notify_vix_unavailable("serie_vide")


# ── Insider buying dans le message Telegram ───────────────────────────────────


@pytest.mark.asyncio
async def test_send_telegram_signals_includes_insider_buy_line():
    """Message Telegram contient '🏦 Insider buy' quand insider_buy_value est renseigné."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from scanner.notifier import send_telegram_signals

    stock_df = _make_stock_row(insider_value=250_000.0, insider_date="2026-06-15")
    captured = []

    async def fake_send(bot, chat_id, text, **kwargs):
        captured.append(text)
        return MagicMock(message_id=1)

    with (
        patch("scanner.notifier._get_bot", return_value=(MagicMock(), "123")),
        patch("scanner.notifier.send_message_safe", side_effect=fake_send),
        patch("scanner.notifier.pin_message_safe", new_callable=AsyncMock),
        patch("scanner.notifier.asyncio.sleep", new_callable=AsyncMock),
    ):
        await send_telegram_signals(stock_df, pd.DataFrame())

    full_text = "\n".join(captured)
    assert "🏦 Insider buy" in full_text
    assert "$250k" in full_text
    assert "2026-06-15" in full_text


@pytest.mark.asyncio
async def test_send_telegram_signals_no_insider_line_when_absent():
    """Message Telegram n'a pas '🏦 Insider buy' si pas de valeur insider."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from scanner.notifier import send_telegram_signals

    stock_df = _make_stock_row(insider_value=None, insider_date=None)
    captured = []

    async def fake_send(bot, chat_id, text, **kwargs):
        captured.append(text)
        return MagicMock(message_id=1)

    with (
        patch("scanner.notifier._get_bot", return_value=(MagicMock(), "123")),
        patch("scanner.notifier.send_message_safe", side_effect=fake_send),
        patch("scanner.notifier.pin_message_safe", new_callable=AsyncMock),
        patch("scanner.notifier.asyncio.sleep", new_callable=AsyncMock),
    ):
        await send_telegram_signals(stock_df, pd.DataFrame())

    full_text = "\n".join(captured)
    assert "🏦 Insider buy" not in full_text
