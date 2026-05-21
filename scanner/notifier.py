import asyncio
import html
import re
from datetime import date, datetime

from telegram import Bot
from telegram.error import RetryAfter

from scanner.config import CONFIG, logger

_HTML_OPEN_TAG_RE = re.compile(r"<(\w+)[^>/]*>")
_HTML_CLOSE_TAG_RE = re.compile(r"</(\w+)>")
_TELEGRAM_INLINE_TAGS = frozenset(("b", "i", "u", "s", "a", "code", "pre"))


def escape_html(text):
    """Échappe les caractères spéciaux pour le mode HTML de Telegram."""
    return html.escape(str(text))


def truncate_message(msg: str, max_chars: int = None) -> str:
    """Tronque un message Telegram à max_chars avec suffix explicite (Lacune 10)."""
    if max_chars is None:
        max_chars = CONFIG["scanner"].get("telegram_max_chars", 4096)
    if len(msg) <= max_chars:
        return msg
    suffix = "\n[message tronqué]"
    return msg[: max_chars - len(suffix)] + suffix


def truncate_message_html_safe(msg: str, max_chars: int = None) -> str:
    """Tronque à max_chars et ferme les balises HTML ouvertes (sécurité parse_mode HTML)."""
    if max_chars is None:
        max_chars = CONFIG["scanner"].get("telegram_max_chars", 4096)
    if len(msg) <= max_chars:
        return msg
    suffix = "\n[message tronqué]"
    truncated = msg[: max_chars - len(suffix)] + suffix
    open_tags: list[str] = []
    for m in re.finditer(r"<(/?)(\w+)[^>]*>", truncated):
        tag = m.group(2).lower()
        if tag not in _TELEGRAM_INLINE_TAGS:
            continue
        if m.group(1) == "/":
            if open_tags and open_tags[-1] == tag:
                open_tags.pop()
        else:
            open_tags.append(tag)
    for tag in reversed(open_tags):
        truncated += f"</{tag}>"
    return truncated


async def send_message_safe(bot: Bot, chat_id, text: str, **kwargs) -> None:
    """Envoie un message Telegram en gérant RetryAfter (rate limit 429)."""
    try:
        await bot.send_message(chat_id=chat_id, text=text, **kwargs)
    except RetryAfter as e:
        wait = int(e.retry_after) + 1
        logger.warning(f"Telegram RetryAfter {wait}s — pause avant réenvoi")
        await asyncio.sleep(wait)
        await bot.send_message(chat_id=chat_id, text=text, **kwargs)


def _get_bot():
    token = CONFIG["telegram"]["bot_token"]
    chat_id = CONFIG["telegram"]["chat_id"]
    if not token or token.startswith("${"):
        return None, None
    return Bot(token=token), chat_id


async def notify_panic(vix: float, spy: float, ema200: float):
    """Envoie le message Telegram de régime Panique (Silent Scan - Lacune 9)."""
    bot, chat_id = _get_bot()
    if not bot:
        logger.warning("Notifications Telegram désactivées (token manquant).")
        return
    msg = (
        "🚨 <b>RÉGIME DE PANIQUE — SCAN SILENCIEUX</b>\n"
        f"VIX : {vix:.1f} &gt; 35\n"
        f"SPY : {spy:.2f} vs EMA200 : {ema200:.2f}\n"
        "<i>Le scan quantitatif a été exécuté et les données persistées, mais aucune alerte individuelle d'achat n'est émise pour préserver le capital.</i>"
    )
    await send_message_safe(bot, chat_id, truncate_message_html_safe(msg), parse_mode="HTML")


async def notify_fmp_unavailable():
    """Envoie le message Telegram FMP indisponible (Lacune 9)."""
    bot, chat_id = _get_bot()
    if not bot:
        logger.warning("Notifications Telegram désactivées (token manquant).")
        return
    msg = (
        "⚠️ <b>Sniper FMP indisponible</b>\n"
        "<i>Aucune clé API valide ou erreur 5xx persistante après 2 retries.\n"
        "Scan arrêté — aucun signal émis.</i>"
    )
    await send_message_safe(bot, chat_id, truncate_message_html_safe(msg), parse_mode="HTML")


async def notify_vix_unavailable():
    """Envoie l'alerte Telegram VIX/SPY indisponible → scan annulé (T081)."""
    bot, chat_id = _get_bot()
    if not bot:
        logger.warning("Notifications Telegram désactivées (token manquant).")
        return
    msg = (
        "⚠️ <b>VIX indisponible — scan annulé</b>\n"
        "<i>La série VIX ou SPY ne contient aucune valeur valide (NaN/0). "
        "Le scan a été interrompu pour préserver l'intégrité du Market Gate.</i>"
    )
    await send_message_safe(bot, chat_id, truncate_message_html_safe(msg), parse_mode="HTML")


