from scanner.universe import load_universe, build_eligible_universe
from scanner.config import logger

def test_universe():
    logger.info("Test de Universe Builder...")
    universe = load_universe()
    stocks = universe.get("stocks", [])
    
    # On teste sur les 5 premiers pour ne pas saturer yfinance tout de suite
    test_subset = stocks[:5]
    eligible = build_eligible_universe(test_subset)
    
    logger.info(f"Test terminé. Éligibles: {eligible}")

if __name__ == "__main__":
    test_universe()
