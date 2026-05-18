# Feature Specification: ValueMomentum Scanner — Implémentation V1 Complète

**Feature Branch**: `001-spec-review-fixes`

**Created**: 2026-05-19

**Status**: Draft

**Spec de référence**: `specs/Spec_ValueMomentum_Scanner.md` (source de vérité pour tous les détails algorithmiques)

**Constitution**: `.specify/memory/constitution.md` v1.1.0

---

## User Scenarios & Testing _(mandatory)_

### User Story 1 — Scan quotidien avec signaux Telegram (Priority: P1)

Je suis un trader position trading. Chaque matin de bourse (09h35 ET), je reçois automatiquement sur Telegram un rapport contenant le Top 10 actions et Top 5 ETFs scorés sur 3 piliers (Qualité, Valorisation, Momentum), avec toutes les métriques clés et les flags de risque.

**Why this priority**: C'est la valeur core du produit. Sans ça, rien d'autre n'a de sens.

**Independent Test**: Lancer `python main.py --now` → vérifier réception Telegram avec Top 10 stocks + Top 5 ETFs formatés correctement.

**Acceptance Scenarios**:

1. **Given** marché NYSE ouvert, **When** scan déclenché à 09h35 ET, **Then** message Telegram reçu dans les 15 minutes contenant ≥ 1 stock scoré avec `score_global`, `score_qualite`, `score_valorisation`, `score_momentum` tous non-nuls
2. **Given** FMP API disponible, **When** 30 tickers shortlistés, **Then** budget FMP ≤ 250 calls (7 endpoints × 30 = 210 nominaux)
3. **Given** jour férié NYSE, **When** scheduler déclenche, **Then** aucun scan exécuté, aucun message Telegram envoyé
4. **Given** FMP indisponible (clé absente ou 5xx persistant après 2 retries), **When** scan déclenché, **Then** message Telegram `⚠️ Sniper FMP indisponible` envoyé, aucun signal émis
5. **Given** message Telegram > 4096 chars, **When** envoi, **Then** message tronqué avec `[message tronqué]` à la fin — pas d'erreur API Telegram

---

### User Story 2 — Filtre de régime marché (Priority: P1)

Le système détecte le régime de marché avant chaque scan et adapte son comportement : silence total en panique réelle (VIX > 35), avertissement en période de stress modéré, scan normal sinon.

**Why this priority**: La préservation du capital prime sur le rendement — c'est la contrainte numéro 1 du besoin.

**Independent Test**: Tester avec mocks SPY/VIX aux 4 niveaux de régime → vérifier comportement exact.

**Acceptance Scenarios**:

1. **Given** VIX > 35 (quelle que soit la position SPY vs EMA200), **When** scan déclenché, **Then** scan annulé, message Telegram `🚨 RÉGIME DE PANIQUE`, 1 entrée `regime='panic'` dans table `scans`, 0 entrée dans `signals`
2. **Given** SPY < EMA200 ET VIX entre 25 et 35, **When** scan exécuté, **Then** chaque signal Top 10 contient flag `⚠️ RÉGIME DE PRUDENCE`
3. **Given** SPY < EMA200 ET VIX ≤ 25, **When** scan exécuté, **Then** scan normal, warning en log interne uniquement (pas de flag Telegram)
4. **Given** SPY ≥ EMA200 ET VIX ≤ 25, **When** scan exécuté, **Then** scan complet, Top 10 émis sans flag de régime

---

### User Story 3 — Entonnoir qualité données (Priority: P2)

Le système applique un filtre d'éligibilité strict sur ~700 tickers avant tout calcul, puis un scoring complet sur les 30 meilleurs sur momentum, garantissant que seules des données fraîches et fiables entrent dans le scoring.

**Why this priority**: Des signaux sur données corrompues sont pires que pas de signaux.

**Independent Test**: Injecter des tickers avec données manquantes, vieilles, secteur=None → vérifier exclusions correctes avec logs.

**Acceptance Scenarios**:

