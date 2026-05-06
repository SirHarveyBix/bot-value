import pytest
import os
import pandas as pd
from freezegun import freeze_time
from scanner.fetcher import fetch_all_data, fetch_market_indices
from scanner.scoring.engine import stock_scoring_pipeline
from scanner.storage import save_signals
from scanner.universe import load_universe

@pytest.mark.asyncio
@pytest.mark.vcr
async def test_full_pipeline_vcr():
    """
    Test d'intégration complet utilisant VCR.py pour l'isolation réseau.
    Simule une exécution un jour de bourse normal (mercredi 15 janv 2025).
    """
    with freeze_time("2025-01-15 10:00:00"):
        # 0. Market Gate
        market_history = await fetch_market_indices()
        assert not market_history.empty
        
        # 1. Universe
        universe = load_universe()
        stocks = universe.get("stocks", [])[:5] 
        
        # 2. Fetch
        all_data = await fetch_all_data(stocks)
        assert len(all_data) >= 5
        
        # 3. Scoring
        ranked_df = stock_scoring_pipeline(all_data, stocks)
        assert not ranked_df.empty
        
        # 4. Storage (WAL mode)
        market_data = {
            "regime": "bull",
            "spy_price": 500.0,
            "spy_ema200": 480.0,
            "vix": 15.0
        }
        save_signals(ranked_df.head(3), pd.DataFrame(), all_data, len(stocks), market_data=market_data)
        
        assert os.path.exists("data/signals/scanner_history.db")
