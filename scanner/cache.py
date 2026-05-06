import json
import os
import time
from datetime import datetime, timedelta
from scanner.config import logger

class CacheManager:
    def __init__(self, cache_dir="data/cache"):
        self.cache_dir = cache_dir
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)

    def _get_path(self, category, key):
        return os.path.join(self.cache_dir, f"{category}_{key}.json")

    def get(self, category, key, ttl_seconds):
        """Récupère une donnée du cache si elle n'est pas expirée."""
        path = self._get_path(category, key)
        if not os.path.exists(path):
            return None

        try:
            with open(path, 'r') as f:
                entry = json.load(f)
            
            fetched_at = datetime.fromisoformat(entry["fetched_at"])
            if datetime.now() - fetched_at > timedelta(seconds=ttl_seconds):
                return None
            
            return entry["data"]
        except Exception as e:
            logger.error(f"Erreur lecture cache {category}:{key} - {e}")
            return None

    def set(self, category, key, data):
        """Enregistre une donnée dans le cache."""
        path = self._get_path(category, key)
        entry = {
            "fetched_at": datetime.now().isoformat(),
            "data": data
        }
        try:
            with open(path, 'w') as f:
                json.dump(entry, f)
        except Exception as e:
            logger.error(f"Erreur écriture cache {category}:{key} - {e}")

# Instance globale
cache = CacheManager()