1. **Given** ticker avec `marketCap < 2B$` ou `volume_dollar_20j < 5M$` ou `price < 5$`, **When** filtre éligibilité appliqué, **Then** ticker exclu avant scoring, loggé `eligibility_filter`
2. **Given** ticker avec `sector = None` (yfinance), **When** pipeline Actions, **Then** exclu du scoring avec motif `sector_missing`
3. **Given** données fondamentales FMP > 120 jours, **When** ticker dans Top 10, **Then** flag `⚠️ données potentiellement périmées` dans message Telegram
4. **Given** données fondamentales FMP > 180 jours, **When** ranking final, **Then** ticker exclu du Top 10
5. **Given** univers après filtres < 100 tickers, **When** scoring déclenché, **Then** scan annulé avec warning log `universe_too_small`
6. **Given** secteur avec < 3 tickers dans la shortlist scorée, **When** ranking intra-secteur, **Then** bascule automatique vers ranking cross-universe pour ce secteur

---

### User Story 4 — Persistance et suivi de performance (Priority: P2)

Chaque scan est enregistré en base SQLite. Les signaux du Top 10 sont stockés avec leur prix au moment du signal. Un job de fond met à jour le retour à 30j et 90j pour valider la stratégie sur données réelles.

**Why this priority**: Sans track record, impossible de valider ou invalider la stratégie.

**Independent Test**: Lancer 2 scans successifs → vérifier tables `scans` et `signals` SQLite avec les champs obligatoires.

**Acceptance Scenarios**:

1. **Given** scan complété, **When** Top 10 émis, **Then** 1 entrée dans `scans` + ≤ 10 entrées dans `signals` avec `price_at_signal` non-null
2. **Given** ticker réapparaît dans Top 10 après absence, **When** stockage, **Then** `first_seen_date` conservée (non réinitialisée)
3. **Given** signal stocké depuis ≥ 30 jours, **When** tâche de fond `update_signal_returns()` exécutée, **Then** `price_30d_later` et `return_30d` mis à jour (yfinance seul, aucun appel FMP)
4. **Given** scan en régime Panique, **When** exécuté, **Then** 1 entrée `scans` avec `regime='panic'`, 0 entrée `signals`

---

### User Story 5 — ETFs sectoriels en pipeline séparé (Priority: P3)

Les ETFs ont leur propre pipeline de scoring (momentum pur, pas de fondamentaux), leur propre section Telegram, et sont filtrés pour exclure les produits leveraged/inverses.

**Why this priority**: ETFs complètent le signal actions mais nécessitent une logique différente.

**Independent Test**: Injecter ETFs dont TQQQ (leveraged) → vérifier exclu. XLK → scoré. Vérifier section Telegram distincte.

**Acceptance Scenarios**:

1. **Given** ETF avec "ULTRA", "3X", "BEAR" dans le nom, **When** pipeline ETF, **Then** exclu du scoring ETF
2. **Given** Top 5 ETFs scorés, **When** message Telegram, **Then** section `📦 TOP ETFs DU JOUR` séparée de la section Actions
3. **Given** ETF scoré, **When** scoring, **Then** score = 50% Perf 6M + 50% Surperf vs SPY, aucune métrique fondamentale utilisée

---

### Edge Cases

- `ROE > 150%` avec `book_value_per_share < 5$` : flag `⚠️ ROE possiblement gonflé par buybacks`, score ROE plafonné au percentile 80
- `book_value_per_share ≤ 0` : ticker exclu du pilier Qualité (ROE mathématiquement sans sens)
- `EBITDA ≤ 0` ou `Dette/EBITDA > 6x` : exclusion inconditionnelle
- `P/E Forward absent (~40-60% des tickers)` : fallback P/E TTM avec pénalité -5 pts sur score pilier Valorisation
- `P/E Forward ET P/E TTM absents` : pilier Valorisation exclu, repondération `score = Qualité×0.50 + Momentum×0.50`
- Secteurs Financials / Real Estate / Utilities : exclusion Dette/EBITDA du pilier Qualité (structure bilancielle incompatible)
- Biotech (Health Care, marketCap < 5B$) : gate P/E négatif suspendu
- Earnings dans les 14 prochains jours : tag `📅 Earnings à venir` (informatif, non bloquant)
- yfinance batch download partiel (< 60% tickers valides) : scan interrompu, alerte Telegram erreur

