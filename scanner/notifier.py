import asyncio
import html
import math
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


async def send_message_safe(bot: Bot, chat_id, text: str, **kwargs):
    """Envoie un message Telegram. Retourne l'objet Message (pour pin), ou None si erreur."""
    try:
        sent = await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        logger.info(f"Telegram message envoyé (chat_id={chat_id})")
        return sent
    except RetryAfter as e:
        wait = int(e.retry_after) + 1
        logger.warning(f"Telegram RetryAfter {wait}s — pause avant réenvoi")
        await asyncio.sleep(wait)
        try:
            sent = await bot.send_message(chat_id=chat_id, text=text, **kwargs)
            logger.info(f"Telegram message envoyé après retry (chat_id={chat_id})")
            return sent
        except Exception as e2:
            logger.error(f"Telegram échec après retry: {e2}")
    except Exception as e:
        logger.error(f"Telegram send_message_safe: {e} (chat_id={chat_id})")
    return None


async def pin_message_safe(bot: Bot, chat_id, message_id: int) -> None:
    """Épingle un message sans notification (silencieux)."""
    try:
        await bot.pin_chat_message(chat_id=chat_id, message_id=message_id, disable_notification=True)
        logger.info(f"Telegram message {message_id} épinglé")
    except Exception as e:
        logger.warning(f"Telegram pin_message_safe: {e} — le bot doit être Admin pour épingler")


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


