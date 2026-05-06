import pytest
from scanner.config import logger
from scanner.fetcher import fetch_all_data

@pytest.mark.asyncio
async def test_fetcher():
    logger.info("Test du Data Fetcher (Async)...")
    test_tickers = ["AAPL", "MSFT"]

    results = await fetch_all_data(test_tickers)

    for symbol, data in results.items():
        info_ok = data.get("info") is not None
        prices_ok = data.get("prices") is not None and not data["prices"].empty
        logger.info(f"Ticker {symbol}: Info={info_ok}, Prices={prices_ok}")
        if prices_ok:
            logger.info(f"Dernier prix pour {symbol}: {data['prices']['Close'].iloc[-1]}")
        
        assert prices_ok, f"Les prix pour {symbol} devraient être présents"

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_fetcher())
