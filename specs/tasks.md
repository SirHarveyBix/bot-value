# Tasks: ValueMomentum Scanner

**Input**: `specs/plan.md` · `specs/Spec_ValueMomentum_Scanner.md` · `specs/besoin.md`

**Format**: `- [ ] [ID] [P?] [Story?] Description avec chemin exact`
- **[P]** : parallélisable (fichiers différents, pas de dépendances incomplètes)
- **[USN]** : user story cible (US1–US5)
- Toutes les tâches incluent le chemin exact du fichier cible

---

## Phase 1 : Setup (Infrastructure partagée)

**Objectif** : Scaffolding projet + configuration + SQLite + scheduler vide fonctionnel

- [ ] T001 Créer `config.yaml` à la racine avec TOUTES les constantes métier : `SHORTLIST_SIZE: 30`, `FMP_CALL_BUDGET_HARD_LIMIT: 245`, `FMP_MAX_RETRIES: 2`, `YFINANCE_CHUNK_SIZE: 100`, `YFINANCE_CHUNK_DELAY_S: 2.0`, `CACHE_TTL_FUNDAMENTALS: 97200`, `CACHE_TTL_PRICE_HISTORY: 14400`, `VIX_PANIC_THRESHOLD: 35`, `VIX_WARNING_THRESHOLD: 25`, `MIN_UNIVERSE_SIZE: 100`, `TELEGRAM_MAX_CHARS: 4096`, `MAX_TICKERS_PER_SECTOR: 3`, `DATA_FRESHNESS_WARNING_DAYS: 120`, `DATA_FRESHNESS_EXCLUSION_DAYS: 180`, `EARNINGS_WINDOW_DAYS: 14`, `INTER_REQUEST_DELAY: 1.0`
- [ ] T002 [P] Créer `.env.example` à la racine avec placeholders : `TELEGRAM_BOT_TOKEN=`, `TELEGRAM_CHAT_ID=`, `FMP_API_KEY=`
- [ ] T003 [P] Créer/vérifier `requirements.txt` avec dépendances épinglées : `yfinance>=0.2.40,<0.3.0`, `pandas>=2.1.0,<3.0.0`, `numpy>=1.26.0,<2.0.0`, `apscheduler>=4.0.0a5`, `pandas-market-calendars>=4.3.0`, `python-telegram-bot>=21.0,<22.0`, `httpx>=0.27.0,<0.28.0`, `PyYAML>=6.0.1,<7.0.0`, `python-dotenv>=1.0.0,<2.0.0`, `loguru>=0.7.2,<1.0.0`, `pytest>=8.0.0`, `pytest-asyncio>=0.23.0`, `vcrpy`, `freezegun`, `supervisor>=4.2.0`
- [ ] T004 [P] Créer les packages Python vides : `scanner/__init__.py`, `scanner/scoring/__init__.py`
- [ ] T005 Implémenter `scanner/storage.py` : fonction `create_db(db_path)` → connexion SQLite, `PRAGMA journal_mode=WAL`, `CREATE TABLE IF NOT EXISTS scans`, `signals`, `scanned_universe`, `universe_metadata` (schémas complets §7.2 spec)
- [ ] T006 Créer `main.py` : chargement `config.yaml` + `.env`, init DB (`create_db()`), APScheduler 4.x `AsyncScheduler`, job `cron` lundi-vendredi 09h35 ET, vérification NYSE via `pandas_market_calendars`, log "Prochain scan : [date]"
- [ ] T007 [P] Créer `supervisord.conf` à la racine : `[program:scanner]` + `[program:web]` avec `%(here)s`, `TZ="America/New_York"`, `startretries=5`, logs vers `data/logs/`

**Checkpoint** : `python main.py` démarre sans erreur. `scanner_history.db` créée avec 4 tables + WAL. `supervisorctl status` retourne RUNNING.

---

## Phase 2 : Foundationnel (Prérequis bloquants)

**Objectif** : Universe builder, fetch OHLCV chunked, client FMP, Market Gate — BLOQUE toutes les user stories

⚠️ **CRITIQUE** : Aucune user story ne peut commencer avant la fin de cette phase

