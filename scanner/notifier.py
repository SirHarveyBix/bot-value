import asyncio
import html
from telegram import Bot
from scanner.config import CONFIG, logger

def escape_html(text):
    """Échappe les caractères spéciaux pour le mode HTML de Telegram."""
    return html.escape(str(text))

async def send_telegram_signals(top_stocks, top_etfs):
    """
    Envoie les signaux du top 10 via Telegram.
    """
    token = CONFIG["telegram"]["bot_token"]
    chat_id = CONFIG["telegram"]["chat_id"]
    
    if not token or not chat_id or token.startswith("${"):
        logger.warning("Notifications Telegram désactivées (token ou chat_id manquant).")
        return

    bot = Bot(token=token)
    
    header = f"📊 <b>ValueMomentum Scanner — {top_stocks.iloc[0].get('scan_date', '')}</b>\n"
    header += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n🏆 <b>TOP ACTIONS DU JOUR</b>\n\n"
    
    # On peut envoyer un message groupé ou individuel. 
    # Spec: 1 message par seconde max.
    
    full_message = header
    
    for i, (_, row) in enumerate(top_stocks.iterrows()):
        symbol = row["symbol"]
        name = escape_html(row.get("symbol")) # En v1 on n'a pas forcément le longName ici
        score = int(row["score_global"])
        
        msg = f"#{i+1} 📈 <b>{name}</b> (${symbol})\n"
        msg += f"Score Global : {score}/100\n"
        msg += f"├ Qualité     : {int(row['score_quality'])}/100\n"
        msg += f"├ Valorisation: {int(row['score_valuation'])}/100\n"
        msg += f"└ Momentum    : {int(row['score_momentum'])}/100\n"
        msg += f"🏢 Secteur : {row.get('sector', 'Unknown')}\n"
        msg += f"🔗 <a href='https://finance.yahoo.com/quote/{symbol}'>Yahoo Finance</a>\n\n"
        
        full_message += msg
        
    if not top_etfs.empty:
        full_message += "📦 <b>TOP ETFs DU JOUR</b>\n\n"
        for i, (_, row) in enumerate(top_etfs.iterrows()):
            symbol = row["symbol"]
            score = int(row["score_global"])
            full_message += f"#{i+1} <b>{symbol}</b> (Score: {score}/100 | Perf 6M: {row['perf_6m']:.1%})\n"
            full_message += f"🔗 <a href='https://finance.yahoo.com/quote/{symbol}'>Yahoo Finance</a>\n\n"

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=full_message,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info("Message Telegram envoyé avec succès.")
    except Exception as e:
        logger.error(f"Erreur envoi Telegram: {e}")

def notify(top_stocks, top_etfs):
    """Wrapper synchrone pour appeler l'envoi async."""
    if top_stocks.empty and top_etfs.empty:
        return
    asyncio.run(send_telegram_signals(top_stocks, top_etfs))
