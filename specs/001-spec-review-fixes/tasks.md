---
description: "Task list for ValueMomentum Scanner V1 — Spec Review Fixes"
---

# Tasks: ValueMomentum Scanner V1 — Spec Review Fixes

**Input**: Design documents from `specs/001-spec-review-fixes/`

**Branch**: `001-spec-review-fixes`

**Scope**: 4 bugs bloquants + 9 lacunes constitution v1.1.0 + suite de tests hermétique (VCR + Freezegun)

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Parallélisable (fichiers différents, sans dépendances actives)
- **[Story]**: User story cible (US1–US4)
- Tests requis explicitement (SC-005 + plan Phase 6)

---

## Phase 1: Setup

**Purpose**: Infrastructure minimale avant tout travail

- [x] T001 Créer `tests/cassettes/.gitkeep` (répertoire VCR obligatoire — sans lui, `@pytest.mark.vcr` fait des appels API live)

---

## Phase 2: Foundational (Bugs bloquants + Config)

**Purpose**: Prérequis durs — bloquent toutes les user stories

**⚠️ CRITIQUE**: Aucun travail US ne peut commencer avant completion de cette phase

- [x] T002 Corriger Bug 1 — renommer `regime` → `market_regime` dans `main.py:107` (NameError : aucune notification Telegram jamais envoyée)
- [x] T003 Corriger Bug 2 — remplacer `"totalCash": k.get("netDebtTTM")` par `"totalCash": None` dans `scanner/fetcher.py` (Net Debt ≠ Total Cash, corrompt debt/EBITDA)
- [x] T004 Corriger Bug 3 — remplacer `.head(50)` par `.head(CONFIG["scanner"]["shortlist_size"])` dans `main.py:78` (50×7=350 calls FMP → quota dépassé)
- [x] T005 Corriger Bug 4 — implémenter cascade VIX 4 niveaux dans `main.py` : panic (VIX>35) → prudence (SPY<EMA200 AND 25<VIX≤35) → bear_light (SPY<EMA200 AND VIX≤25) → normal
- [x] T006 Ajouter 8 constantes manquantes dans `config.yaml` sous `scanner:` : `shortlist_size: 30`, `vix_panic_threshold: 35`, `vix_warning_threshold: 25`, `max_workers_universe: 4`, `fmp_max_retries: 2`, `min_universe_size: 100`, `telegram_max_chars: 4096`, `min_tickers_intra_sector: 3` (Lacune 12)
- [x] T007 Mettre à jour `scanner/universe.py` : lire `CONFIG["scanner"]["max_workers_universe"]` au lieu de `CONFIG["scanner"].get("max_workers", 8)` (Lacune 12, dépend de T006)

**Checkpoint**: 4 bugs corrigés, config alignée — implémentation US peut démarrer

---

## Phase 3: User Story 1 — Scan quotidien avec signaux Telegram (Priority: P1) 🎯 MVP

**Goal**: Scan s'exécute complètement, 7 endpoints FMP par ticker, budget ≤ 250 calls, messages Telegram tronqués et sécurisés

**Independent Test**: `python main.py --now` → réception Telegram avec Top 10 stocks + Top 5 ETFs, `score_global` non-NaN sur tous

### Implementation US1

