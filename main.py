from datetime import datetime

import pandas_market_calendars as mcal
from apscheduler.schedulers.blocking import BlockingScheduler
from pytz import timezone

from scanner.config import logger
from scanner.fetcher import fetch_all_data
from scanner.filters import check_data_ratio, filter_post_scoring
from scanner.notifier import notify
from scanner.scoring.engine import etf_scoring_pipeline, stock_scoring_pipeline
from scanner.storage import save_signals
from scanner.universe import build_eligible_universe, load_universe


def is_market_open():
    """Vérifie si le NYSE est ouvert aujourd'hui."""
    nyse = mcal.get_calendar("NYSE")
    today = datetime.now().date()
    schedule = nyse.schedule(start_date=today, end_date=today)
    return not schedule.empty

def run_scanner():
    """Fonction principale du job de scan."""
    logger.info("Déclenchement du scan quotidien...")

    if not is_market_open():
        logger.info("Le marché NYSE est fermé aujourd'hui. Scan annulé.")
        return

    try:
        # 1. Universe Builder
        universe = load_universe()
        initial_stocks = universe.get("stocks", [])
        initial_etfs = universe.get("etfs", [])

        # 2. Filtrage éligibilité pour les stocks
        eligible_stocks = build_eligible_universe(initial_stocks)

        # 3. Fetcher (Stocks + ETFs + Sector ETFs)
        all_data = fetch_all_data(eligible_stocks, initial_etfs)

        # 4. Vérification du ratio de données (Section 13.3 des specs)
        if not check_data_ratio(all_data, len(eligible_stocks)):
            logger.error("Scan interrompu : ratio de données valides insuffisant.")
            return

        # 5. Scoring Engine
        ranked_stocks_df = stock_scoring_pipeline(all_data, eligible_stocks)
        ranked_etfs_df = etf_scoring_pipeline(all_data, initial_etfs)

        # 6. Post-Scoring Filters (Diversification + Freshness + Earnings)
        top_10_stocks = filter_post_scoring(ranked_stocks_df, all_data)
        top_5_etfs = ranked_etfs_df.head(5)

        # 7. Storage
        save_signals(top_10_stocks, top_5_etfs, all_data, len(eligible_stocks))

        # 8. Notify
        notify(top_10_stocks, top_5_etfs)

        logger.info("Scan quotidien terminé avec succès.")
    except Exception as e:
        logger.exception(f"Erreur critique lors du scan: {e}")

def main():
    logger.info("Démarrage du ValueMomentum Scanner Scheduler...")

    scheduler = BlockingScheduler()
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
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Arrêt du scheduler.")

if __name__ == "__main__":
    main()