async def send_telegram_signals(top_stocks, top_etfs, market_regime=None, portfolio=None, exits_today=None):
    """
    Envoie les signaux via Telegram.
    Respecte la limite de 1 message/seconde avec un délai de 1.5s.
    """
    bot, chat_id = _get_bot()
    if not bot:
        logger.warning("Notifications Telegram désactivées (token ou chat_id manquant).")
        return

    # T073 — log JSON avant envoi (loguru serialize=True → signals_{date}.jsonl)
    stock_symbols = [row["symbol"] for _, row in top_stocks.iterrows()]
    logger.info(f"signals_dispatch regime={market_regime} stocks={stock_symbols} count={len(stock_symbols)}")

    # 0. Envoi des sorties de position s'il y en a
    if exits_today:
        exit_msg = "🚨 <b>SORTIE DE POSITION</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        for ex in exits_today:
            exit_msg += f"❌ <b>{escape_html(ex['name'])}</b> (${escape_html(ex['symbol'])})\n"
            exit_msg += f"├ Raison: Rang {ex['rank']} (&gt;15) ou Score {ex['score']:.1f}/100 (&lt;70)\n"
            exit_msg += f"└ Détention consécutive: {ex['days_held']} jours\n\n"
        await send_message_safe(bot, chat_id, truncate_message_html_safe(exit_msg), parse_mode="HTML")
        await asyncio.sleep(1.5)

    # 1. Envoi du Header
    header = f"📊 <b>ValueMomentum Scanner — {datetime.now().strftime('%Y-%m-%d')}</b>\n"

    if market_regime == "prudence":
        header += "⚠️ <b>RÉGIME DE PRUDENCE — SPY &lt; EMA200, VIX modéré</b>\n"

    header += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n🏆 <b>TOP ACTIONS DU JOUR</b>"
    await send_message_safe(bot, chat_id, truncate_message_html_safe(header), parse_mode="HTML")
    await asyncio.sleep(1.5)

    # 2. Envoi des Stocks (un par un)
    for i, (_, row) in enumerate(top_stocks.iterrows()):
        symbol = escape_html(row["symbol"])
        name = escape_html(row.get("name", row["symbol"]))
        score = int(row["score_global"])

        # Détermination du statut de portefeuille pour le ticker
        status_tag = ""
        if portfolio and symbol in portfolio:
            item = portfolio[symbol]
            status = item["status"]
            days_held = item["days_held"]
            if status == "ACHAT":
                status_tag = "🚀 <b>ACHAT</b> (Nouveau signal)\n"
            elif status == "MATURATION":
                status_tag = f"⏳ <b>MATURATION</b> (Jour {days_held}/3)\n"
            elif status == "HOLD":
                status_tag = f"🟢 <b>HOLD</b> (Détention : {days_held} jours)\n"

        if status_tag:
            msg = f"#{i + 1}\n{status_tag}📈 <b>{name}</b> (${symbol})\n"
        else:
            msg = f"#{i + 1} 📈 <b>{name}</b> (${symbol})\n"
        msg += f"Score Global : {score}/100\n"
        msg += f"├ Qualité     : {int(row['score_quality'])}/100\n"
        msg += f"├ Valorisation: {int(row['score_valuation'])}/100\n"
        msg += f"└ Momentum    : {int(row['score_momentum'])}/100\n\n"

        msg += f"📈 Perf 6M : {row.get('perf_6m', 0):.1%} vs secteur {row.get('outperf_6m', 0):+.1%}\n"
        msg += f"💰 P/E Fwd : {row.get('pe', 0):.1f} | ROE : {row.get('roe', 0):.1%}\n"
        msg += f"🏢 {escape_html(row.get('sector', 'Unknown'))} | Cap : ${row.get('mcap_b', 0):.1f}B\n"

        if row.get("first_seen_date"):
            days_active = (date.today() - date.fromisoformat(row["first_seen_date"])).days
            msg += f"⏱️ Signal actif depuis : {days_active} jours\n"

        if row.get("earnings_date"):
            msg += f"📅 Earnings : {escape_html(str(row['earnings_date']))}\n"

        if row.get("warning"):
            msg += f"⚠️ {escape_html(row['warning'])}\n"

        msg += f"🔗 <a href='https://finance.yahoo.com/quote/{symbol}'>Yahoo Finance</a>"

        try:
            await send_message_safe(
                bot, chat_id, truncate_message_html_safe(msg), parse_mode="HTML", disable_web_page_preview=True
            )
            await asyncio.sleep(1.5)
        except Exception as e:
            logger.error(f"Erreur envoi Telegram pour {symbol}: {e}")

    # 3. Envoi des ETFs
    if not top_etfs.empty:
        etf_header = "━━━━━━━━━━━━━━━━━━━━━━━━━━\n📦 <b>TOP ETFs DU JOUR</b>"
        await send_message_safe(bot, chat_id, truncate_message_html_safe(etf_header), parse_mode="HTML")
        await asyncio.sleep(1.5)

        for i, (_, row) in enumerate(top_etfs.iterrows()):
            symbol = escape_html(row["symbol"])
            score = int(row["score_global"])
            msg = f"#{i + 1} <b>{symbol}</b>\n"
            msg += f"Score : {score}/100 | Perf 6M : {row['perf_6m']:.1%}\n"
            msg += f"🔗 <a href='https://finance.yahoo.com/quote/{symbol}'>Yahoo Finance</a>"

            try:
                await send_message_safe(
                    bot, chat_id, truncate_message_html_safe(msg), parse_mode="HTML", disable_web_page_preview=True
                )
                await asyncio.sleep(1.5)
            except Exception as e:
                logger.error(f"Erreur envoi Telegram pour {symbol}: {e}")


async def notify(top_stocks, top_etfs, market_regime=None, portfolio=None, exits_today=None):
    """Envoi des signaux via Telegram (Asynchrone)."""
    if top_stocks.empty and top_etfs.empty and not exits_today:
        return
    await send_telegram_signals(top_stocks, top_etfs, market_regime, portfolio, exits_today)
