# Implementation Plan: ValueMomentum Scanner

**Branch**: `main` | **Date**: 2026-05-21 | **Spec**: `specs/Spec_ValueMomentum_Scanner.md`

**Input**: `specs/Spec_ValueMomentum_Scanner.md` + `specs/besoin.md` + `.specify/memory/constitution.md`

## Summary

Scanner quotidien quantitatif pour Position Trading (horizon 3–6 mois). Architecture en entonnoir asymétrique : Chalutier yfinance (~700 tickers, OHLCV + momentum) → Sniper FMP (Top 30, fondamentaux institutionnels) → Top 10 Telegram. Score 3 piliers (Qualité 35%, Valorisation 30%, Momentum 35%) en percentile ranking cross-universe / intra-secteur GICS. Market Gate 4 niveaux (VIX > 35 = Panique, arrêt total). SQLite WAL pour historisation et backtesting futur. Déployé sur Mac Mini macOS via supervisord + launchd.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: yfinance >= 0.2.40, httpx >= 0.27.0, APScheduler >= 4.0.0a5, python-telegram-bot >= 21.0, pandas >= 2.1.0, pandas-market-calendars >= 4.3.0, PyYAML >= 6.0.1, loguru >= 0.7.2

**Storage**: SQLite WAL (`data/signals/scanner_history.db`) — tables `scans`, `signals`, `scanned_universe`, `universe_metadata`

**Testing**: pytest >= 8.0.0 + pytest-asyncio + VCR.py (isolation réseau) + Freezegun (déterminisme temporel)

**Target Platform**: macOS (Mac Mini local), supervisord + launchd boot persistence

**Project Type**: Service autonome (scanner + notifier) — pas de web API en v1.0

**Performance Goals**: Scan complet ≤ 15 min de 09h35 ET à réception Telegram ; Budget FMP ≤ 175 calls/run (disjoncteur hard limit — 30 × 5 = 150 nominal + 25 retry margin, BF-010)

**Constraints**: FMP free tier 250 calls/jour strict ; SHORTLIST_SIZE = 30 non négociable ; hard limit 175 calls/run (BF-010) ; yfinance chunks ≤ 100 tickers + pause 2s ; CACHE_TTL_FUNDAMENTALS = 97200s (27h, anti race condition) ; SQLite local uniquement

**Scale/Scope**: ~700 tickers univers, 30 shortlist, 10 signaux Top Actions + 5 ETFs/jour

## Constitution Check

_GATE: Must pass before Phase 0 research. Re-check after Phase 1 design._

