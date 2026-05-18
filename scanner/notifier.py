import asyncio
import html
from datetime import datetime

from telegram import Bot

from scanner.config import CONFIG, logger


def escape_html(text):
    """Échappe les caractères spéciaux pour le mode HTML de Telegram."""
    return html.escape(str(text))

async def send_telegram_signals(top_stocks, top_etfs, market_regime=None):
    """
    Envoie les signaux via Telegram.
    Respecte la limite de 1 message/seconde avec un délai de 1.5s.
    """
    token = CONFIG["telegram"]["bot_token"]
    chat_id = CONFIG["telegram"]["chat_id"]

    if not token or not chat_id or token.startswith("${"):
        logger.warning("Notifications Telegram désactivées (token ou chat_id manquant).")
        return

    bot = Bot(token=token)

    # 1. Envoi du Header
    header = f"📊 <b>ValueMomentum Scanner — {datetime.now().strftime('%Y-%m-%d')}</b>\n"
    
    # Alerte Régime de Marché si Stress Majeur
    if market_regime and market_regime.get("status") == "Stress Majeur":
        header += "🚨 <b>RÉGIME DE PANIQUE : EXPOSITION DÉCONSEILLÉE</b>\n"
        header += f"<i>SPY < EMA 200 et VIX ({market_regime.get('vix', 0):.1f}) > 25</i>\n"
    
    header += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n🏆 <b>TOP ACTIONS DU JOUR</b>"
    await bot.send_message(chat_id=chat_id, text=header, parse_mode="HTML")
    await asyncio.sleep(1.5)

    # 2. Envoi des Stocks (un par un)
    for i, (_, row) in enumerate(top_stocks.iterrows()):
        symbol = row["symbol"]
        name = escape_html(row.get("name", symbol))
        score = int(row["score_global"])

        msg = f"#{i+1} 📈 <b>{name}</b> (${symbol})\n"
        msg += f"Score Global : {score}/100\n"
        msg += f"├ Qualité     : {int(row['score_quality'])}/100\n"
        msg += f"├ Valorisation: {int(row['score_valuation'])}/100\n"
        msg += f"└ Momentum    : {int(row['score_momentum'])}/100\n\n"
        
        msg += f"📈 Perf 6M : {row.get('perf_6m', 0):.1%} vs secteur {row.get('outperf_6m', 0):+.1%}\n"
        msg += f"💰 P/E Fwd : {row.get('pe', 0):.1f} | ROE : {row.get('roe', 0):.1%}\n"
        msg += f"🏢 {row.get('sector', 'Unknown')} | Cap : ${row.get('mcap_b', 0):.1f}B\n"
        
        if "earnings_date" in row and row["earnings_date"]:
            msg += f"📅 <b>Earnings : {row['earnings_date']}</b>\n"
        
        if "warning" in row and row["warning"]:
            msg += f"⚠️ {row['warning']}\n"

        msg += f"🔗 <a href='https://finance.yahoo.com/quote/{symbol}'>Yahoo Finance</a>"

        try:
            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML", disable_web_page_preview=True)
            await asyncio.sleep(1.5)
        except Exception as e:
            logger.error(f"Erreur envoi Telegram pour {symbol}: {e}")

    # 3. Envoi des ETFs
    if not top_etfs.empty:
        etf_header = "━━━━━━━━━━━━━━━━━━━━━━━━━━\n📦 <b>TOP ETFs DU JOUR</b>"
        await bot.send_message(chat_id=chat_id, text=etf_header, parse_mode="HTML")
        await asyncio.sleep(1.5)

        for i, (_, row) in enumerate(top_etfs.iterrows()):
            symbol = row["symbol"]
            score = int(row["score_global"])
            msg = f"#{i+1} <b>{symbol}</b>\n"
            msg += f"Score : {score}/100 | Perf 6M : {row['perf_6m']:.1%}\n"
            msg += f"🔗 <a href='https://finance.yahoo.com/quote/{symbol}'>Yahoo Finance</a>"
            
            try:
                await bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML", disable_web_page_preview=True)
                await asyncio.sleep(1.5)
            except Exception as e:
                logger.error(f"Erreur envoi Telegram pour {symbol}: {e}")

async def notify(top_stocks, top_etfs, market_regime=None):
    """Envoi des signaux via Telegram (Asynchrone)."""
    if top_stocks.empty and top_etfs.empty:
        return
    await send_telegram_signals(top_stocks, top_etfs, market_regime)
