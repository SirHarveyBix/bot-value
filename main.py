import argparse
import asyncio
from datetime import datetime

import pandas_market_calendars as mcal
from apscheduler import AsyncScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone

from scanner.config import logger
from scanner.fetcher import fetch_all_data, fetch_market_indices, fetch_prices_batch
from scanner.filters import check_batch_data_ratio, check_data_ratio, filter_post_scoring
from scanner.notifier import notify
from scanner.scoring.engine import etf_scoring_pipeline, momentum_screening_pipeline, stock_scoring_pipeline
from scanner.storage import save_signals
from scanner.universe import build_eligible_universe, load_universe


def is_market_open():
    """Vérifie si le NYSE est ouvert aujourd'hui."""
    nyse = mcal.get_calendar("NYSE")
    today = datetime.now().date()
    schedule = nyse.schedule(start_date=today, end_date=today)
    return not schedule.empty

async def run_scanner(force=False):
    """Fonction principale du job de scan (asynchrone)."""
    logger.info("Déclenchement du scan quotidien...")

    if not force and not is_market_open():
        logger.info("Le marché NYSE est fermé aujourd'hui. Scan annulé (utilisez --force pour passer outre).")
        return

    try:
        # 0. Market Gate : EMA 200 + VIX (Section 4.0)
        market_history = await fetch_market_indices()
        market_regime = "unknown"
        current_spy = None
        ema200 = None
        current_vix = None

        if not market_history.empty:
            spy_close = market_history["Close"]["SPY"]
            vix_close = market_history["Close"]["^VIX"]

            ema200 = spy_close.ewm(span=200, adjust=False).mean().iloc[-1].item()
            current_spy = spy_close.iloc[-1].item()
            current_vix = vix_close.iloc[-1].item()

            # Règle de Stress : SPY < EMA 200 ET VIX > 25
            if current_spy < ema200 and current_vix > 25:
                market_regime = "stress"
                logger.warning(f"🚨 RÉGIME DE PANIQUE DÉTECTÉ (SPY {current_spy:.2f} < EMA200 {ema200:.2f} ET VIX {current_vix:.1f} > 25)")
            elif current_spy < ema200:
                market_regime = "bear_light"
                logger.info(f"⚠️ MARCHÉ SOUS EMA 200 (VIX {current_vix:.1f} calme) - Vigilance.")
            else:
                market_regime = "bull"
                logger.info(f"✅ MARCHÉ SAIN (SPY {current_spy:.2f} > EMA 200 {ema200:.2f})")

        # 1. Universe Builder
        universe = load_universe()
        initial_stocks = universe.get("stocks", [])
        initial_etfs = universe.get("etfs", [])

        # 2. Filtrage éligibilité pour les stocks
        eligible_stocks = build_eligible_universe(initial_stocks)

        # 3. Le Chalutier : Fetch uniquement les prix pour tout l'univers éligible
        price_data = await fetch_prices_batch(eligible_stocks)

        if not check_batch_data_ratio(price_data, len(eligible_stocks)):
            logger.error("Scan interrompu : trop d'échecs lors du batch download.")
            return
        
        # 4. Premier Screening : Momentum uniquement
        momentum_ranked_df = momentum_screening_pipeline(price_data, eligible_stocks)
        shortlist_stocks = momentum_ranked_df.head(50)["symbol"].tolist()
        
        logger.info(f"Shortlist de {len(shortlist_stocks)} tickers sélectionnés pour analyse approfondie.")

        # 5. Le Sniper : Fetch des fondamentaux complets uniquement pour la shortlist
        all_data = await fetch_all_data(shortlist_stocks, initial_etfs, prices_batch=price_data)

        if not check_data_ratio(all_data, len(shortlist_stocks)):
            logger.error("Scan interrompu : trop d'échecs lors du fetch des fondamentaux (Sniper).")
            return

        # 6. Scoring Engine Complet
        ranked_stocks_df = stock_scoring_pipeline(all_data, shortlist_stocks)
        ranked_etfs_df = etf_scoring_pipeline(all_data, initial_etfs)

        # 7. Post-Scoring Filters
        top_10_stocks = filter_post_scoring(ranked_stocks_df, all_data)
        top_5_etfs = ranked_etfs_df.head(5)

        # 8. Storage
        market_data = {
            "regime": market_regime,
            "spy_price": current_spy,
            "spy_ema200": ema200,
            "vix": current_vix
        }
        save_signals(top_10_stocks, top_5_etfs, all_data, len(eligible_stocks), market_data=market_data)

        # 9. Notify
        await notify(top_10_stocks, top_5_etfs, market_regime=regime)

        if not top_10_stocks.empty:
            logger.info("TOP 5 STOCKS IDENTIFIED:")
            for _, row in top_10_stocks.head(5).iterrows():
                logger.info(f"- {row['symbol']} (Score: {int(row['score_global'])}/100)")

        logger.info("Scan quotidien terminé avec succès.")
    except Exception as e:
        logger.exception(f"Erreur critique lors du scan: {e}")

async def main():
    parser = argparse.ArgumentParser(description="ValueMomentum Scanner")
    parser.add_argument("--force", action="store_true", help="Force le scan même si le marché est fermé")
    parser.add_argument("--now", action="store_true", help="Lance le scan immédiatement et quitte")
    args = parser.parse_args()

    if args.now or args.force:
        await run_scanner(force=args.force)
        if args.now:
            return

    logger.info("Démarrage du ValueMomentum Scanner (APScheduler 4.x Async Native)...")

    # APScheduler 4.x : AsyncScheduler est le point d'entrée direct
    async with AsyncScheduler() as scheduler:
        tz = timezone("America/New_York")
        
        # Configuration du trigger Cron
        trigger = CronTrigger(
            day_of_week="mon-fri",
            hour=9,
            minute=35,
            timezone=tz
        )

        # Ajout de l'horaire (schedule)
        await scheduler.add_schedule(
            run_scanner,
            trigger=trigger,
            id="daily_scan"
        )

        logger.info("Scheduler configuré pour 09:35 ET, du lundi au vendredi.")
        
        # Lancer le scheduler
        await scheduler.run_until_stopped()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
