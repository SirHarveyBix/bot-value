"""Tests unitaires — scanner/cache.py (CacheManager, namespaces SQLite)."""

from unittest.mock import patch


def test_eligibility_namespace_isolated_from_fundamentals(tmp_path):
    """
    _check_single_ticker stocke sous 'eligibility', fetch_ticker_info lit sous
    'fundamentals'. Sans séparation : yfinance data → cache hit → FMP jamais
    appelé → roe_3y=None → tous les stocks exclus par le quality gate.
    """
    db_path = str(tmp_path / "cache.db")
    with patch("scanner.cache.DB_PATH", db_path), patch("scanner.storage.DB_PATH", db_path):
        from scanner.cache import CacheManager

        cache = CacheManager(db_path)
        yf_info = {"sector": "Technology", "marketCap": 1_000_000_000}
        cache.set("eligibility", "AAPL", yf_info)

        assert cache.get("fundamentals", "AAPL", 97200) is None
        assert cache.get("eligibility", "AAPL", 97200) == yf_info


def test_fmp_and_yfinance_namespaces_are_independent(tmp_path):
    """FMP sous 'fundamentals' et yfinance sous 'eligibility' ne se masquent pas."""
    db_path = str(tmp_path / "cache.db")
    with patch("scanner.cache.DB_PATH", db_path), patch("scanner.storage.DB_PATH", db_path):
        from scanner.cache import CacheManager

        cache = CacheManager(db_path)
        cache.set("fundamentals", "MSFT", {"roe_3y": 0.25, "source": "FMP"})
        cache.set("eligibility", "MSFT", {"sector": "Technology", "marketCap": 5e9})

        assert cache.get("fundamentals", "MSFT", 97200)["roe_3y"] == 0.25
        assert cache.get("eligibility", "MSFT", 97200)["sector"] == "Technology"


def test_cache_ttl_expires(tmp_path):
    """Une entrée expirée (ttl=0) retourne None."""
    db_path = str(tmp_path / "cache.db")
    with patch("scanner.cache.DB_PATH", db_path), patch("scanner.storage.DB_PATH", db_path):
        from scanner.cache import CacheManager

        cache = CacheManager(db_path)
        cache.set("fundamentals", "TSLA", {"roe_3y": 0.10})

        assert cache.get("fundamentals", "TSLA", 0) is None


def test_cache_upsert_overwrites(tmp_path):
    """SET sur clé existante → UPSERT, pas doublon."""
    db_path = str(tmp_path / "cache.db")
    with patch("scanner.cache.DB_PATH", db_path), patch("scanner.storage.DB_PATH", db_path):
        from scanner.cache import CacheManager

        cache = CacheManager(db_path)
        cache.set("fundamentals", "AAPL", {"roe_3y": 0.10})
        cache.set("fundamentals", "AAPL", {"roe_3y": 0.25})

        result = cache.get("fundamentals", "AAPL", 97200)
        assert result["roe_3y"] == 0.25