- [ ] T008 Créer `data/universe/tickers_universe.json` : clés `stocks` (S&P 500 + Nasdaq 100, ~600 tickers) et `etfs` (SPDR sectoriels : XLK, XLV, XLF, XLY, XLP, XLI, XLE, XLB, XLRE, XLU, XLC + autres ETFs majeurs)
- [ ] T009 Implémenter `scanner/universe.py` : `build_eligible_universe(tickers, prices_df)` → filtres éligibilité (marketCap > 2B$, volume_dollar_20j > 5M$, price > 5$, listing NYSE/NASDAQ/AMEX, ancienneté > 2 ans d'historique), retourne DataFrame des tickers éligibles
- [ ] T010 Implémenter `scanner/fetcher.py` : `fetch_prices_chunked(tickers, period)` → découpe en chunks `YFINANCE_CHUNK_SIZE`, `yf.download(..., threads=False)`, `asyncio.sleep(YFINANCE_CHUNK_DELAY_S)` entre chunks, log `batch_partial_failure` si chunk < 60% valides
- [ ] T011 [P] Implémenter `scanner/fetcher.py` : `FMPClient` (`httpx.AsyncClient`, `base_url`, `api_key`), jitter `random.uniform(0.8, 1.5)`, `FMP_MAX_RETRIES=2` avec backoff exponentiel, skip + flag si ticker échoue 2 fois
- [ ] T012 Implémenter `scanner/fetcher.py` : cache fondamentaux 27h (fichiers JSON `data/cache/{ticker}.json`, champs `fetched_at` + `expires_at`), invalidation forcée si ticker dans earnings calendar avec date = J-1
- [ ] T013 Implémenter `scanner/fetcher.py` : compteur global `fmp_call_counter = 0`, fonction `fmp_fetch(endpoint, symbol)` → incrémente counter, retourne `{}` + log warning si `fmp_call_counter >= FMP_CALL_BUDGET_HARD_LIMIT`
- [ ] T014 Ajouter check `MIN_UNIVERSE_SIZE` dans `main.py` après `build_eligible_universe()` et AVANT shortlisting : si `len(eligible) < 100` → log `universe_too_small`, envoyer alerte Telegram erreur, return sans scan

**Checkpoint** : `fetch_prices_chunked(700_tickers)` → 0 HTTP 429, data valide. `fmp_fetch()` → disjoncteur à 245. Cache 27h créé et relu correctement.

---

## Phase 3 : User Story 2 — Filtre de régime marché (Priorité : P1)

**Objectif** : Market Gate 4 niveaux opérationnel, scan annulé en Panique, flags sur signaux en Prudence

**Test indépendant** : `python main.py --now --dry-run` avec mocks VIX=40 → aucun signal, 1 entrée `scans` regime='panic', message Telegram 🚨

- [ ] T015 [US2] Créer `scanner/market_gate.py` : enum `MarketRegime(PANIC, CAUTION, BEAR_LIGHT, NORMAL)`
- [ ] T016 [US2] Implémenter `evaluate_market_regime(vix: float, spy_price: float, spy_ema200: float) -> MarketRegime` dans `scanner/market_gate.py` : cascade first-match (VIX > 35 → PANIC, SPY < EMA200 AND VIX ∈ [25,35] → CAUTION, SPY < EMA200 AND VIX ≤ 25 → BEAR_LIGHT, else NORMAL)
- [ ] T017 [P] [US2] Implémenter `fetch_market_indicators() -> dict` dans `scanner/fetcher.py` : fetch `^VIX` (yfinance) + SPY 1 an OHLCV, calcul EMA200 (`ewm(span=200)`), retourne `{vix, spy_price, spy_ema200}`
- [ ] T018 [US2] Intégrer Market Gate dans `main.py` : appel `evaluate_market_regime()` avant tout scoring → PANIC : écrire `scans(regime='panic')`, envoyer `send_panic_alert()`, return; CAUTION : stocker flag pour injection dans signaux
- [ ] T019 [US2] Créer `scanner/notifier.py` (placeholder complet) : `send_panic_alert(vix, spy, ema200)`, `send_fmp_error(cause)`, `send_system_error(module, msg)` — HTML parse_mode, `html.escape()` sur tous les strings, truncation 4096
- [ ] T020 [P] [US2] Test `tests/test_logic.py` (Freezegun) scénario PANIC : VIX=40.0, SPY > EMA200 → `evaluate_market_regime()` retourne PANIC
- [ ] T021 [P] [US2] Test scénario CAUTION : VIX=30.0, SPY < EMA200 → CAUTION
- [ ] T022 [P] [US2] Test scénario BEAR_LIGHT : VIX=20.0, SPY < EMA200 → BEAR_LIGHT
- [ ] T023 [P] [US2] Test scénario NORMAL : VIX=20.0, SPY ≥ EMA200 → NORMAL

**Checkpoint** : 4 tests Freezegun passent. Panique → 1 entrée `scans`, 0 entrée `signals`, message Telegram `🚨 RÉGIME DE PANIQUE`. VIX=36 + SPY > EMA200 → PANIC (VIX prime EMA200).

---

## Phase 4 : User Story 1 — Scan quotidien avec signaux Telegram (Priorité : P1) 🎯 MVP

**Objectif** : Pipeline complet opérationnel — Chalutier → Sniper → Scoring 3 piliers → Top 10 Telegram

**Test indépendant** : `python main.py --now --force` → réception Telegram Top 10 actions, scores non-nuls, budget FMP ≤ 245 calls

- [ ] T024 [US1] Implémenter `fetch_fmp_fundamentals(ticker) -> dict` dans `scanner/fetcher.py` : 7 endpoints séquentiels (`ratios-ttm`, `key-metrics-ttm`, `profile`, `income-statement?limit=3`, `balance-sheet-statement?limit=1`, `earnings-surprises`, `analyst-estimates`), incrémente `fmp_call_counter` × 7
- [ ] T025 [US1] Créer `scanner/scoring/quality.py` : `calculate_quality_metrics(ticker_info) -> dict` → `roe_3y` (moyenne ROE 3 bilans annuels FMP, jamais TTM ni yfinance), `operating_margin` (`operatingProfitMarginTTM`), `fcf_yield` (`freeCashFlowTTM / marketCap`), `debt_ebitda` (`netDebt / ebitda`)
- [ ] T026 [US1] Implémenter `apply_quality_gates(metrics, ticker_info) -> tuple[bool, str|None, list[str]]` dans `quality.py` : BVS ≤ 0 → exclude "book_value_per_share <= 0", ROE is None → exclude "ROE 3 ans indisponible", ROE < 0 → exclude "ROE négatif", EBITDA ≤ 0 → exclude, debt_ebitda > 6 → exclude, ROE > 1.50 + BVS < 5$ → flag `⚠️ ROE possiblement gonflé par buybacks` + `metrics["roe_capped"] = True`
- [ ] T027 [P] [US1] Implémenter exceptions sectorielles dans `quality.py` : `exclude_debt = sector in ["Financials", "Real Estate", "Utilities"]` → pilier Qualité sur 3 critères (ROE, marge op., FCF yield) si True
- [ ] T028 [US1] Créer `scanner/scoring/valuation.py` : `calculate_valuation_metrics(ticker_info) -> dict` → `pe_ratio` (`peRatioTTM`, fallback P/E TTM -5pts si Forward absent), `ev_ebitda` (`enterpriseValueMultipleTTM`), `peg_ratio` (`pegRatioTTM`); repondération si P/E + EV/EBITDA tous absents → `score_global = qualite×0.50 + momentum×0.50`
- [ ] T029 [US1] Créer `scanner/scoring/momentum.py` : `calculate_momentum_metrics(ticker_info, prices_df, sector) -> dict` → `perf_6m` (J0/J-126 -1), `surperf_6m` (perf_6m - perf_6m_SECTOR_ETF), `perf_3m` (J0/J-63 -1), `surprise_earnings` (via `earnings-surprises` FMP), `revision_analystes` (via `analyst-estimates` FMP)
- [ ] T030 [US1] Implémenter décroissance earnings dans `momentum.py` : `days_since = (today - last_earnings_date).days`, `decay = max(0.0, min(1.0, 1.0 - days_since / 90))`, redistribution proportionnelle des poids libérés aux 4 autres critères
- [ ] T031 [US1] Implémenter pénalités anti-extrême dans `momentum.py` : `perf_1m > 0.25` → `-10 pts`, `perf_1m < -0.20` → `-5 pts`, score momentum clampé `[0, 100]`
- [ ] T032 [US1] Créer `scanner/scoring/engine.py` : `RATIO_CLAMP` dict (roe:[0,1.5], operating_margin:[-0.5,0.6], fcf_yield:[-0.2,0.3], debt_ebitda:[0,10], pe_ratio:[1,60], ev_ebitda:[0,40], peg_ratio:[-5,5]), `winsorize(value, low, high)` clamp dans plage
- [ ] T033 [US1] Implémenter `percentile_rank(series) -> Series` cross-universe dans `engine.py`. Implémenter `intra_sector_rank(df, metric, sector_col) -> Series` avec fallback cross-universe si secteur < 3 tickers
- [ ] T034 [US1] Implémenter `stock_scoring_pipeline(tickers_data, prices_df) -> DataFrame` dans `engine.py` : winsorise les ratios → gates qualité → percentile rank → score_global = qualite×0.35 + valorisation×0.30 + momentum×0.35; `rank_roe` plafonné 80 si `roe_capped=True`; exclut sector=None avec log `sector_missing`
- [ ] T035 [US1] Compléter `scanner/notifier.py` : `escape_html(text)` (`html.escape(str(text))`), `truncate_message(text)` (≤ 4096 chars, coupe proprement à dernier `\n` + `⚠️ [message tronqué]`), `format_signal(ticker_data, regime, rank) -> str` suivant template §6.1 spec
- [ ] T036 [US1] Implémenter `send_signals(top10_actions, regime)` dans `notifier.py` : boucle + `asyncio.sleep(1.5)`, `parse_mode="HTML"`, `disable_web_page_preview=True`
- [ ] T037 [US1] Implémenter `save_scan(conn, scan_data)` et `save_signals(conn, signals_list)` dans `storage.py` : `first_seen_date` = date courante si nouveau ticker, conservée si réapparition (query `SELECT first_seen_date FROM signals WHERE ticker=? ORDER BY scan_date ASC LIMIT 1`)
- [ ] T038 [US1] Câbler pipeline complet dans `main.py` : `build_eligible_universe` → MIN_UNIVERSE check → momentum score Chalutier → Top 30 → `fetch_fmp_fundamentals` (avec disjoncteur) → `stock_scoring_pipeline` → Top 10 → `save_scan` + `save_signals` → `send_signals`
- [ ] T039 [P] [US1] Test intégration (VCR + Freezegun mercredi 10h00 ET) : pipeline complet → 1 entrée `scans`, 10 entrées `signals`, `score_global` ∈ [0,100] pour chaque ticker, jamais NaN
- [ ] T040 [P] [US1] Test budget FMP : mock `fmp_call_counter`, run 30 tickers → assert `fmp_call_counter ≤ 245` (SC-001)

**Checkpoint** : `python main.py --now --force` → message Telegram reçu dans les 15 min avec Top 10, scores non-nuls. Budget FMP ≤ 245. Scanner v1.0 MVP fonctionnel.

---

## Phase 5 : User Story 3 — Entonnoir qualité données (Priorité : P2)

**Objectif** : Filtres éligibilité complets, freshness, earnings calendar, MIN_UNIVERSE_SIZE robuste

**Test indépendant** : Injecter tickers BVS ≤ 0 / ROE None / sector=None / données > 180j → vérifier exclusions + logs corrects

- [ ] T041 [US3] Ajouter exclusion sector=None dans `scanner/universe.py` (ou `engine.py`) : log `sector_missing` avec ticker, exclure du pipeline Actions, maintenir dans univers pour runs suivants
- [ ] T042 [US3] Implémenter `data_freshness_check(ticker_data) -> tuple[bool, list[str]]` dans `scanner/filters.py` : calcule `days_since_report = (today - last_report_date).days`; > 120j → flag `⚠️ données potentiellement périmées`; > 180j → retourne `(False, ["données trop vieilles"])` (exclu ranking)
- [ ] T043 [US3] Implémenter `earnings_calendar_check(ticker, calendar_data) -> str|None` dans `scanner/filters.py` : date earnings dans `[today, today + 14j]` → retourne `📅 Earnings à venir : {date}` (tag informatif, non bloquant)
- [ ] T044 [US3] Implémenter concentration sectorielle dans `scanner/filters.py` : `apply_sector_concentration(ranked_df, max_per_sector=3) -> DataFrame` → si secteur dépasse plafond, remplace overflow par meilleurs tickers restants hors-secteur
- [ ] T045 [US3] Câbler `filters.py` dans pipeline `engine.py` / `main.py` : freshness check avant ranking final, earnings tag ajouté aux `flags` JSON du signal, concentration sectorielle appliquée sur Top 10 avant envoi
- [ ] T046 [P] [US3] Tests `tests/test_logic.py` : fixtures données manquantes → BVS ≤ 0 exclu avec reason, ROE None exclu "indisponible", sector=None exclu `sector_missing`, données > 180j exclues ranking

**Checkpoint** : FR-003 respecté (yfinance non utilisé pour ROE/marges). US3 acceptance criteria 1–6 passent tous.

---

## Phase 6 : User Story 4 — Persistance et suivi de performance (Priorité : P2)

**Objectif** : SQLite complet + table `scanned_universe` (anti survivorship bias) + job retours automatique

**Test indépendant** : 2 scans successifs → `first_seen_date` stable, `scanned_universe` ~600-700 lignes/scan, `return_30d` calculable après 30j mock

- [ ] T047 [US4] Ajouter `CREATE TABLE IF NOT EXISTS scanned_universe` dans `scanner/storage.py` : colonnes `scan_date, ticker, score_momentum, rank_chalutier, in_shortlist, in_top10, price_at_scan, sector, market_cap` + `CREATE INDEX idx_scanned_universe_date`
- [ ] T048 [US4] Implémenter `save_scanned_universe(conn, scan_date, eligible_df)` dans `storage.py` : INSERT de TOUS les tickers post-éligibilité Chalutier (pré-shortlist) avec leurs métriques momentum + flags in_shortlist/in_top10
- [ ] T049 [US4] Câbler `save_scanned_universe` dans `main.py` : appelé immédiatement après `build_eligible_universe()`, avant shortlisting Top 30
- [ ] T050 [US4] Implémenter `update_signal_returns(conn)` dans `storage.py` : `SELECT id, ticker, scan_date, price_at_signal FROM signals WHERE price_30d_later IS NULL AND scan_date <= date('now', '-30 days')`, fetch prix yfinance uniquement (0 appel FMP), UPDATE `price_30d_later` + `return_30d`
- [ ] T051 [US4] Ajouter job background `update_signal_returns` dans APScheduler `main.py` : `cron` quotidien (ex: 10h30 ET), indépendant du scan principal
- [ ] T052 [P] [US4] Test `tests/test_integration_vcr.py` : 2 scans consécutifs (Freezegun J et J+31) → `first_seen_date` non réinitialisée sur réapparition, `scanned_universe` peuplée, après 31j mock `return_30d` calculé

**Checkpoint** : SC-006 validé (`SELECT avg(return_30d) FROM signals` retourne résultat calculable). `first_seen_date` stable sur 2 scans.

---

## Phase 7 : User Story 5 — ETFs sectoriels pipeline séparé (Priorité : P3)

**Objectif** : ETFs scorés sur momentum pur (sector rotation), leveraged exclus, section Telegram distincte

**Test indépendant** : TQQQ → exclu. SOXL → exclu. XLK → scoré (score = perf_6m×0.5 + surperf_vs_SPY×0.5). Section `📦 TOP ETFs DU JOUR` séparée.

- [ ] T053 [US5] Implémenter `is_eligible_etf(ticker: str, name: str) -> bool` dans `scanner/universe.py` : `EXCLUDED_ETF_PATTERNS = ["3X", "2X", "-3", "-2", "ULTRA", "ULTRA SHORT", "BEAR", "SHORT", "INVERSE", "DAILY", "PROSHARES"]`, retourne `not any(pat in name.upper() for pat in patterns)`
- [ ] T054 [US5] Implémenter `etf_scoring_pipeline(etfs_data, prices_df) -> DataFrame` dans `scanner/scoring/engine.py` : score = `perf_6m × 0.50 + surperf_vs_spy × 0.50`, 0 appel FMP, 0 métrique fondamentale, filtre `is_eligible_etf()` avant scoring
- [ ] T055 [P] [US5] Implémenter `format_etf_signal(etf_data, rank) -> str` dans `scanner/notifier.py` : format §6.2 spec, section commençant par `📦 TOP ETFs DU JOUR`
- [ ] T056 [US5] Câbler ETF pipeline dans `main.py` : après shortlisting Actions, scorer ETFs séparément → Top 5 → `save_signals(signal_type='etf')` → `send_etf_signals()` en section Telegram distincte
- [ ] T057 [P] [US5] Tests `tests/test_logic.py` : TQQQ (nom "ProShares UltraPro QQQ") → `is_eligible_etf()` retourne False; SOXL ("Direxion Daily Semiconductor Bull 3X Shares") → False; XLK ("Technology Select Sector SPDR") → True; score ETF = perf_6m×0.5 + surperf×0.5 sans FMP

**Checkpoint** : US5 acceptance criteria 1–3 passent. Section ETF distincte dans Telegram. 0 appel FMP pour les ETFs.

---

## Phase 8 : Polish & Transverse

**Objectif** : Tests hermétiques complets, déploiement Mac Mini, validation finale

- [ ] T058 Créer `tests/conftest.py` : configuration VCR.py `record_mode="none"` par défaut, cassettes dans `tests/cassettes/`, fixtures Freezegun (mercredi 10h00 ET)
- [ ] T059 [P] Créer `tests/test_logic.py` complet : tests statiques scoring — `apply_quality_gates` (BVS ≤ 0, ROE None, ROE < 0, ROE > 150% + BVS < 5$ cap), decay earnings clampé [0,1], pénalités anti-extrême, winsorisation `RATIO_CLAMP`, `evaluate_market_regime` 4 scénarios
- [ ] T060 [P] Créer `tests/test_fetcher_vcr.py` : connecteurs yfinance chunked (chunk size 100, 2 cassettes) + FMP 7 endpoints (cassette par ticker) + disjoncteur 245 (mock counter)
- [ ] T061 Créer `tests/test_integration_vcr.py` : pipeline complet (VCR + Freezegun) — scan complet → `scans` + `signals` écrits, Market Gate PANIC → 0 signaux, FMP indisponible → Telegram erreur + 0 signaux
- [ ] T062 Test mock FMP call counter : run complet 30 tickers via fixtures → assert `fmp_call_counter ≤ 245` (SC-001)
- [ ] T063 [P] Vérifier exhaustivement `html.escape()` dans `notifier.py` : fixtures AT&T, Johnson & Johnson, tout nom avec `<>/&` → chaînes correctement escapées dans message final
- [ ] T064 [P] Documenter setup Mac Mini dans `README.md` section "Déploiement" : `pmset -a sleep 0 disksleep 0 hibernatemode 0 powernap 0`, clone + venv + pip install, `supervisord -c supervisord.conf`
- [ ] T065 Créer script bash `scripts/install-launchd.sh` : génère `~/Library/LaunchAgents/com.valuemomentum.plist` depuis `PROJECT_DIR="$(pwd)"`, `launchctl load "$PLIST"` — flag `-n` obligatoire pour `KeepAlive`
- [ ] T066 Run `pytest tests/ -v --tb=short` → assert 100% pass en isolation réseau (SC-005)
- [ ] T067 [P] Vérifier `score_global ∈ [0, 100]` pour toutes les fixtures de test, jamais NaN (SC-003)

**Checkpoint** : SC-001 à SC-006 tous validés. `supervisorctl status` : scanner RUNNING + web RUNNING. Reboot Mac Mini → scanner redémarre automatiquement.

---

## Dépendances & Ordre d'exécution

### Dépendances entre phases

- **Phase 1 (Setup)** : Aucune dépendance — peut démarrer immédiatement
- **Phase 2 (Foundationnel)** : Dépend de Phase 1 — BLOQUE toutes les user stories
- **Phase 3 (US2 Market Gate)** : Dépend de Phase 2 (fetcher market indicators)
- **Phase 4 (US1 MVP)** : Dépend de Phase 2 + Phase 3 (Market Gate intégré dans pipeline)
- **Phase 5 (US3 Entonnoir)** : Dépend de Phase 2 — peut commencer en parallèle de Phase 3/4
- **Phase 6 (US4 Persistance)** : Dépend de Phase 4 (pipeline complet, signaux écrits)
- **Phase 7 (US5 ETFs)** : Dépend de Phase 2 — peut commencer dès Phase 2 terminée
- **Phase 8 (Polish)** : Dépend de toutes les phases précédentes

### Dépendances intra-user story

- Models → Services → Intégration pipeline → Tests
- `apply_quality_gates` (T026) avant `stock_scoring_pipeline` (T034)
- `notifier.py` (T035-T036) avant câblage pipeline (T038)
- `save_signals` (T037) avant `update_signal_returns` (T050)

### Opportunités parallèles

- T002, T003, T004 parallèles entre eux (Phase 1)
- T011, T012, T013 parallèles (même module fetcher.py, sections distinctes)
- T020, T021, T022, T023 parallèles (tests Market Gate, données indépendantes)
- T025, T027, T028, T029 parallèles (scoring pillars distincts)
- T039, T040 parallèles (tests US1)
- T059, T060, T063, T064, T067 parallèles (Polish)

---

## Exemple d'exécution parallèle — Phase 4 (US1)

```bash
# Scoring pillars en parallèle (fichiers distincts, 0 dépendances croisées) :
T025 scanner/scoring/quality.py       ← calculate_quality_metrics
T027 scanner/scoring/quality.py       ← sector exceptions (même fichier mais section distincte)
T028 scanner/scoring/valuation.py     ← valuation metrics
T029 scanner/scoring/momentum.py      ← momentum metrics

# Puis séquentiellement :
T030 momentum.py     ← décroissance + pénalités (dépend T029)
T031 engine.py       ← RATIO_CLAMP + winsorize
T032 engine.py       ← percentile_rank (dépend T031)
T033 engine.py       ← pipeline scoring (dépend T026, T031, T032)
```

---

## Stratégie d'implémentation

### MVP First (User Story 1 uniquement)

1. Phase 1 Setup → Phase 2 Foundationnel → Phase 3 Market Gate → Phase 4 US1
2. **STOP et VALIDER** : `python main.py --now --force` → message Telegram reçu avec Top 10
3. Déployer sur Mac Mini (Phase 8 partiel : T064-T065)
4. Laisser tourner 7 jours → vérifier logs + `scanner_history.db`

### Livraison incrémentale

1. **MVP** : US2 + US1 → Scanner opérationnel + Market Gate
2. **+US3** : Filtres qualité données complets
3. **+US4** : Persistance anti survivorship bias + track record
4. **+US5** : ETF pipeline
5. **+Polish** : Tests hermétiques complets + déploiement robuste

---

## Résumé

| Phase | User Story | Tâches | Statut |
|-------|-----------|--------|--------|
| 1 Setup | — | T001–T007 | ⬜ |
| 2 Foundationnel | — | T008–T014 | ⬜ |
| 3 Market Gate | US2 (P1) | T015–T023 | ⬜ |
| 4 MVP Scan | US1 (P1) | T024–T040 | ⬜ |
| 5 Entonnoir | US3 (P2) | T041–T046 | ⬜ |
| 6 Persistance | US4 (P2) | T047–T052 | ⬜ |
| 7 ETFs | US5 (P3) | T053–T057 | ⬜ |
| 8 Polish | — | T058–T067 | ⬜ |
| **Total** | | **67 tâches** | |

- **Tâches [P]** (parallélisables) : 30
- **MVP scope** : T001–T040 (Phases 1–4) = 40 tâches
