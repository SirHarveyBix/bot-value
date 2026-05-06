import argparse
import asyncio
from datetime import datetime

import pandas_market_calendars as mcal
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import timezone

from scanner.config import logger
from scanner.fetcher import fetch_all_data, fetch_prices_batch, fetch_spy_history
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
        # 0. Market Gate : Vérification de la tendance (SPY MA200)
        spy_history = await fetch_spy_history()
        market_regime = "unknown"
        if not spy_history.empty:
            spy_close = spy_history["Close"]
            ma200 = spy_close.rolling(window=200).mean().iloc[-1]
            current_spy = spy_close.iloc[-1]
            
            if current_spy < ma200:
                market_regime = "bear"
                logger.warning(f"🚨 MARCHÉ BAISSIER DÉTECTÉ (SPY {current_spy:.2f} < MA200 {ma200:.2f})")
            else:
                market_regime = "bull"
                logger.info(f"✅ MARCHÉ HAUSSIER (SPY {current_spy:.2f} > MA200 {ma200:.2f})")

        # 1. Universe Builder
        universe = load_universe()
        initial_stocks = universe.get("stocks", [])
        initial_etfs = universe.get("etfs", [])

        # 2. Filtrage éligibilité pour les stocks
        eligible_stocks = build_eligible_universe(initial_stocks)

        # 3. Le Chalutier : Fetch uniquement les prix pour tout l'univers éligible
        # C'est rapide et sans risque de rate-limit 429
        price_data = await fetch_prices_batch(eligible_stocks)

        # Vérification du ratio de données pour le batch
        if not check_batch_data_ratio(price_data, len(eligible_stocks)):
            logger.error("Scan interrompu : trop d'échecs lors du batch download.")
            return
        
        # 4. Premier Screening : Momentum uniquement
        # On calcule le momentum pour les ~700 tickers et on garde le Top 50
        momentum_ranked_df = momentum_screening_pipeline(price_data, eligible_stocks)
        shortlist_stocks = momentum_ranked_df.head(50)["symbol"].tolist()
        
        logger.info(f"Shortlist de {len(shortlist_stocks)} tickers sélectionnés pour analyse approfondie.")

        # 5. Le Sniper : Fetch des fondamentaux complets uniquement pour la shortlist
        # On passe price_data pour éviter de retélécharger les historiques de prix
        all_data = await fetch_all_data(shortlist_stocks, initial_etfs, prices_batch=price_data)

        # Vérification du ratio de données pour la shortlist (Sniper)
        if not check_data_ratio(all_data, len(shortlist_stocks)):
            logger.error("Scan interrompu : trop d'échecs lors du fetch des fondamentaux (Sniper).")
            return

        # 6. Scoring Engine Complet (Qualité + Valorisation + Momentum)
        # On ne score en profondeur que les 50 sélectionnés
        ranked_stocks_df = stock_scoring_pipeline(all_data, shortlist_stocks)
        ranked_etfs_df = etf_scoring_pipeline(all_data, initial_etfs)

        # 7. Post-Scoring Filters (Diversification + Freshness + Earnings)
        top_10_stocks = filter_post_scoring(ranked_stocks_df, all_data)
        top_5_etfs = ranked_etfs_df.head(5)

        # 7. Storage
        market_data = {
            "regime": market_regime,
            "spy_price": current_spy if not spy_history.empty else None,
            "spy_ma200": ma200 if not spy_history.empty else None
        }
        save_signals(top_10_stocks, top_5_etfs, all_data, len(eligible_stocks), market_data=market_data)

        # 8. Notify (Maintenant awaitable)
        await notify(top_10_stocks, top_5_etfs)

        # 9. Console Summary
        if not top_10_stocks.empty:
            logger.info("TOP 5 STOCKS IDENTIFIED:")
            for _, row in top_10_stocks.head(5).iterrows():
                logger.info(f"- {row['symbol']} (Score: {int(row['score_global'])}/100) | Q:{int(row['score_quality'])} V:{int(row['score_valuation'])} M:{int(row['score_momentum'])}")

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

    logger.info("Démarrage du ValueMomentum Scanner (AsyncIOScheduler)...")

    scheduler = AsyncIOScheduler()
    tz = timezone("America/New_York")

    scheduler.add_job(
        run_scanner,
        "cron",
        day_of_week="mon-fri",
        hour=9,
        minute=35,
        timezone=tz
    )

    logger.info("Scheduler configuré pour 09:35 ET, du lundi au vendredi.")
    scheduler.start()

    try:
        while True:
            await asyncio.sleep(1000)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Arrêt du scheduler.")

if __name__ == "__main__":
    asyncio.run(main())
