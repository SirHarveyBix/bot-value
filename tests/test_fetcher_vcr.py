import pytest
from scanner.config import logger
from scanner.fetcher import fetch_all_data

@pytest.mark.asyncio
@pytest.mark.vcr
async def test_fetcher_vcr():
    """Test du fetcher avec VCR pour ne pas consommer l'API FMP."""
    logger.info("Test du Data Fetcher (Hermétique via VCR)...")
    test_tickers = ["AAPL", "MSFT"]

    results = await fetch_all_data(test_tickers)

    for symbol, data in results.items():
        if symbol in test_tickers:
            info_ok = data.get("info") is not None
            prices_ok = data.get("prices") is not None and not data["prices"].empty
            assert prices_ok, f"Les prix pour {symbol} devraient être présents dans la cassette"
            if info_ok:
                assert data["info"].get("symbol") == symbol
