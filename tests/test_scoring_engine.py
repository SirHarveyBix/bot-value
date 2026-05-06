import pytest
from scanner.config import logger
import pandas as pd
from scanner.fetcher import fetch_all_data, fetch_prices_batch, fetch_spy_history
from scanner.scoring.engine import stock_scoring_pipeline, etf_scoring_pipeline
from scanner.storage import save_signals
from scanner.universe import load_universe

@pytest.mark.asyncio
async def test_scoring():
    logger.info("Test du Scoring Engine & SQLite...")
    
    # 0. Market Gate Simulation
    spy_history = await fetch_spy_history()
    assert not spy_history.empty
    spy_close = spy_history["Close"]
    ma200 = spy_close.rolling(window=200).mean().iloc[-1].item()
    current_spy = spy_close.iloc[-1].item()
    market_regime = "bull" if current_spy > ma200 else "bear"

    universe = load_universe()
    stocks = universe.get("stocks", [])[:10]
    etfs = universe.get("etfs", [])[:2]

    logger.info(f"Récupération des données...")
    all_data = await fetch_all_data(stocks, etfs)

    logger.info("Exécution du Scoring...")
    ranked_stocks = stock_scoring_pipeline(all_data, stocks)
    ranked_etfs = etf_scoring_pipeline(all_data, etfs)

    logger.info("Test de sauvegarde SQLite...")
    market_data = {
        "regime": market_regime,
        "spy_price": current_spy,
        "spy_ma200": ma200
    }
    save_signals(ranked_stocks.head(5), ranked_etfs.head(2), all_data, len(stocks), market_data=market_data)
    
    import os
    assert os.path.exists("data/signals/scanner_history.db")
    logger.info("✅ Base de données SQLite créée et alimentée.")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_scoring())