- [x] T008 [P] [US1] Définir `FMPUnavailableError(Exception)` dans `scanner/fetcher.py` (Lacune 13 — exception dédiée pour propagation async propre)
- [x] T009 [US1] Ajouter endpoint `analyst-estimates/{symbol}?period=quarter&limit=3` comme 7ème appel FMP dans `scanner/fetcher.py` : extraire `estimatedEpsAvg` des 3 dernières périodes (Lacune 5, dépend de T008)
- [x] T010 [P] [US1] Implémenter `compute_analyst_revision_3m(estimates: list) -> float | None` dans `scanner/scoring/momentum.py` : `(current_eps - prev_eps) / abs(prev_eps)`, retourner `None` si < 2 périodes ou EPS absent (Lacune 5)
- [x] T011 [US1] Mettre à jour `momentum_subweights` dans `config.yaml` : `perf_6m: 0.30`, `outperf_6m: 0.30`, `perf_3m: 0.15`, `surprise_earnings: 0.15`, `analyst_revision: 0.10` (Lacune 5)
- [x] T012 [US1] Intégrer `analyst_revision_3m` dans le ranking momentum de `scanner/scoring/engine.py` avec le poids `analyst_revision` de config (Lacune 5, dépend de T010, T011)
- [x] T013 [US1] Implémenter `compute_momentum_weights(surprise_date, base_weights, today) -> dict` dans `scanner/scoring/engine.py` : décroissance linéaire `effective_surprise = w["surprise_earnings"] * max(0.0, 1.0 - days_since/90)`, redistribution freed vers autres critères proportionnellement (Lacune 6, Freezegun obligatoire en test)
- [x] T014 [P] [US1] Implémenter `truncate_message(msg: str, max_chars: int = None) -> str` dans `scanner/notifier.py` : lire `CONFIG["scanner"]["telegram_max_chars"]`, tronquer avec suffix `\n[message tronqué]` (Lacune 10)
- [x] T015 [US1] Appliquer `truncate_message()` à tous les arguments `text=` de `bot.send_message()` dans `scanner/notifier.py` (Lacune 10, dépend de T014)
- [x] T016 [P] [US1] Ajouter `notify_fmp_unavailable()` dans `scanner/notifier.py` : message HTML `⚠️ Sniper FMP indisponible` avec `truncate_message()` (Lacune 9, dépend de T014)
- [x] T017 [US1] Dans `scanner/fetcher.py` `fetch_all_data()` : catcher `FMPUnavailableError` → appeler `notify_fmp_unavailable()` → re-raise (Lacune 13, dépend de T008, T016)
- [x] T018 [US1] Dans `main.py` : wrapper l'appel `fetch_all_data()` dans try/except `FMPUnavailableError` → `return` (Lacune 13, dépend de T008)

**Checkpoint**: US1 testable indépendamment — scan complet, budget FMP respecté, Telegram reçu

---

## Phase 4: User Story 2 — Filtre de régime marché (Priority: P1)

**Goal**: 4 régimes détectés correctement, panic stoppe le scan et notifie, prudence flag chaque signal

**Independent Test**: Mocks SPY/VIX aux 4 niveaux → comportement exact vérifié (scan annulé, flag Telegram, log seul, scan normal)

### Implementation US2

- [x] T019 [P] [US2] Ajouter `notify_panic(vix: float, spy: float, ema200: float)` dans `scanner/notifier.py` : message HTML `🚨 RÉGIME DE PANIQUE — SCAN ANNULÉ` avec VIX et SPY vs EMA200, `truncate_message()` (Lacune 9, dépend de T014)
- [x] T020 [US2] Dans `main.py` : après détection `market_regime == "panic"`, appeler `save_scan_entry(market_data)` puis `await notify_panic(...)` puis `return` — 0 signal émis (Lacune 9, dépend de T005, T019)
- [x] T021 [US2] Corriger condition régime dans `scanner/notifier.py` : remplacer `market_regime.get("status") == "Stress Majeur"` par `market_regime == "prudence"` (Lacune 9 — string fix)

**Checkpoint**: US2 testable indépendamment — panic coupe proprement, prudence flag visible sur chaque signal

---

## Phase 5: User Story 3 — Entonnoir qualité données (Priority: P2)

**Goal**: sector=None exclu avec log, univers < 100 tickers coupe le scan, secteur < 3 tickers bascule cross-universe

**Independent Test**: Injecter tickers avec données manquantes/vieilles/secteur=None → exclusions correctes avec logs `sector_missing`, `universe_too_small`

### Implementation US3

- [x] T022 [P] [US3] Dans `scanner/scoring/engine.py` `stock_scoring_pipeline()` : ajouter exclusion `if info.get("sector") is None: logger.warning(f"Exclusion {symbol}: sector=None (sector_missing)"); continue` (Lacune 7)
- [x] T023 [P] [US3] Dans `scanner/scoring/engine.py` avant percentile ranking : ajouter check `if len(scored_rows) < CONFIG["scanner"]["min_universe_size"]: logger.warning(f"universe_too_small ({len(scored_rows)} tickers)"); return pd.DataFrame()` (Lacune 8, dépend de T006)
- [x] T024 [US3] Dans `scanner/scoring/engine.py` : implémenter fallback intra-secteur — détecter secteurs avec `sector_counts < CONFIG["scanner"]["min_tickers_intra_sector"]`, utiliser ranking cross-universe pour ces tickers, peupler `use_cross_universe_ranking: True` (Lacune 8, dépend de T023)

**Checkpoint**: US3 testable indépendamment — filtres qualité données tracés dans logs, univers minimum garanti

