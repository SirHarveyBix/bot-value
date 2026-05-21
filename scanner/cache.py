import json
import os
import sqlite3
import contextlib
from datetime import datetime, timedelta

from scanner.config import logger
from scanner.storage import DB_PATH, init_db


class CacheManager:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
        # Unique source de vérité pour initialiser la DB et ses schémas
        init_db()

    @contextlib.contextmanager
    def _conn(self):
        """Context manager pour gérer la connexion SQLite avec busy_timeout anti-lock."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")  # Attend jusqu'à 5s en cas de lock concurrent
        try:
            yield conn
        finally:
            conn.close()

    def get(self, category, key, ttl_seconds):
        """Récupère une donnée du cache si elle n'est pas expirée."""
        try:
            with self._conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT data, fetched_at FROM api_cache WHERE category = ? AND key = ?",
                    (category, key),
                )
                row = cursor.fetchone()

            if not row:
                return None

            data_str, fetched_at_str = row
            fetched_at = datetime.fromisoformat(fetched_at_str)
            if datetime.now() - fetched_at > timedelta(seconds=ttl_seconds):
                return None

            return json.loads(data_str)
        except Exception as e:
            logger.error(f"Erreur lecture cache {category}:{key} - {e}")
            return None

    def set(self, category, key, data):
        """Enregistre une donnée dans le cache."""
        try:
            data_str = json.dumps(data)
            fetched_at_str = datetime.now().isoformat()
            with self._conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO api_cache (category, key, fetched_at, data) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(category, key) DO UPDATE SET fetched_at = excluded.fetched_at, data = excluded.data",
                    (category, key, fetched_at_str, data_str),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Erreur écriture cache {category}:{key} - {e}")


# Instance globale
cache = CacheManager()

