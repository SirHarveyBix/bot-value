import argparse
import asyncio
import sqlite3
from datetime import datetime

import pandas_market_calendars as mcal
from apscheduler import AsyncScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone

import scanner.fetcher as _fetcher
from scanner.config import CONFIG, logger
from scanner.fetcher import SECTOR_ETFS, FMPUnavailableError, fetch_all_data, fetch_market_indices, fetch_prices_batch
from scanner.filters import cap_sector_shortlist, check_batch_data_ratio, check_data_ratio, filter_post_scoring
from scanner.market_gate import MarketRegime, evaluate_market_regime
from scanner.notifier import (
    notify,
    notify_exclusions,
    notify_fmp_unavailable,
    notify_panic,
    notify_vix_unavailable,
    notify_yfinance_ban,
    poll_telegram_commands,
)
from scanner.scoring.engine import (
    compute_inverse_vol_weights,
    etf_scoring_pipeline,
    momentum_screening_pipeline,
    stock_scoring_pipeline,
)
from scanner.storage import (
    DB_PATH,
    export_signals_json,
    get_first_seen_dates_batch,
    reconstruct_portfolio_and_maturation,
    save_scanned_universe,
    save_signals,
    update_portfolio_flags,
    update_signal_returns,
)
from scanner.universe import build_eligible_universe, load_universe

_scanner_lock = asyncio.Lock()


def is_market_open():
    """Vérifie si le NYSE est ouvert aujourd'hui."""
    nyse = mcal.get_calendar("NYSE")
    today = datetime.now().date()
    schedule = nyse.schedule(start_date=today, end_date=today)
    return not schedule.empty


