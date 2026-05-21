from datetime import datetime

import pandas as pd
import yfinance as yf

from scanner.config import CONFIG, logger


def filter_post_scoring(df, all_data, exclusions_out: list | None = None):
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
                    if exclusions_out is not None:
                        exclusions_out.append({"symbol": symbol, "name": row.get("name", symbol), "gate": "fraîcheur", "reason": warning_reason})
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
                if exclusions_out is not None:
                    exclusions_out.append({"symbol": symbol, "name": row.get("name", symbol), "gate": "diversification", "reason": f"Plafond secteur {sector} ({max_per_sector} max)"})

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

    max_age = CONFIG["scanner"].get("data_freshness_exclusion_days", 200)
    warning_age = CONFIG["scanner"].get("data_freshness_warning_days", 120)

    if age_days >= max_age:
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


def sanity_check_gate(prices_df, symbol: str) -> bool:
    """
    Vérifie si le ticker présente des variations journalières anormales (baisse < -45% ou hausse > +50%).
    Utile pour écarter les anomalies de prix et les stock splits non ajustés.
    """
    if prices_df is None or prices_df.empty or "Close" not in prices_df.columns:
        return True

    # Calcul du rendement quotidien (daily returns)
    daily_returns = prices_df["Close"].pct_change().dropna()
    if daily_returns.empty:
        return True

    # Exclut si en dehors de [-45%, +50%]
    if (daily_returns < -0.45).any() or (daily_returns > 0.50).any():
        logger.warning(
            f"Sanity Check Gate: Ticker {symbol} exclu pour variation journalière anormale "
            f"(min: {daily_returns.min():.2%}, max: {daily_returns.max():.2%})"
        )
        return False
    return True
