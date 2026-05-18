# Research: ValueMomentum Scanner V1

**Branch**: `001-spec-review-fixes` | **Date**: 2026-05-19

## Architecture Decisions

### Decision 1 — Aucune nouvelle dépendance

**Decision**: Toutes les 13 issues sont corrigibles avec le set de dépendances existant.  
**Rationale**: `analyst-estimates` est accessible via l'`httpx.AsyncClient` déjà présent. La décroissance earnings est du Python arithmétique pur. La conservation `first_seen_date` est un SELECT-before-INSERT SQL standard.  
**Alternatives considérées**: Ajouter `aiohttp` pour les requêtes FMP — rejeté (httpx déjà présent, même API async, pas de valeur ajoutée).

---

### Decision 2 — FMP `analyst-estimates` = 7ème endpoint

**Decision**: Ajouter l'endpoint `analyst-estimates` comme 7ème appel FMP par ticker.  
**Rationale**: Budget = 7 × 30 = 210 calls nominaux. La spec originale budgétisait 7 endpoints mais le code n'en implémentait que 6. Ajouter le 7ème restore le design intentionnel sans dépasser le quota.  
**Alternatives considérées**: Intégrer la révision dans l'endpoint `earnings-surprises` — rejeté (données différentes, endpoint différent, sémantique distincte).

---

### Decision 3 — `FMPUnavailableError` comme exception custom

**Decision**: Exception dédiée pour propager l'indisponibilité FMP à travers la stack async.  
**Rationale**: Plus propre que des flags booléens ou des valeurs de retour sentinelles. Permet à `main.py` de catcher explicitement sans coupler `fetcher.py` à `notifier.py`.  
**Alternatives considérées**: Retourner `None` depuis `fetch_all_data()` — rejeté (None est ambigu, masque la distinction entre "ticker sans données" et "FMP totalement down").

---

### Decision 4 — Earnings decay per-row dans `engine.py`

**Decision**: Calcul des poids momentum en boucle per-ticker, pas vectorisé avec des poids fixes.  
**Rationale**: Chaque ticker a sa propre `surprise_date`. La redistribution des poids ne peut pas être faite au niveau DataFrame avec des poids constants dans `config.yaml`. Coût : ~30 itérations (négligeable).  
**Alternatives considérées**: Pré-calculer un weight moyen sur l'univers — rejeté (incorrect : efface la distinction temporelle individuelle entre tickers dont les earnings viennent de sortir vs il y a 80 jours).

---

### Decision 5 — Schema migration via try/except sur ALTER TABLE

**Decision**: Utiliser `try/except sqlite3.OperationalError` pour chaque `ALTER TABLE ADD COLUMN`.  
**Rationale**: SQLite ne supporte pas `ADD COLUMN IF NOT EXISTS`. Le pattern try/except est idiomatique pour les déploiements SQLite locaux mono-nœud. Pas d'Alembic justifié à cette échelle.  
**Alternatives considérées**: Drop & recreate table — rejeté (perte de données historiques). Alembic — rejeté (overkill pour Mac Mini local, ajoute une dépendance).

---

### Decision 6 — Renommage `max_workers` → `max_workers_universe`

**Decision**: Renommer la clé config et aligner la valeur à 4.  
**Rationale**: `universe.py` lit `CONFIG["scanner"].get("max_workers", 8)` — la clé est `max_workers: 2` dans config.yaml, donc le code ne trouvait pas la clé et utilisait le défaut 8. Le rename `max_workers_universe: 4` aligne clé config et lecture code, supprime le défaut silencieux de 8 workers (risque ban yfinance), et clarifie la portée.  
**Alternatives considérées**: Garder `max_workers` et corriger la valeur à 4 — rejeté (ambigüité sur la portée de la concurrence reste entière).

---

## Risques Résiduels

| Risque                                              | Probabilité                             | Mitigation                                                         |
| --------------------------------------------------- | --------------------------------------- | ------------------------------------------------------------------ |
| yfinance `.info` rate-limit avec max_workers=4      | Faible (4 req/s avec jitter)            | Jitter 0.8–1.5s par worker. Réduire à 2 si 429 observés            |
| FMP `analyst-estimates` indisponible pour un ticker | Modérée (~10-15% des tickers)           | `None` retourné → critère exclu → redistribution poids (spec §4.1) |
| APScheduler 4.x alpha breaking change               | Faible (usage limité à un add_schedule) | Pin exact version dans requirements.txt                            |
| Cassettes VCR périmées après mise à jour yfinance   | Modérée (yfinance change souvent)       | Documenter procédure de re-record dans CONTRIBUTING                |