---

## Requirements _(mandatory)_

### Functional Requirements

- **FR-001**: Le scan DOIT s'exécuter uniquement les jours de bourse NYSE (via `pandas_market_calendars`)
- **FR-002**: Le Market Gate DOIT évaluer VIX et SPY/EMA200 en priorité absolue avant tout scoring
- **FR-003**: `yfinance` NE DOIT PAS être utilisé pour calculer ROE, marges, FCF, ou toute donnée bilancielle
- **FR-004**: FMP DOIT être utilisé pour les 7 endpoints de la shortlist (30 tickers max, 210 calls nominaux)
- **FR-005**: Si FMP indisponible : Telegram `⚠️ Sniper FMP indisponible` + scan arrêté — aucun fallback yfinance fondamentaux
- **FR-006**: Scoring Actions = 3 piliers (Qualité 35%, Valorisation 30%, Momentum 35%) avec percentile ranking
- **FR-007**: Scoring Momentum = 5 critères incluant révision estimations analystes (FMP `analyst-estimates`)
- **FR-008**: Earnings Surprise DOIT avoir décroissance temporelle linéaire sur 90 jours post-résultats
- **FR-009**: Ranking intra-secteur DOIT basculer en cross-universe si secteur a < 3 tickers dans la shortlist
- **FR-010**: Tous les messages Telegram DOIVENT être html.escape()'és et tronqués à 4096 chars max
- **FR-011**: SQLite WAL mode OBLIGATOIRE pour l'accès concurrent bot/dashboard
- **FR-012**: Toutes les constantes métier DOIVENT être dans `config.yaml` (pas de magic numbers dans le code)

### Key Entities

- **Scan** : Un run quotidien — date, régime marché, métriques SPY/VIX/EMA200, taille univers
- **Signal** : Un ticker dans le Top 10/5 d'un scan — score global + piliers, prix au signal, flags, first_seen_date, retours à 30j/90j
- **Ticker** : Instrument financier — Actions (pipeline complet) ou ETF (pipeline momentum seul)
- **Cache** : Entrée TTL JSON — fondamentaux 24h, prix 4h, invalidation post-earnings
- **Universe** : Liste JSON des tickers stocks + ETFs — source statique mise à jour manuellement

---

## Success Criteria _(mandatory)_

### Measurable Outcomes

- **SC-001**: Budget FMP ≤ 250 calls/jour en conditions nominales (30 tickers × 7 endpoints = 210)
- **SC-002**: Durée totale du scan ≤ 15 minutes de 09h35 ET à réception Telegram
- **SC-003**: `score_global` est un float [0, 100] pour chaque ticker du Top 10, jamais NaN
- **SC-004**: Aucun scan ne crash silencieusement — toute erreur critique produit un message Telegram d'erreur
- **SC-005**: 100% des tests passent en isolation réseau (VCR cassettes, aucun appel API live en test)
- **SC-006**: Après 90 jours de production, requête SQL sur `signals` retourne `avg(return_30d)` calculable

---

## Constitution Alignment

- [x] **Mandate Check**: Entonnoir Chalutier/Sniper respecté. Market Gate 4 niveaux avec priorité VIX. Liquidité institutionnelle appliquée.
- [x] **Technical Alignment**: SQLite WAL, asyncio APScheduler 4.x, jitter rate-limiting, FMP circuit-breaker 2 retries.
- [x] **Validation Standards**: VCR.py cassettes pour tests réseau, Freezegun pour logique temporelle.

---

## Assumptions

- Mac Mini local — pas de cloud, pas de Docker, pas de CI/CD automatisé
- `yfinance >= 0.2.40` stable pour batch OHLCV download (comportement threads=True)
- FMP free tier à 250 calls/jour sans rate-limit par seconde documenté
- APScheduler 4.x alpha stable pour usage local (pas de production scalée)
- L'univers `tickers_universe.json` est maintenu manuellement ±1x/mois
- Aucun ordre financier n'est exécuté — scanner de décision uniquement