async def run_scanner(force=False):
    """Fonction principale du job de scan (asynchrone)."""
    logger.info("Déclenchement du scan quotidien...")

    # Reset disjoncteur FMP à chaque scan
    _fetcher.fmp_call_counter = 0

    if not force and not is_market_open():
        logger.info("Le marché NYSE est fermé aujourd'hui. Scan annulé (utilisez --force pour passer outre).")
        return

    if _scanner_lock.locked():
        logger.warning("Scan déjà en cours — appel ignoré (double-déclenchement scheduler/Telegram).")
        return

    await _scanner_lock.acquire()
    try:
        # 0. Market Gate : VIX-priority 4-level cascade
        market_history = await fetch_market_indices()
        regime = MarketRegime.NORMAL
        current_spy = None
        ema200 = None
        current_vix = None

        if not market_history.empty:
            try:
                spy_close = market_history["Close"]["SPY"]
                vix_close = market_history["Close"]["^VIX"]
            except KeyError:
                logger.error("SPY ou ^VIX absent du téléchargement market — scan annulé.")
                await notify_vix_unavailable()
                return

            spy_valid = spy_close.replace(0, float("nan")).dropna()
            vix_valid = vix_close.replace(0, float("nan")).dropna()

            if spy_valid.empty or vix_valid.empty:
                logger.error("VIX ou SPY indisponible (série vide après dropna) — scan annulé.")
                await notify_vix_unavailable()
                return

            ema200 = spy_valid.ewm(span=200, adjust=False).mean().iloc[-1].item()
            current_spy = spy_valid.iloc[-1].item()
            current_vix = vix_valid.iloc[-1].item()

            spy_std = float(spy_valid.std())
            if spy_std < 1.0:
                logger.error(
                    f"SPY série plate suspecte (std={spy_std:.4f}, price={current_spy:.2f}) — "
                    "yfinance a probablement retourné des données stale. Scan annulé."
                )
                await notify_vix_unavailable()
                return

            regime = evaluate_market_regime(current_vix, current_spy, ema200)
            logger.info(
                f"Market Gate: regime={regime.value} | SPY={current_spy:.2f} EMA200={ema200:.2f} VIX={current_vix:.1f}"
            )
        else:
            logger.error("Indices marché indisponibles (DataFrame vide) — scan annulé.")
            await notify_vix_unavailable()
            return

        market_regime = regime.value

        if regime == MarketRegime.PANIC:
            logger.info(
                "Market Gate: VIX > 35 (PANIC). Le scan complet continue en mode silencieux et persistera les signaux en base."
            )

        # 1. Universe Builder
        universe = load_universe()
        initial_stocks = universe.get("stocks", [])
        initial_etfs = universe.get("etfs", [])

        # 2. Filtrage éligibilité pour les stocks
        eligible_stocks = build_eligible_universe(initial_stocks)

        # MIN_UNIVERSE_SIZE check sur l'univers complet post-chalutier (spec §Table constantes)
        min_universe_size = CONFIG["scanner"]["min_universe_size"]
        if len(eligible_stocks) < min_universe_size:
            logger.error(
                f"universe_too_small : {len(eligible_stocks)} tickers éligibles < {min_universe_size}. Scan annulé."
            )
            return

        # 3. Le Chalutier : prix stocks + ETFs sectoriels (sector outperformance + ETF scoring)
        etf_tickers = list(dict.fromkeys(initial_etfs + list(SECTOR_ETFS)))
        price_data = await fetch_prices_batch(eligible_stocks + etf_tickers)

        if not check_batch_data_ratio(price_data, len(eligible_stocks) + len(etf_tickers)):
            logger.error("Scan interrompu : trop d'échecs lors du batch download.")
            await notify_yfinance_ban()
            return

        # 4. Premier Screening : Momentum uniquement
        momentum_ranked_df = momentum_screening_pipeline(price_data, eligible_stocks)
        # T004: Bug 3 fix — shortlist_size depuis config
        shortlist_stocks = cap_sector_shortlist(momentum_ranked_df, CONFIG["scanner"].get("shortlist_sector_cap", 5))

        logger.info(f"Shortlist de {len(shortlist_stocks)} tickers sélectionnés pour analyse approfondie.")

        # 5. Le Sniper : Fetch des fondamentaux complets uniquement pour la shortlist
        # T018: Catch FMPUnavailableError → return (Lacune 13)
        try:
            all_data = await fetch_all_data(shortlist_stocks, initial_etfs, prices_batch=price_data)
        except FMPUnavailableError:
            return

        if not check_data_ratio(all_data, len(shortlist_stocks)):
            logger.error("Scan interrompu : trop d'échecs lors du fetch des fondamentaux (Sniper).")
            await notify_fmp_unavailable()
            return

        # 6. Scoring Engine Complet
        exclusions: list[dict] = []
        ranked_stocks_df = stock_scoring_pipeline(all_data, shortlist_stocks, exclusions_out=exclusions)
        ranked_etfs_df = etf_scoring_pipeline(all_data, initial_etfs)

        # 7. Post-Scoring Filters
        top_10_stocks = await filter_post_scoring(ranked_stocks_df, all_data, exclusions_out=exclusions)
        if not top_10_stocks.empty:
            top_10_stocks = compute_inverse_vol_weights(top_10_stocks, all_data)
        top_5_etfs = ranked_etfs_df.head(5)

        # T049: Anti survivorship bias — stocker univers Chalutier complet
        scan_date_str = datetime.now().strftime("%Y-%m-%d")
        top10_symbols = top_10_stocks["symbol"].tolist() if not top_10_stocks.empty else []
        await save_scanned_universe(momentum_ranked_df, shortlist_stocks, top10_symbols, scan_date=scan_date_str)

        # 8. Storage
        market_data = {"regime": market_regime, "spy_price": current_spy, "spy_ema200": ema200, "vix": current_vix}
        save_signals(top_10_stocks, top_5_etfs, all_data, len(eligible_stocks), market_data=market_data)
        export_signals_json(top_10_stocks, top_5_etfs, len(eligible_stocks), market_data=market_data)

        # Simulation du portefeuille, maturation et sorties
        portfolio: dict = {}
        exits_today: list = []
        try:

            def _reconstruct_sync():
                with sqlite3.connect(DB_PATH) as _conn:
                    return reconstruct_portfolio_and_maturation(_conn)

            portfolio, exits_today = await asyncio.to_thread(_reconstruct_sync)
        except Exception as _e:
            logger.warning(f"Impossible de reconstruire le portefeuille: {_e}")

        update_portfolio_flags(scan_date_str, portfolio, exits_today)

        # Gap 1: enrichir top_10_stocks avec first_seen_date depuis SQLite avant notify
        if not top_10_stocks.empty:
            first_seen_map = get_first_seen_dates_batch(top_10_stocks["symbol"].tolist(), scan_date_str)
            top_10_stocks = top_10_stocks.copy()
            top_10_stocks["first_seen_date"] = top_10_stocks["symbol"].map(first_seen_map)

        # 9. Notify — En cas de panique (VIX > 35), on envoie uniquement le message de crise (Silent Scan)
        # Sinon on envoie les signaux normaux enrichis du portefeuille et des sorties
        if regime == MarketRegime.PANIC:
            await notify_panic(current_vix, current_spy, ema200)
        else:
            await notify(
                top_10_stocks, top_5_etfs, market_regime=market_regime, portfolio=portfolio, exits_today=exits_today
            )
            if exclusions:
                await notify_exclusions(exclusions)

        if not top_10_stocks.empty:
            logger.info("TOP 5 STOCKS IDENTIFIED:")
            for _, row in top_10_stocks.head(5).iterrows():
                logger.info(f"- {row['symbol']} (Score: {int(row['score_global'])}/100)")

        logger.info("Scan quotidien terminé avec succès.")
    except Exception as e:
        logger.exception(f"Erreur critique lors du scan: {e}")
    finally:
        _scanner_lock.release()


