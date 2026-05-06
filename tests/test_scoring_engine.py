from scanner.universe import load_universe
from scanner.fetcher import fetch_all_data
from scanner.scoring.engine import scoring_engine
from scanner.config import logger

def test_scoring():
    logger.info("Test du Scoring Engine...")
    universe = load_universe()
    stocks = universe.get("stocks", [])
    
    # On prend un échantillon plus large pour avoir des percentiles significatifs
    test_subset = stocks[:20]
    
    logger.info(f"Récupération des données pour {len(test_subset)} tickers...")
    all_data = fetch_all_data(test_subset)
    
    logger.info("Exécution du Scoring Engine...")
    ranked_df = scoring_engine(all_data)
    
    if not ranked_df.empty:
        logger.info(f"Top 5 Tickers:\n{ranked_df[['symbol', 'score_global', 'score_quality', 'score_valuation', 'score_momentum']].head(5)}")
    else:
        logger.warning("Aucun ticker n'a passé les filtres.")

if __name__ == "__main__":
    test_scoring()
