from datetime import datetime

import pandas as pd
import yfinance as yf

from scanner.config import CONFIG, logger


def filter_post_scoring(df, all_data):
    """
    Applique les filtres de diversification sectorielle et enrichit avec l'earnings calendar.
    """
    if df.empty:
        return df

    # 1. Diversification sectorielle (Section 5.3)
    max_per_sector = CONFIG["scanner"].get("max_tickers_per_sector", 3)
    final_top_10 = []
    sector_counts = {}

    # On parcourt le df trié par score_global
    for _, row in df.iterrows():
        symbol = row["symbol"]
        sector = row.get("sector", "Unknown")
        count = sector_counts.get(sector, 0)

        if len(final_top_10) < 10:
            if count < max_per_sector:
                # 2. Data Freshness check
                info = all_data.get(symbol, {}).get("info", {})
                is_fresh, has_warning, warning_reason = data_freshness_check(info)

                if not is_fresh:
                    logger.warning(f"Ticker {symbol} exclu car données trop vieilles ({warning_reason})")
                    continue

                # 3. Earnings Calendar check (Section 5.2)
                row_copy = row.copy()
                earnings_date = earnings_calendar_check(symbol)
                if earnings_date:
                    row_copy["earnings_date"] = earnings_date

                if has_warning:
                    row_copy["warning"] = warning_reason

                final_top_10.append(row_copy)
                sector_counts[sector] = count + 1
            else:
                logger.debug(f"Ticker {row['symbol']} exclu du top 10 (limite secteur {sector} atteinte)")

    return pd.DataFrame(final_top_10)

def data_freshness_check(ticker_info):
    """
    Vérifie la fraîcheur des données fondamentales (Section 5.1).
    """
    if not ticker_info:
        return False, False, "No info"

    # yfinance 'lastFiscalYearEnd' ou 'mostRecentQuarter'
    last_update_ts = ticker_info.get("lastFiscalYearEnd") or ticker_info.get("mostRecentQuarter")
    if not last_update_ts:
        return True, True, "Date de mise à jour inconnue"

    last_update = datetime.fromtimestamp(last_update_ts)
    age_days = (datetime.now() - last_update).days

    max_age = CONFIG["scanner"].get("max_data_age_days", 180)
    warning_age = 120

    if age_days > max_age:
        return False, False, f"Données trop vieilles: {age_days} jours"

    if age_days > warning_age:
        return True, True, f"Données potentiellement périmées ({age_days} j)"

    return True, False, None

def earnings_calendar_check(symbol):
    """
    Récupère la prochaine date de résultats (Section 5.2).
    """
    try:
        ticker = yf.Ticker(symbol)
        calendar = ticker.calendar
        if calendar is None:
            return None

        dates = None
        if isinstance(calendar, dict):
            dates = calendar.get("Earnings Date", [])
        elif hasattr(calendar, "empty"):
            if calendar.empty:
                return None
            dates = calendar.get("Earnings Date", [])

        if dates:
            next_date = dates[0]
            delta = (next_date.date() - datetime.now().date()).days
            if 0 <= delta <= 14:
                return next_date.strftime("%Y-%m-%d")
        return None
    except Exception as e:
        logger.debug(f"Erreur earnings calendar pour {symbol}: {e}")
        return None

def check_batch_data_ratio(price_data, eligible_count):
    """
    Vérifie si le téléchargement par lot (Chalutier) a récupéré assez de données.
    """
    if eligible_count == 0:
        return False

    if isinstance(price_data.columns, pd.MultiIndex):
        valid_count = len(price_data.columns.levels[0])
    else:
        valid_count = 1 if not price_data.empty else 0

    ratio = valid_count / eligible_count
    min_ratio = CONFIG["scanner"].get("min_valid_data_ratio", 0.60)

    if ratio < min_ratio:
        logger.error(f"Ratio de prix batch trop faible: {ratio:.2%} (min {min_ratio:.0%})")
        return False
    return True

def check_data_ratio(all_data, eligible_count):
    """
    Vérifie si on a assez de données valides pour produire un rapport.
    """
    if eligible_count == 0:
        return False

    valid_count = sum(1 for d in all_data.values() if d.get("info") and not d["info"].get("error"))
    ratio = valid_count / eligible_count

    min_ratio = CONFIG["scanner"].get("min_valid_data_ratio", 0.60)
    if ratio < min_ratio:
        logger.error(f"Ratio de données valides trop faible: {ratio:.2%} (min {min_ratio:.0%})")
        return False
    return True