async def test_telegram():
    """Envoie un message Telegram de test pour vérifier la configuration."""
    from scanner.notifier import _get_bot, send_message_safe

    bot, chat_id = _get_bot()
    if not bot:
        logger.error("Token Telegram manquant dans .env (TELEGRAM_BOT_TOKEN).")
        return
    logger.info(f"Test Telegram → chat_id={chat_id}")
    await send_message_safe(
        bot,
        chat_id,
        "✅ <b>ValueMomentum Scanner — test de connexion</b>\nTelegram opérationnel.",
        parse_mode="HTML",
    )
    logger.info("Message de test envoyé. Vérifiez Telegram.")


async def main():
    parser = argparse.ArgumentParser(description="ValueMomentum Scanner")
    parser.add_argument("--force", action="store_true", help="Force le scan même si le marché est fermé")
    parser.add_argument("--now", action="store_true", help="Lance le scan immédiatement et quitte")
    parser.add_argument("--test-telegram", action="store_true", help="Envoie un message Telegram de test et quitte")
    args = parser.parse_args()

    if args.test_telegram:
        await test_telegram()
        return

    if args.now or args.force:
        await run_scanner(force=args.force)
        if args.now:
            return

    logger.info("Démarrage du ValueMomentum Scanner (APScheduler 4.x Async Native)...")

    async with AsyncScheduler() as scheduler:
        tz = timezone("America/New_York")

        # Job principal : scan quotidien 09h35 ET
        await scheduler.add_schedule(
            run_scanner, trigger=CronTrigger(day_of_week="mon-fri", hour=9, minute=35, timezone=tz), id="daily_scan"
        )

        # T028: Job secondaire : mise à jour retours 18h00 ET (Lacune 11)
        await scheduler.add_schedule(
            update_signal_returns,
            trigger=CronTrigger(day_of_week="mon-fri", hour=18, minute=0, timezone=tz),
            id="update_returns",
        )

        logger.info("Scheduler configuré : scan 09h35 ET + retours 18h00 ET, lundi-vendredi.")

        # Commandes Telegram depuis le téléphone (/scan, /status, /help)
        telegram_task = asyncio.create_task(poll_telegram_commands(run_scanner))

        try:
            await scheduler.run_until_stopped()
        finally:
            telegram_task.cancel()
            try:
                await telegram_task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
