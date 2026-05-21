from unittest.mock import patch

import pytest

from scanner.config import logger
from scanner.fetcher import fetch_all_data

pytestmark = pytest.mark.asyncio

@pytest.mark.vcr
async def test_fetcher_vcr():
    """
    Test du fetcher avec VCR pour ne pas consommer l'API FMP.
    Skipé si pas de cassette VCR ou clé FMP absente.
    Le fallback yfinance a été supprimé en V1 (Lacune 13) — FMP obligatoire.
    """
    logger.info("Test du Data Fetcher (Hermétique via VCR)...")
    test_tickers = ["AAPL", "MSFT"]

    mock_info = {
        "symbol": "AAPL", "longName": "Apple Inc.", "sector": "Technology",
        "marketCap": 3_000_000_000_000, "source": "FMP",
        "surprise_pct": 0.0, "surprise_date": None, "analyst_revision_3m": None,
    }

    async def mock_fetch_ticker(symbol, client=None):
        return {**mock_info, "symbol": symbol}

    with patch("scanner.fetcher.fetch_ticker_info", side_effect=mock_fetch_ticker):
        results = await fetch_all_data(test_tickers)

    for symbol in test_tickers:
        assert symbol in results
        data = results[symbol]
        assert data.get("info") is not None
        assert data["info"]["symbol"] == symbol