- [x] **I. Funnel Architecture**: Chalutier/Sniper separation respected. FMP-only for fundamentals (ROE, marges, dette/EBITDA, FCF, P/E forward, surprise earnings, révisions analystes). No yfinance fallback for balance sheet data (Règle d'Or §16). ETF pipeline momentum-only 50% Perf 6M + 50% Surperf vs SPY (sector rotation framing, not value). Leveraged/inverse ETFs excluded by name pattern.
- [x] **II. Quality & Stability**: ROE 3Y from FMP `income-statement` (3 annual periods) — no TTM fallback, no yfinance. `book_value_per_share ≤ 0` → exclude (ROE mathématiquement sans sens). `ROE > 150%` + `BVS < $5` → cap percentile 80 + flag `⚠️ ROE possiblement gonflé par buybacks`. Utilities/Financials/REITs excluded from debt/EBITDA gate (3-criteria quality pillar instead). Data freshness: 365d warn flag, 450d exclusion (bilans annuels FMP — BF-028).
- [x] **III. Market Gate**: 4-level priority cascade intact — Panique VIX > 35 (scan annulé, 0 signaux, 1 entrée `scans` regime='panic'), Prudence SPY < EMA200 + VIX 25–35 (flag sur chaque signal), Bear Light SPY < EMA200 + VIX ≤ 25 (log interne uniquement), Normal (Top 10 complet). VIX evaluated before EMA200 (VIX = leading indicator, EMA200 = lagging).
- [x] **IV. Institutional Liquidity**: Cap > $2B, Dollar Vol > $5M (20d avg), Price > $5, NYSE/NASDAQ/AMEX only. OTC et tickers hors-US exclus.
- [x] **V. Quantitative Momentum**: 5 sub-criteria — Perf 6M (30%), Surperf sectorielle 6M (30%), Perf 3M (15%), Earnings Surprise avec décroissance linéaire 90j (15%), Révision analystes 3M (10%). Pénalités anti-extrême : 1M > +25% → -10 pts, 1M < -20% → -5 pts sur score momentum final.
- [x] **VI. Sector GICS Integrity**: `sector = None` → exclu avec log `sector_missing`. Sectors < 3 tickers dans shortlist → cross-universe fallback pour métriques intra-secteur. MIN_UNIVERSE_SIZE = 100 vérifié sur l'univers complet post-éligibilité Chalutier (avant shortlisting à 30) — vérification dans `main.py` après `build_eligible_universe()`, pas dans `stock_scoring_pipeline()`.
- [x] **VII. Signal Persistence**: `first_seen_date` jamais réinitialisée à la réapparition. Sortie du Top 10 par score uniquement (pas de rotation calendaire). Signal persistant > 90 jours = conviction, pas anomalie.
- [x] **Technical Standards**: SQLite WAL activé (`PRAGMA journal_mode=WAL`). APScheduler 4.x async (même event loop que Telegram + httpx). Jitter 0.8–1.5s entre tous les appels externes. FMP 2 retries max + disjoncteur global 175 calls (BF-010). `html.escape()` obligatoire sur toutes les chaînes dans messages Telegram. Truncation 4096 chars.
- [x] **Quality Gates**: VCR.py cassettes pour tous les tests réseau (isolation complète, 0 appel API live par défaut). Freezegun pour toute logique temporelle (NYSE calendar, freshness, earnings decay, fenêtre earnings).

## Project Structure

### Documentation (this feature)

```text
specs/
├── plan.md                      # Ce fichier
├── besoin.md                    # Expression de besoin du trader
└── Spec_ValueMomentum_Scanner.md # Spec technique complète (source de vérité)
```

### Source Code (repository root)

```text
valuemomentum-scanner/
├── main.py                      # Orchestrateur : scheduler APScheduler, Market Gate, pipeline principal
├── config.yaml                  # Toutes les constantes métier (source de vérité)
├── supervisord.conf             # Process manager (scanner + web)
├── .env                         # Secrets (gitignored)
├── requirements.txt
│
├── scanner/
│   ├── __init__.py
│   ├── universe.py              # Module 1 : Universe Builder + refresh auto
│   ├── fetcher.py               # Module 2 : Data Fetcher
│   │                              — yfinance OHLCV chunked (100 tickers, pause 2s)
│   │                              — FMP httpx.AsyncClient + cache 27h + disjoncteur 175 calls (BF-010)
│   │                              — Validation None-safe de toutes les données externes
│   ├── scoring/
│   │   ├── __init__.py
│   │   ├── quality.py           # Pilier Qualité — ROE 3Y FMP, gates BVS, winsorisation
│   │   ├── valuation.py         # Pilier Valorisation — P/E, EV/EBITDA, PEG (FMP)
│   │   ├── momentum.py          # Pilier Momentum — 5 critères, décroissance earnings
│   │   └── engine.py            # Score global, percentile ranking, winsorisation, repondération
│   ├── market_gate.py           # Market Gate 4 niveaux (VIX + EMA200)
│   ├── filters.py               # Module 4 : Post-scoring (freshness, earnings calendar, concentration)
│   ├── notifier.py              # Module 5 : Telegram (html.escape, truncation 4096, rate limit)
│   └── storage.py               # Module 6 : SQLite WAL (scans, signals, scanned_universe)
│
├── data/
│   ├── universe/
│   │   └── tickers_universe.json  # Master list actions + ETFs
│   ├── signals/
│   │   └── scanner_history.db     # SQLite WAL
│   ├── cache/                     # Cache fondamentaux 27h (JSON par ticker)
│   └── logs/
│
├── web/
│   └── index.html               # Dashboard HTML statique v1.0
│
└── tests/
    ├── cassettes/               # VCR.py cassettes (réseau hermétique)
    ├── test_logic.py            # Tests unitaires scoring (données statiques, Freezegun)
    ├── test_fetcher_vcr.py      # Tests connecteurs yfinance/FMP (VCR cassettes)
    └── test_integration_vcr.py  # Pipeline complet (Market Gate, scoring, SQLite)
```

**Structure Decision**: Single project. Pas de séparation frontend/backend en v1.0 — dashboard HTML statique sur http.server. Toute la logique métier dans `scanner/`, strictement découplée du code d'acquisition dans `fetcher.py`.

## Complexity Tracking

> Aucune violation de la Constitution détectée — section vide.

---

## Implementation Phases

### Phase 0 — Research (TERMINÉE)

Décisions architecturales documentées dans `Spec_ValueMomentum_Scanner.md` §Préambule (Actes 1–4). Rationale trader validé : Jegadeesh & Titman momentum 3–6 mois, séparation yfinance/FMP, scoring percentile, Market Gate VIX.

**Outputs** : `specs/besoin.md`, `specs/Spec_ValueMomentum_Scanner.md`

---

### Phase 1 — Core Infrastructure

**Objectif** : Scaffolding projet + configuration + SQLite + scheduler vide fonctionnel.

**Fichiers à créer** :

| Fichier              | Contenu                                                                                                        |
| -------------------- | -------------------------------------------------------------------------------------------------------------- |
| `config.yaml`        | Toutes les constantes (SHORTLIST_SIZE=30, VIX thresholds, TTL cache 97200s, chunk sizes, FMP budget 175, etc.) |
| `.env.example`       | Template secrets (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, FMP_API_KEY)                                           |
| `requirements.txt`   | Dépendances épinglées (voir §10 spec)                                                                          |
| `scanner/storage.py` | Création tables SQLite WAL : `scans`, `signals`, `scanned_universe`, `universe_metadata`                       |
| `main.py`            | Skeleton : load config/env, init DB, APScheduler 4.x async, job quotidien 09h35 ET                             |
| `supervisord.conf`   | Config supervisord (scanner + web, paths relatifs `%(here)s`)                                                  |

**Critères d'acceptation** :

- `python main.py` démarre sans erreur, scheduler inactif affiche "Prochain scan : [date]"
- `scanner_history.db` créée avec 4 tables + WAL mode confirmé (`PRAGMA journal_mode`)
- `supervisorctl status` retourne `scanner RUNNING`

---

### Phase 2 — Universe Builder & Chalutier

**Objectif** : Fetch OHLCV chunked pour ~700 tickers, filtres éligibilité, shortlist Top 30 momentum.

**Fichiers à créer/compléter** :

| Fichier                               | Contenu clé                                                                                                 |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `data/universe/tickers_universe.json` | Master list S&P 500 + Nasdaq 100 + ETFs sectoriels SPDR                                                     |
| `scanner/universe.py`                 | `build_eligible_universe()` : filtres (cap > 2B$, vol > 5M$, prix > 5$, NYSE/NASDAQ/AMEX, ancienneté 2 ans) |
| `scanner/fetcher.py`                  | `fetch_prices_chunked()` : chunks 100, pause 2s, `threads=False`, fallback < 60% batch                      |
| `main.py`                             | MIN_UNIVERSE_SIZE check (≥ 100 tickers post-éligibilité) avant shortlisting                                 |

**Règles de winsorisation** : Les performances 6M / 3M / 1M sont clampées dans `RATIO_CLAMP` avant calcul percentile.

**Critères d'acceptation** :

- `python main.py --now --dry-run` → log affiche taille univers (doit être ≥ 100)
- Si univers < 100 tickers → scan annulé, alerte Telegram `universe_too_small`
- Batch download: aucun HTTP 429 sur run complet ~700 tickers (validé avec cassette VCR)

---

### Phase 3 — Market Gate

**Objectif** : Implémentation du filtre de régime 4 niveaux — PRIORITÉ ABSOLUE avant scoring.

**Fichiers à créer** :

| Fichier                  | Contenu clé                                                                                                         |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| `scanner/market_gate.py` | `evaluate_market_regime(vix, spy_price, spy_ema200)` → enum `{PANIC, CAUTION, BEAR_LIGHT, NORMAL}`                  |
| `main.py`                | Appel Market Gate avant tout scoring ; gestion Panique (écriture `scans` regime='panic', 0 signaux, Telegram alert) |

**Cascade (first match wins)** :

1. VIX > 35 → PANIC (quelle que soit position SPY)
2. SPY < EMA200 AND VIX ∈ [25, 35] → CAUTION
3. SPY < EMA200 AND VIX ≤ 25 → BEAR_LIGHT
4. SPY ≥ EMA200 AND VIX ≤ 25 → NORMAL

**Critères d'acceptation** :

- Tests Freezegun : 4 scénarios × assertion comportement exact (FR-002, User Story 2)
- Panique : 1 entrée `scans`, 0 entrée `signals`, message Telegram `🚨 RÉGIME DE PANIQUE`
- VIX = 36, SPY > EMA200 → PANIC (VIX prime sur EMA200)

---

### Phase 4 — Sniper FMP + Scoring Engine

**Objectif** : Fetch fondamentaux FMP (5 endpoints × 30 tickers = 150 nominal, hard limit 175 — BF-010), scoring 3 piliers, ranking.

**Fichiers à créer/compléter** :

| Fichier                        | Contenu clé                                                                                           |
| ------------------------------ | ----------------------------------------------------------------------------------------------------- |
| `scanner/fetcher.py`           | `fetch_fmp_fundamentals(ticker)` : 5 endpoints httpx, cache 27h, disjoncteur 175 calls (BF-010), 2 retries max |
| `scanner/scoring/quality.py`   | ROE 3Y (FMP only), gates BVS, cap ROE > 150%, winsorisation, exclusion Financials/RE/Utilities        |
| `scanner/scoring/valuation.py` | P/E Forward (FMP), EV/EBITDA, PEG ; fallback P/E TTM -5pts ; repondération si pilier absent           |
| `scanner/scoring/momentum.py`  | 5 critères, décroissance earnings 90j, pénalités anti-extrême ±1M                                     |
| `scanner/scoring/engine.py`    | Percentile ranking (cross-universe / intra-secteur GICS), winsorisation RATIO_CLAMP, score global     |

**Règles critiques** :

- `apply_quality_gates()` retourne `(bool, str|None, list[str])` (3-tuple, jamais 2-tuple)
- Winsorisation AVANT percentile ranking pour TOUS les ratios (voir `RATIO_CLAMP` §4.1 spec)
- Secteur < 3 tickers dans shortlist → ranking cross-universe pour P/E, EV/EBITDA, marge op.
- Decay earnings : `max(0.0, min(1.0, 1.0 - days_since / 90))` — clampé dans [0, 1]
- `scanned_universe` table : tous les tickers post-Chalutier stockés (anti survivorship bias)

**Critères d'acceptation** :

- SC-001 : Budget FMP ≤ 175 calls sur run complet 30 tickers (mock call counter dans tests — 30 × 5 = 150 nominal + 25 retry margin, BF-010)
- SC-003 : `score_global` ∈ [0, 100] pour chaque ticker, jamais NaN
- `apply_quality_gates` : tests ROE TTM refusé, BVS ≤ 0 exclu, ROE > 150% + BVS < 5$ → cap 80

---

### Phase 5 — Telegram Notifier

**Objectif** : Formatage et envoi des signaux (Top 10 Actions + Top 5 ETFs) + messages système.

**Fichiers à créer** :

| Fichier               | Contenu clé                                                |
| --------------------- | ---------------------------------------------------------- |
| `scanner/notifier.py` | `send_signals()`, `send_panic_alert()`, `send_fmp_error()` |

**Règles obligatoires** :

- `html.escape()` sur TOUS les champs string (noms, secteurs, flags) avant format
- Truncation `truncate_message()` à 4096 chars — `[message tronqué]` si dépassement
- Rate limit : `asyncio.sleep(1.5)` entre chaque message
- `parse_mode="HTML"` + `disable_web_page_preview=true`
- Signal actif depuis N jours : calculé depuis `first_seen_date` SQLite

**Critères d'acceptation** :

- Message AT&T ($T) et Johnson & Johnson ($JNJ) : `&` correctement escapé en `&amp;`
- Message > 4096 chars → tronqué proprement, pas d'erreur API
- FR-010 : 100% chaînes escapées (vérifié par test statique sur fixtures)

---

### Phase 6 — ETF Pipeline

**Objectif** : Pipeline scoring ETFs séparé, section Telegram distincte.

**Fichiers à compléter** :

| Fichier                     | Contenu clé                                                                             |
| --------------------------- | --------------------------------------------------------------------------------------- |
| `scanner/scoring/engine.py` | `etf_scoring_pipeline()` : score = 50% Perf 6M + 50% Surperf vs SPY                     |
| `scanner/universe.py`       | `is_eligible_etf()` : exclusion ULTRA/3X/BEAR/SHORT/INVERSE/DAILY/PROSHARES sur nom ETF |

**Critères d'acceptation** :

- TQQQ → exclu (pattern "3X" dans le nom)
- SOXL → exclu (pattern "ULTRA" dans le nom)
- XLK → scoré, section `📦 TOP ETFs DU JOUR` séparée dans Telegram
- Score ETF = prix uniquement (aucun appel FMP, aucune métrique fondamentale)

---

### Phase 7 — Storage & Backtesting Foundation

**Objectif** : Persistance complète + job de suivi de performance + table `scanned_universe`.

**Fichiers à compléter** :

| Fichier              | Contenu clé                                                                           |
| -------------------- | ------------------------------------------------------------------------------------- |
| `scanner/storage.py` | `save_scan()`, `save_signals()`, `save_scanned_universe()`, `update_signal_returns()` |

**Table `scanned_universe`** (anti survivorship bias) :

- Stocke TOUS les tickers post-éligibilité Chalutier à chaque scan
- Champs : `scan_date`, `ticker`, `score_momentum`, `rank_chalutier`, `in_shortlist`, `in_top10`, `price_at_scan`, `sector`, `market_cap`
- Index : `idx_scanned_universe_date ON scanned_universe(scan_date)`

**Critères d'acceptation** :

- SC-006 : `SELECT avg(return_30d) FROM signals` retourne résultat calculable après 30 jours
- `first_seen_date` non réinitialisée sur réapparition (test 2 scans successifs avec même ticker)
- `scanned_universe` contient ~600–700 lignes par scan (pas seulement le Top 10)

---

### Phase 8 — Tests hermétiques

**Objectif** : Suite de tests complète, 100% isolation réseau, déterminisme temporel.

**Fichiers à créer** :

| Fichier                         | Contenu clé                                                                           |
| ------------------------------- | ------------------------------------------------------------------------------------- |
| `tests/test_logic.py`           | Tests unitaires : scoring, gates, decay, pénalités, winsorisation — données statiques |
| `tests/test_fetcher_vcr.py`     | Tests connecteurs yfinance/FMP via cassettes VCR.py                                   |
| `tests/test_integration_vcr.py` | Pipeline complet : Market Gate + scoring + Telegram + SQLite (VCR + Freezegun)        |

**Protocoles obligatoires** :

- VCR.py : `record_mode="none"` par défaut (jamais d'appels live), cassettes dans `tests/cassettes/`
- Freezegun : fixé à mercredi 10:00 ET (NYSE ouvert) pour tous les tests temporels
- Mock FMP call counter : assertion que run complet 30 tickers ≤ 175 calls (SC-001 — 30 × 5 = 150 nominal + 25 retry margin, BF-010)

**Critères d'acceptation** :

- SC-005 : 100% tests passent en isolation réseau (`--offline` ou cassettes en place)
- Aucun `import yfinance` ni `import httpx` direct dans les tests d'intégration (tout via fixtures/mocks)

---

### Phase 9 — Déploiement Mac Mini

**Objectif** : Installation supervisord, launchd, prévention veille.

**Checklist déploiement** :

```bash
# 1. Setup système
sudo pmset -a sleep 0 disksleep 0 hibernatemode 0 powernap 0

# 2. Clone + venv
git clone https://github.com/SirHarveyBix/bot-value.git && cd bot-value
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Secrets
cp .env.example .env  # Remplir TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, FMP_API_KEY

# 4. Lancer supervisord
supervisord -c supervisord.conf
supervisorctl -c supervisord.conf status

# 5. Boot persistence
PROJECT_DIR="$(pwd)"
# → Générer et charger le plist launchd (voir §11.4 spec)
launchctl load ~/Library/LaunchAgents/com.valuemomentum.plist

# 6. Test manuel
python main.py --now --force
```

**Critères d'acceptation** :

- Reboot Mac Mini → scanner redémarre automatiquement, scan déclenché à 09h35 ET suivant
- `supervisorctl status` : `scanner RUNNING`, `web RUNNING`
- Message Telegram reçu dans les 15 minutes après 09h35 ET (SC-002)

---

## Constantes Métier Clés (config.yaml)

| Constante                    | Valeur | Note                              |
| ---------------------------- | ------ | --------------------------------- |
| `SHORTLIST_SIZE`             | 30     | Hard max (budget FMP)             |
| `FMP_CALL_BUDGET_HARD_LIMIT` | 175    | Disjoncteur global (30 × 5 = 150 nominal + 25 retry margin — BF-010) |
| `FMP_MAX_RETRIES`            | 2      | Hard max                          |
| `YFINANCE_CHUNK_SIZE`        | 100    | Tickers par batch                 |
| `YFINANCE_CHUNK_DELAY_S`     | 2.0    | Pause inter-chunks                |
| `CACHE_TTL_FUNDAMENTALS`     | 97200  | 27h (anti race condition TTL 24h) |
| `VIX_PANIC_THRESHOLD`        | 35     | Seuil Panique                     |
| `VIX_WARNING_THRESHOLD`      | 25     | Seuil Prudence                    |
| `MIN_UNIVERSE_SIZE`          | 100    | En dessous → scan annulé          |
| `TELEGRAM_MAX_CHARS`         | 4096   | Limite API fixe                   |
| `MAX_TICKERS_PER_SECTOR`     | 3      | Mode défensif par défaut          |

## Open Questions / Risques

| Risque                         | Mitigation spécifiée                                          |
| ------------------------------ | ------------------------------------------------------------- |
| yfinance HTTP 429              | Chunks 100 + pause 2s + `threads=False` (§3bis.2.1)           |
| FMP quota 250/jour             | Disjoncteur 175 calls + cache 27h (§2, §3bis.2.4 — BF-010)   |
| Race condition cache           | TTL 27h vs 24h (§3bis.2.4)                                    |
| Survivorship bias backtesting  | Table `scanned_universe` complète (§7.2)                      |
| Ratios aberrants (parsing FMP) | Winsorisation `RATIO_CLAMP` avant percentile (§4.1)           |
| Boot Mac Mini après coupure    | launchd `KeepAlive=true` + supervisord `startretries=5` (§11) |
| Cassette VCR obsolète          | Re-record explicite requis (`record_mode="new_episodes"`)     |