async def notify_vix_unavailable(reason: str = "serie_vide"):
    """Envoie l'alerte Telegram VIX/SPY indisponible → scan annulé (T081).

    reason:
      "absent"     — SPY ou ^VIX absent du téléchargement yfinance
      "serie_vide" — série vide après dropna (NaN/0)
      "spy_plat"   — SPY std < 1.0 (données stale yfinance)
      "indices_vides" — DataFrame complet vide
    """
    bot, chat_id = _get_bot()
    if not bot:
        logger.warning("Notifications Telegram désactivées (token manquant).")
        return
    detail = {
        "absent": "SPY ou ^VIX absent du téléchargement yfinance (ticker non reconnu).",
        "serie_vide": "La série VIX ou SPY ne contient aucune valeur valide après filtrage NaN/0.",
        "spy_plat": "SPY retourné par yfinance est suspect : série quasi-plate (données stale). Probable ban IP yfinance.",
        "indices_vides": "yfinance n'a retourné aucune donnée pour SPY/VIX (DataFrame vide).",
    }.get(reason, "Erreur inconnue Market Gate.")
    msg = (
        f"⚠️ <b>Market Gate — scan annulé</b>\n"
        f"<code>{reason}</code> : {detail}\n"
        "<i>Le scan reprendra à 09h35 ET. Si l'erreur persiste, vérifier les logs sur le serveur.</i>"
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
            exit_msg += f"├ Raison: Rang {ex['rank']} (&gt;15) ou Score {ex.get('score') or 0.0:.1f}/100 (&lt;70)\n"
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
        raw_symbol = row["symbol"]
        symbol = escape_html(raw_symbol)
        name = escape_html(row.get("name", raw_symbol))
        score = int(row.get("score_global") or 0)

        # Détermination du statut de portefeuille pour le ticker
        status_tag = ""
        if portfolio and raw_symbol in portfolio:
            item = portfolio[raw_symbol]
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
        msg += f"├ Qualité     : {int(row.get('score_quality') or 0)}/100\n"
        msg += f"├ Valorisation: {int(row.get('score_valuation') or 0)}/100\n"
        msg += f"└ Momentum    : {int(row.get('score_momentum') or 0)}/100\n\n"

        msg += f"📈 Perf 6M : {row.get('perf_6m', 0):.1%} vs secteur {row.get('outperf_6m', 0):+.1%}\n"
        msg += f"💰 P/E Fwd : {row.get('pe', 0):.1f} | ROE : {row.get('roe', 0):.1%}\n"
        msg += f"🏢 {escape_html(row.get('sector', 'Unknown'))} | Cap : ${row.get('mcap_b', 0):.1f}B\n"

        if row.get("first_seen_date"):
            try:
                days_active = (date.today() - date.fromisoformat(row["first_seen_date"])).days
                msg += f"⏱️ Signal actif depuis : {days_active} jours\n"
            except ValueError:
                pass

        if row.get("insider_buy_value") and row.get("insider_buy_date"):
            value_k = int(row["insider_buy_value"] / 1000)
            msg += f"🏦 Insider buy : ${value_k}k ({escape_html(str(row['insider_buy_date']))})\n"

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
            raw_symbol = row["symbol"]
            symbol = escape_html(raw_symbol)
            name = escape_html(str(row.get("name", raw_symbol)))
            score = int(row["score_global"])
            perf_6m = row.get("perf_6m", 0.0) or 0.0
            outperf = row.get("outperf_spy")

            msg = f"#{i + 1} <b>{symbol}</b> — {name}\n"
            msg += f"Score : {score}/100\n"
            msg += f"Perf 6M : {perf_6m:+.1%}"
            if outperf is not None and not (isinstance(outperf, float) and math.isnan(outperf)):
                msg += f" | vs SPY : {outperf:+.1%}"
            msg += f"\n🔗 <a href='https://finance.yahoo.com/quote/{raw_symbol}'>Yahoo Finance — {name}</a>"

            try:
                await send_message_safe(
                    bot, chat_id, truncate_message_html_safe(msg), parse_mode="HTML", disable_web_page_preview=True
                )
                await asyncio.sleep(1.5)
            except Exception as e:
                logger.error(f"Erreur envoi Telegram pour {symbol}: {e}")

    # 4. Message résumé compact → épinglé (remplace le pin précédent)
    pinned = _build_pinned_summary(top_stocks, top_etfs, market_regime)
    sent = await send_message_safe(bot, chat_id, truncate_message_html_safe(pinned), parse_mode="HTML")
    if sent:
        await pin_message_safe(bot, chat_id, sent.message_id)


def _build_pinned_summary(top_stocks, top_etfs, market_regime: str | None) -> str:
    """Construit le message résumé compact destiné à être épinglé."""
    today = datetime.now().strftime("%Y-%m-%d")
    regime_label = {
        "panic": "🚨 PANIQUE",
        "prudence": "⚠️ PRUDENCE",
        "bear_light": "🐻 BEAR LIGHT",
        "normal": "✅ NORMAL",
    }.get(market_regime or "normal", "✅ NORMAL")

    msg = f"📌 <b>ValueMomentum — {today}</b>\n"
    msg += f"Régime : {regime_label}\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n"

    if not top_stocks.empty:
        msg += "🏆 <b>Top stocks</b>\n"
        for i, (_, row) in enumerate(top_stocks.head(5).iterrows()):
            sym = escape_html(row["symbol"])
            score = int(row["score_global"])
            perf = row.get("perf_6m", 0.0)
            perf = 0.0 if (perf is None or (isinstance(perf, float) and math.isnan(perf))) else perf
            msg += f"  {i + 1}. <b>{sym}</b> — {score}/100 | Perf 6M {perf:+.1%}\n"
    else:
        msg += "Aucun signal stock.\n"

    if not top_etfs.empty:
        msg += "📦 <b>Top ETFs</b>\n"
        for i, (_, row) in enumerate(top_etfs.head(2).iterrows()):
            sym = escape_html(row["symbol"])
            score = int(row["score_global"])
            msg += f"  {i + 1}. <b>{sym}</b> — {score}/100\n"

    msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += "Commandes : /scan /status /help"
    return msg


_GATE_EMOJI = {
    "qualité": "📊",
    "valorisation": "💰",
    "fraîcheur": "📅",
    "diversification": "🔢",
    "sanity": "⚡",
    "données": "❓",
}


async def notify_exclusions(exclusions: list[dict]) -> None:
    """Envoie un message Telegram listant les tickers exclus avec la raison (par gate)."""
    if not exclusions:
        return
    bot, chat_id = _get_bot()
    if not bot:
        return

    msg = "🔍 <b>TICKERS ANALYSÉS ET EXCLUS</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    by_gate: dict[str, list[dict]] = {}
    for exc in exclusions:
        by_gate.setdefault(exc["gate"], []).append(exc)

    for gate, items in by_gate.items():
        emoji = _GATE_EMOJI.get(gate, "❌")
        msg += f"\n{emoji} <b>{gate.capitalize()}</b>\n"
        for item in items:
            name = escape_html(item.get("name") or item["symbol"])
            symbol = escape_html(item["symbol"])
            reason = escape_html(item.get("reason", "—"))
            msg += f"  ❌ <b>{name}</b> (${symbol}) — {reason}\n"

    await send_message_safe(bot, chat_id, truncate_message_html_safe(msg), parse_mode="HTML")


async def notify_error(module: str, error: str) -> None:
    """Alerte Telegram pour toute erreur critique de scan (SC-004)."""
    bot, chat_id = _get_bot()
    if not bot:
        return
    msg = (
        f"🚨 <b>ValueMomentum — Erreur critique</b>\n"
        f"Module : <code>{escape_html(module)}</code>\n"
        f"Erreur : <code>{escape_html(error[:300])}</code>\n"
        "<i>Vérifier les logs sur le serveur.</i>"
    )
    await send_message_safe(bot, chat_id, truncate_message_html_safe(msg), parse_mode="HTML")


async def notify_universe_too_small(count: int, minimum: int) -> None:
    """Alerte Telegram si l'univers éligible est trop petit pour un scan fiable."""
    bot, chat_id = _get_bot()
    if not bot:
        return
    msg = (
        f"⚠️ <b>Univers trop petit — scan annulé</b>\n"
        f"{count} tickers éligibles &lt; minimum {minimum}.\n"
        "<i>yfinance retourne probablement des données partielles (IP throttle).\n"
        "Le scan reprendra demain à 09h35 ET.</i>"
    )
    await send_message_safe(bot, chat_id, truncate_message_html_safe(msg), parse_mode="HTML")


async def notify_yfinance_ban() -> None:
    """Alerte Telegram si yfinance retourne trop peu de données (IP ban probable)."""
    bot, chat_id = _get_bot()
    if not bot:
        logger.warning("Notifications Telegram désactivées (token manquant).")
        return
    msg = (
        "🚫 <b>BAN IP yfinance détecté — scan interrompu</b>\n"
        "<i>Le batch download yfinance a retourné moins de 60% de données valides.\n"
        "Yahoo Finance a probablement bloqué l'IP temporairement.\n"
        "Réessayez dans 15–30 minutes ou changez de réseau.</i>"
    )
    await send_message_safe(bot, chat_id, truncate_message_html_safe(msg), parse_mode="HTML")


async def notify(top_stocks, top_etfs, market_regime=None, portfolio=None, exits_today=None):
    """Envoi des signaux via Telegram (Asynchrone)."""
    if top_stocks.empty and top_etfs.empty and not exits_today:
        bot, chat_id = _get_bot()
        if bot:
            regime_label = {
                "panic": "🚨 PANIQUE",
                "prudence": "⚠️ PRUDENCE",
                "bear_light": "🐻 BEAR LIGHT",
                "normal": "✅ NORMAL",
            }.get(market_regime or "normal", "✅ NORMAL")
            msg = (
                f"📊 <b>Scan terminé — aucun signal émis</b>\n"
                f"Régime : {regime_label}\n"
                "<i>Tous les tickers ont été exclus par les gates qualité/valorisation.</i>"
            )
            await send_message_safe(bot, chat_id, msg, parse_mode="HTML")
        return
    await send_telegram_signals(top_stocks, top_etfs, market_regime, portfolio, exits_today)


_active_tasks: set[asyncio.Task] = set()
_scan_in_progress = False


async def _run_scan_guarded(run_scanner_fn) -> None:
    """Wrapper pour le scan déclenché depuis Telegram : log les erreurs et libère le guard."""
    global _scan_in_progress
    try:
        await run_scanner_fn(force=True)
    except Exception as e:
        logger.error(f"Erreur scan déclenché depuis Telegram: {e}")
    finally:
        _scan_in_progress = False


async def poll_telegram_commands(run_scanner_fn) -> None:
    """
    Écoute les commandes Telegram entrantes et les exécute.
    Tourne en parallèle du scheduler (asyncio.create_task).

    Commandes disponibles :
      /scan   — déclenche un scan immédiat (équivalent --force)
      /status — affiche le dernier scan en base
      /help   — liste les commandes
    """
    global _scan_in_progress
    import sqlite3

    from scanner.storage import DB_PATH

    bot, chat_id = _get_bot()
    if not bot:
        return

    last_update_id = None
    logger.info("Telegram command polling démarré.")

    while True:
        try:
            kwargs = {"timeout": 30, "allowed_updates": ["message"]}
            if last_update_id is not None:
                kwargs["offset"] = last_update_id + 1

            updates = await bot.get_updates(**kwargs)

            for update in updates:
                try:
                    last_update_id = update.update_id
                    msg = update.message
                    if not msg or not msg.text:
                        continue

                    # Filtre : n'accepte que les messages du chat configuré
                    if str(msg.chat.id) != str(chat_id):
                        continue

                    parts = msg.text.strip().lower().split()
                    if not parts:
                        continue
                    text = parts[0]

                    if text in ("/scan", "/force"):
                        if _scan_in_progress:
                            await send_message_safe(
                                bot,
                                chat_id,
                                "⚠️ Scan déjà en cours, patientez.",
                                parse_mode="HTML",
                            )
                        else:
                            await send_message_safe(
                                bot,
                                chat_id,
                                "⏳ <b>Scan manuel déclenché…</b>\nRésultats dans 10–15 min.",
                                parse_mode="HTML",
                            )
                            logger.info(f"Commande Telegram /scan reçue depuis chat_id={msg.chat.id}")
                            _scan_in_progress = True
                            task = asyncio.create_task(_run_scan_guarded(run_scanner_fn))
                            _active_tasks.add(task)
                            task.add_done_callback(_active_tasks.discard)

                    elif text == "/status":

                        def _get_status():
                            try:
                                with sqlite3.connect(DB_PATH) as conn:
                                    scan_row = conn.execute(
                                        "SELECT scan_date, market_regime, spy_price, vix FROM scans ORDER BY scan_date DESC LIMIT 1"
                                    ).fetchone()
                                    signal_count = conn.execute(
                                        "SELECT COUNT(*) FROM signals WHERE scan_date = (SELECT MAX(scan_date) FROM signals)"
                                    ).fetchone()
                                    total_scans = conn.execute("SELECT COUNT(*) FROM scans").fetchone()
                                    return (
                                        scan_row,
                                        (signal_count[0] if signal_count else 0),
                                        (total_scans[0] if total_scans else 0),
                                    )
                            except Exception as err:
                                logger.warning(f"Erreur lecture statut DB: {err}")
                                return None, 0, 0

                        result = await asyncio.to_thread(_get_status)
                        row, signal_count, total_scans = result
                        if row:
                            scan_date, regime, spy, vix = row
                            regime_label = {
                                "panic": "🚨 PANIQUE",
                                "prudence": "⚠️ PRUDENCE",
                                "bear_light": "🐻 BEAR LIGHT",
                                "normal": "✅ NORMAL",
                            }.get(regime or "normal", "✅ NORMAL")
                            try:
                                age_h = int((datetime.now() - datetime.fromisoformat(scan_date)).total_seconds() / 3600)
                                age_str = f"{age_h}h" if age_h < 48 else f"{age_h // 24}j"
                            except Exception:
                                age_str = "?"
                            in_progress_str = " | ⏳ scan en cours" if _scan_in_progress else ""
                            status_msg = (
                                f"📌 <b>Dernier scan : {scan_date}</b> (il y a {age_str}){in_progress_str}\n"
                                f"Régime : {regime_label} | SPY : {spy:.2f} | VIX : {vix:.1f}\n"
                                f"Signaux émis : {signal_count} | Scans total : {total_scans}\n"
                                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                "Commandes : /scan /status /help"
                            )
                        else:
                            status_msg = "❓ Aucun scan en base. Scanner démarré ?"
                        await send_message_safe(bot, chat_id, status_msg, parse_mode="HTML")

                    elif text == "/help":
                        help_msg = (
                            "🤖 <b>ValueMomentum Scanner — Commandes</b>\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            "/scan — Déclenche un scan immédiat\n"
                            "/status — Affiche le dernier scan\n"
                            "/aide — Explique le score et les indicateurs\n"
                            "/help — Cette aide"
                        )
                        await send_message_safe(bot, chat_id, help_msg, parse_mode="HTML")

                    elif text == "/aide":
                        aide1 = (
                            "📖 <b>ValueMomentum — Guide du score</b>\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            "\n"
                            "🏆 <b>Score global (0–100)</b>\n"
                            "Composite de 3 piliers pondérés :\n"
                            "  • Qualité : 35 %\n"
                            "  • Momentum : 35 %\n"
                            "  • Valorisation : 30 %\n"
                            "\n"
                            "🔵 <b>Qualité (35 %)</b>\n"
                            "Mesure la solidité financière de l'entreprise.\n"
                            "  • <b>ROE 3 ans</b> : rentabilité sur fonds propres moyennée sur 3 ans. Doit être &gt; 0 (obligatoire).\n"
                            "  • <b>ROIC</b> : retour sur capital investi.\n"
                            "  • <b>Marge opérationnelle</b> : bénéfice avant intérêts / CA.\n"
                            "  • <b>FCF Yield</b> : cash disponible / capitalisation boursière.\n"
                            "  • <b>Dette/EBITDA</b> : levier financier. Exclu si &gt; 6×.\n"
                        )
                        await send_message_safe(bot, chat_id, aide1, parse_mode="HTML")
                        await asyncio.sleep(1.0)

                        aide2 = (
                            "📈 <b>Momentum (35 %)</b>\n"
                            "Mesure la dynamique de prix récente.\n"
                            "  • <b>Perf 6M</b> : performance sur 6 mois (126 séances).\n"
                            "  • <b>Perf 3M</b> : performance sur 3 mois.\n"
                            "  • <b>Surperf. secteur</b> : perf du titre vs ETF de son secteur.\n"
                            "  • <b>Surprise earnings</b> : bonus si l'entreprise a battu les estimations récemment (décroit sur 90j).\n"
                            "\n"
                            "💰 <b>Valorisation (30 %)</b>\n"
                            "Cherche les titres peu chers par rapport à leurs pairs.\n"
                            "  • <b>P/E forward</b> : prix / bénéfice estimé. Moins = mieux.\n"
                            "  • <b>EV/EBITDA</b> : valeur entreprise / résultat opérationnel.\n"
                            "  • <b>PEG</b> : P/E divisé par la croissance attendue.\n"
                        )
                        await send_message_safe(bot, chat_id, aide2, parse_mode="HTML")
                        await asyncio.sleep(1.0)

                        aide3 = (
                            "🚧 <b>Gates d'exclusion</b>\n"
                            "Un ticker est exclu s'il échoue l'un de ces critères :\n"
                            "  • <b>Sanity</b> : variation journalière &gt; +50 % ou &lt; –45 % (split ou erreur de données).\n"
                            "  • <b>Qualité</b> : ROE &lt; 0, EBITDA ≤ 0, dette/EBITDA &gt; 6×, book value ≤ 0.\n"
                            "  • <b>Valorisation</b> : P/E &gt; 60 ou négatif sans justification.\n"
                            "  • <b>Liquidité</b> : cap. boursière &lt; 2 Md$, volume &lt; 5 M$/j, prix &lt; 5$.\n"
                            "\n"
                            "🌡 <b>Régimes de marché</b>\n"
                            "  • ✅ <b>NORMAL</b> : SPY ≥ EMA200 et VIX ≤ 25. Scan complet.\n"
                            "  • ⚠️ <b>PRUDENCE</b> : SPY &lt; EMA200 et VIX entre 25 et 35. Signaux émis avec avertissement.\n"
                            "  • 🐻 <b>BEAR LIGHT</b> : SPY &lt; EMA200 et VIX ≤ 25. Scan normal, log interne.\n"
                            "  • 🚨 <b>PANIQUE</b> : VIX &gt; 35. Scan silencieux — aucun signal émis.\n"
                            "\n"
                            "⚖️ <b>Poids suggéré (%)</b>\n"
                            "Pondération inverse-volatilité sur 63 jours. Les titres moins volatils reçoivent un poids plus élevé pour équilibrer le risque du portefeuille."
                        )
                        await send_message_safe(bot, chat_id, aide3, parse_mode="HTML")

                except Exception as e:
                    logger.warning(f"Erreur traitement update {update.update_id}: {e}")

        except asyncio.CancelledError:
            logger.info("Telegram command polling arrêté.")
            raise
        except Exception as e:
            if "401" in str(e) or "Unauthorized" in str(e):
                logger.warning("Token Telegram invalide — rechargement")
                bot, chat_id = _get_bot()
                if not bot:
                    break
            else:
                logger.warning(f"Telegram polling erreur: {e}")
            await asyncio.sleep(5)