---

## Phase 6: User Story 4 — Persistance et suivi de performance (Priority: P2)

**Goal**: Colonnes de retour en base, `first_seen_date` jamais réinitialisée, job 18h00 ET calcule return_30d/90d

**Independent Test**: 2 scans successifs → tables `scans` et `signals` SQLite avec `price_at_signal` non-null, `first_seen_date` conservée

### Implementation US4

- [x] T025 [US4] Dans `scanner/storage.py` : exécuter migration schema SQLite (try/except OperationalError par ALTER TABLE) pour 7 nouvelles colonnes : `first_seen_date TEXT`, `price_at_signal REAL`, `price_30d_later REAL`, `return_30d REAL`, `price_90d_later REAL`, `return_90d REAL`, `flags TEXT` (Lacune 11)
- [x] T026 [US4] Dans `scanner/storage.py` : implémenter `get_first_seen_date(conn, symbol) -> str | None` (SELECT depuis signals) et mettre à jour `save_signals()` pour `first_seen = get_first_seen_date(conn, symbol) or today_str` (Lacune 11, dépend de T025)
- [x] T027 [P] [US4] Dans `scanner/storage.py` : implémenter `update_signal_returns()` async — requête signals avec `price_30d_later IS NULL AND first_seen_date <= date('now', '-30 days')`, fetch prix yfinance via `asyncio.to_thread`, calculer et stocker `return_30d` (Lacune 11, yfinance seul, 0 appel FMP)
- [x] T028 [US4] Dans `main.py` : enregistrer `update_signal_returns()` dans APScheduler à 18h00 ET (schedule secondaire quotidien) (Lacune 11, dépend de T027)

**Checkpoint**: US4 testable indépendamment — historique SQLite complet, track record calculable

---

## Phase 7: Tests (Après toutes les phases ci-dessus)

**Purpose**: Suite hermétique — 0 appel API live, temporalité deterministe

**⚠️ Tests requis explicitement**: SC-005 + plan Phase 6 — VCR cassettes + Freezegun obligatoires

### Tests unitaires — `tests/test_logic.py`

- [x] T029 [P] Écrire `test_market_gate_panic_vix_over_35` : VIX=40, SPY above EMA200 → `market_regime == "panic"` [US2]
- [x] T030 [P] Écrire `test_market_gate_panic_regardless_spy` : VIX=36, SPY below EMA200 → `market_regime == "panic"` [US2]
- [x] T031 [P] Écrire `test_market_gate_prudence` : VIX=30, SPY < EMA200 → `market_regime == "prudence"` [US2]
- [x] T032 [P] Écrire `test_market_gate_bear_light` : VIX=20, SPY < EMA200 → `market_regime == "bear_light"` [US2]
- [x] T033 [P] Écrire `test_market_gate_normal` : VIX=15, SPY ≥ EMA200 → `market_regime == "normal"` [US2]
- [x] T034 [P] Écrire `test_sector_none_exclusion` : `sector=None` → ticker exclu, log contient `"sector_missing"` [US3]
- [x] T035 [P] Écrire `test_earnings_decay_expired` : `surprise_date = today-91d` (Freezegun) → `effective_surprise == 0.0` [US1]
- [x] T036 [P] Écrire `test_earnings_decay_partial` : `surprise_date = today-45d` (Freezegun) → `effective_surprise == base × 0.5` [US1]
- [x] T037 [P] Écrire `test_earnings_decay_fresh` : `surprise_date = today-5d` (Freezegun) → `effective_surprise == base_weight` (aucune décroissance) [US1]
- [x] T038 [P] Écrire `test_intra_sector_fallback` : secteur avec 2 tickers → `use_cross_universe_ranking == True` [US3]
- [x] T039 [P] Écrire `test_truncate_message` : string 5000 chars → `len(result) == 4096`, se termine par `"[message tronqué]"` [US1]
- [x] T040 [P] Écrire `test_first_seen_date_preserved` : AAPL jour1 → absent → jour5 → `first_seen_date == jour1` [US4]
- [x] T041 [P] Écrire `test_totalcash_none_after_fix` : réponse FMP mockée → `totalCash is None`, `netDebt` correctement mappé depuis `netDebtTTM` [US3]

### Tests d'intégration — `tests/test_integration_vcr.py`

- [x] T042 [P] Écrire `test_fmp_budget_counter` : mock 30-ticker Sniper (VCR cassette) → compter appels HTTP FMP → assert total ≤ 250 [US1]
- [x] T043 [P] Écrire `test_full_pipeline_panic_regime` : VIX=40 (mock SPY/VIX) → assert scan termine après `notify_panic()`, 0 rows dans `signals` [US2]
- [x] T044 [P] Écrire `test_fmp_unavailable_abort` : FMP répond 503 × 2 (VCR cassette) → `FMPUnavailableError` levée → `notify_fmp_unavailable()` appelé → 0 signals émis [US1]

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Aucune — démarre immédiatement
- **Foundational (Phase 2)**: Dépend de Phase 1 — **bloque toutes les user stories**
- **US1 (Phase 3)**: Dépend de Phase 2 — commence après les 4 bugs et config fixés
- **US2 (Phase 4)**: Dépend de Phase 2 — peut démarrer en parallèle avec US1 (fichiers distincts)
- **US3 (Phase 5)**: Dépend de Phase 2 — peut démarrer en parallèle avec US1/US2
- **US4 (Phase 6)**: Dépend de Phase 2 — peut démarrer en parallèle avec US1/US2/US3
- **Tests (Phase 7)**: Dépend de toutes les phases précédentes

### User Story Dependencies

- **US1 (P1)**: Après Phase 2 — aucune dépendance inter-story
- **US2 (P1)**: Après Phase 2 — dépend de T005 (cascade VIX en Phase 2)
- **US3 (P2)**: Après Phase 2 — aucune dépendance inter-story
- **US4 (P2)**: Après Phase 2 — aucune dépendance inter-story

### Parallel Opportunities (Phase 3–6 simultanés)

```
Phase 2 COMPLETE
    ├── Phase 3 (US1): T008, T010, T014, T016 parallélisables entre eux
    ├── Phase 4 (US2): T019 parallélisable avec Phase 3
    ├── Phase 5 (US3): T022, T023 parallélisables entre eux
    └── Phase 6 (US4): T027 parallélisable avec autres phases
Phase 7 (Tests): T029–T044 tous parallélisables entre eux
```

---

## Parallel Example: User Story 1

```bash
# Tâches parallèles dans US1 (fichiers distincts) :
Task T008: "Définir FMPUnavailableError dans scanner/fetcher.py"
Task T010: "compute_analyst_revision_3m dans scanner/scoring/momentum.py"
Task T014: "truncate_message dans scanner/notifier.py"

# Ensuite (dépendent des précédentes) :
Task T009: "analyst-estimates endpoint dans fetcher.py" (dépend T008)
Task T012: "intégrer analyst_revision_3m dans engine.py" (dépend T010, T011)
Task T015: "appliquer truncate_message à bot.send_message" (dépend T014)
Task T016: "notify_fmp_unavailable dans notifier.py" (dépend T014)
```

---

## Implementation Strategy

### MVP First (US1 + US2 — P1 uniquement)

1. Phase 1: Setup (T001)
2. Phase 2: Foundational — 4 bugs + config (T002–T007)
3. Phase 3: US1 — scan complet, budget FMP, Telegram (T008–T018)
4. Phase 4: US2 — market regime 4 niveaux (T019–T021)
5. **STOP et VALIDER**: `python main.py --now` → Telegram reçu en < 15 min, ≤ 250 calls FMP

### Incremental Delivery

1. Setup + Foundational → bugs bloquants éliminés
2. US1 + US2 → scan fonctionnel end-to-end (MVP !)
3. US3 → qualité données améliorée
4. US4 → track record SQLite opérationnel
5. Tests Phase 7 → suite hermétique validée

---

## Summary

| Phase        | Tâches    | User Story            | Priorité  |
| ------------ | --------- | --------------------- | --------- |
| Setup        | T001      | —                     | Immédiat  |
| Foundational | T002–T007 | 4 bugs + config       | Bloquant  |
| Phase 3      | T008–T018 | US1 Scan quotidien    | P1        |
| Phase 4      | T019–T021 | US2 Régime marché     | P1        |
| Phase 5      | T022–T024 | US3 Entonnoir qualité | P2        |
| Phase 6      | T025–T028 | US4 Persistance       | P2        |
| Tests        | T029–T044 | US1/US2/US3/US4       | Post-impl |

**Total**: 44 tâches | **MVP**: T001–T021 (21 tâches)

**Parallèles dans MVP**: T008, T010, T014, T016, T019 (Phase 3+4 simultanés sur fichiers distincts)
