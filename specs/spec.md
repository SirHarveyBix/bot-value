# Spec — ValueMomentum Scanner

### Version 1.0 — Document de référence pour développement IA

---

## Préambule : Discussion fondatrice entre le Value Expert et le PO

> Ce chapitre documente le raisonnement stratégique qui a orienté les choix techniques.
> Il fait partie intégrante des specs car il explique le _pourquoi_ de chaque décision.

---

### Acte 1 — La stratégie : qu'est-ce qu'on cherche vraiment ?

**Value Expert (VE) :** Le nom "ValueMomentum" est bien choisi mais il faut qu'on soit précis sur ce qu'on entend par "valeur". Le P/E forward seul, c'est insuffisant. Buffett ne s'est jamais arrêté au P/E. Ce qui l'intéresse, c'est la _qualité du business_ : est-ce que l'entreprise génère du cash libre de façon prévisible, est-ce qu'elle a un avantage compétitif durable, est-ce que le management alloue le capital intelligemment ?

**PO (Product Owner / Tech) :** Je comprends, mais on est contraints par ce que `yfinance` peut nous donner de façon fiable et gratuite. Le FCF yield par exemple, yfinance le retourne mal pour 30 à 40% des tickers. On ne peut pas construire un scoring sur des données corrompues.

**VE :** C'est exactement là où je veux en venir. Il faut qu'on choisisse des proxies solides de la qualité, pas des métriques exotiques. Ce que je recommande comme socle value : le **Return on Equity (ROE)** sur 3 ans — si une entreprise dégage >15% de ROE de façon stable, elle a probablement un moat. La **marge opérationnelle** — au-dessus de 15%, le business est structurellement défendable. Et le **ratio dette nette / EBITDA** — en dessous de 3x, le bilan ne va pas tuer l'equity. Ces trois données sont fiables dans yfinance.

**PO :** Le P/E forward et le PEG restent pertinents comme filtres d'entrée, non ?

**VE :** En filtres d'élimination oui. Un P/E forward > 30 sur un secteur non-tech, c'est une alerte. Un PEG > 2, ça mérite un regard. Mais je ne les mettrais pas comme critères de scoring positif — trop volatils selon les estimations d'analystes. Ce sont des _gates_, pas des _scores_.

**PO :** D'accord. Parlons momentum. Sur 1 mois de surperformance sectorielle, c'est trop court selon moi. On va capturer du bruit, des rebonds techniques sans conviction.

**VE :** Tout à fait. La littérature académique sur le momentum (Jegadeesh & Titman, AQR) montre que l'effet momentum significatif se mesure sur **3 à 12 mois**, avec un sweet spot autour de **6 mois**. Sur 1 mois, tu risques même l'effet de _mean reversion_ à court terme — les actions qui ont le plus monté sur 1 mois tendent parfois à underperformer le mois suivant.

**PO :** Donc on retient le momentum 6 mois comme indicateur principal, avec le 3 mois comme confirmateur ?

**VE :** Exactement. Et j'ajoute un filtre que j'appelle le "momentum de révision" : si les analystes ont révisé leurs estimations de bénéfices à la hausse sur les 3 derniers mois, c'est un signal fort. Ça capture l'accélération fondamentale que tu avais dans ta spec initiale avec le critère de croissance du CA.

---

### Acte 2 — L'univers : quels tickers scanner ?

**PO :** La spec initiale dit 500 à 1000 tickers. Je préfère commencer avec un univers de qualité plutôt qu'un univers large.

**VE :** Absolument d'accord. 1000 tickers incluant des micro-caps sans liquidité, c'est du poison pour un scanner value. Tu vas avoir des signaux sur des entreprises où le spread bid-ask seul te coûte 1-2% et où tu ne peux pas entrer sur une position significative sans faire bouger le marché.

**PO :** Donc on définit des filtres d'éligibilité stricts avant même le scoring :

- Market cap minimum 2B$ (Large & Mid caps)
- Volume journalier moyen 20 jours > 5M$ (exécutable institutionnel)
- Prix > 5$ (éviter les zones penny stock, split post-crise)
- Listé sur NYSE, NASDAQ, ou AMEX (pas OTC)

**VE :** C'est beaucoup plus sérieux. Cela nous protège du slippage.

**PO :** L'univers de départ sera le **S&P 500 + Russell 1000 + un panier d'ETFs sectoriels et thématiques** (environ 150 ETFs). Au total, on vise ~850 instruments avant filtres de liquidité, ce qui nous amènera à environ 600-700 instruments scorés. C'est le bon calibrage.

---

### Acte 3 — Le scoring : comment on classe ?

**VE :** Le scoring doit refléter la philosophie : on cherche des entreprises de qualité, sous-valorisées, avec du vent dans le dos. Trois piliers donc : **Qualité**, **Valorisation**, **Momentum**.

**PO :** Et on les pondère comment ?

**VE :** Pour un horizon 3-6 mois, le momentum est le catalyseur immédiat. Mais sans qualité et valorisation, tu achètes juste ce qui a déjà monté. Ma suggestion de pondération :

- Qualité : 35%
- Valorisation : 30%
- Momentum : 35%

C'est une pondération qui se rapproche de ce que font les facteurs "Quality Momentum" des grands fonds (AQR, Dimensional). On n'est pas dans le deep value pur Buffett — notre horizon 3-6 mois exige plus de momentum.

**PO :** Chaque pilier aura 3 à 4 sous-critères. On normalise chaque sous-critère en percentile rang sur l'univers entier (0 à 100). C'est la seule façon de comparer des métriques aux échelles très différentes.

**VE :** Le percentile ranking est exactement la bonne approche. Un ROE de 20% peut être très bien dans la distribution ou dans la moyenne selon le secteur. Attention : certains critères doivent être comparés **au sein du même secteur GICS**, pas sur l'univers global. Le P/E d'une banque et le P/E d'un éditeur logiciel, ça n'a aucun sens à comparer directement.

**PO :** Bonne remarque. On implémentera deux types de ranking : **cross-universe** pour les métriques universelles (momentum, croissance CA), et **intra-sector** pour les métriques de valorisation (P/E, EV/EBITDA). Règle de robustesse : si un secteur GICS a **moins de 3 tickers** dans la shortlist scorée, les tickers de ce secteur basculent automatiquement en ranking **cross-universe** pour les métriques intra-secteur. Un ranking intra-secteur sur 1-2 observations est statistiquement sans sens (1 ticker unique obtient automatiquement le percentile 100 — biais systématique).

---

### Acte 4 — Ce qui peut mal tourner ?

**VE :** Le principal risque opérationnel de ce système, c'est la **fraîcheur des données fondamentales**. Les trimestriels ne sortent pas tous les jours. Un P/E calculé sur des earnings vieux de 9 mois peut être complètement trompeur. Le bot doit afficher la date des dernières données fondamentales utilisées dans chaque signal.

**PO :** On ajoutera une "data freshness flag" : si les données financières d'une entreprise ont plus de 120 jours, on la marque `⚠️ données potentiellement périmées` dans le message Telegram.

**VE :** Deuxième risque : les faux positifs autour des résultats trimestriels (Earnings). Une entreprise peut scorer fort juste avant ses résultats, puis s'effondrer de 20% si les earnings déçoivent. Le bot doit filtrer ou au minimum signaler les entreprises avec des résultats attendus dans les 14 prochains jours.

**PO :** On intègre un **Earnings Calendar check** via yfinance. Les tickers avec earnings dans ±14 jours seront tagués `📅 Earnings à venir` — inclus dans les signaux mais avec avertissement explicite.

**VE :** Troisième risque : les ETFs et les actions ne se comparent pas sur les critères fondamentaux. Un ETF n'a pas de P/E, pas de ROE.

**PO :** Bonne observation. On crée deux pipelines de scoring distincts : un pipeline **Actions** avec les 5 critères complets, et un pipeline **ETFs** limité aux critères momentum + flux de capitaux (AUM trend). Les ETFs auront leur propre classement et leur propre section dans le rapport Telegram.

---

## User Stories & Critères d'Acceptation

> Cette section définit les scénarios testables et les exigences fonctionnelles (FR-xxx) de référence. Source de vérité pour la validation QA.

---

### User Story 1 — Scan quotidien avec signaux Telegram (Priorité : P1)

Je suis un trader position trading. Chaque matin de bourse (09h35 ET), je reçois automatiquement sur Telegram un rapport contenant le Top 10 actions et Top 5 ETFs scorés sur 3 piliers (Qualité, Valorisation, Momentum), avec toutes les métriques clés et les flags de risque.

**Test indépendant** : `python main.py --now --force` → réception Telegram avec Top 10 stocks + Top 5 ETFs formatés.

**Scénarios d'acceptation** :

1. **Given** marché NYSE ouvert, **When** scan déclenché à 09h35 ET, **Then** message Telegram reçu dans les 15 minutes avec `score_global`, `score_qualite`, `score_valorisation`, `score_momentum` tous non-nuls
2. **Given** FMP API disponible, **When** 30 tickers shortlistés, **Then** budget FMP ≤ 250 calls (7 endpoints × 30 = 210 nominaux)
3. **Given** jour férié NYSE, **When** scheduler déclenche, **Then** aucun scan exécuté, aucun message Telegram envoyé
4. **Given** FMP indisponible (clé absente ou 5xx persistant après 2 retries), **When** scan déclenché, **Then** message Telegram `⚠️ Sniper FMP indisponible` envoyé, aucun signal émis
5. **Given** message Telegram > 4096 chars, **When** envoi, **Then** message tronqué avec `[message tronqué]` — pas d'erreur API Telegram

---

### User Story 2 — Filtre de régime marché (Priorité : P1)

Le système détecte le régime de marché avant chaque scan et adapte son comportement : silence total en panique réelle (VIX > 35), avertissement en stress modéré, scan normal sinon.

**Test indépendant** : Mocks SPY/VIX aux 4 niveaux → vérifier comportement exact.

**Scénarios d'acceptation** :

1. **Given** VIX > 35 (quelle que soit la position SPY vs EMA200), **When** scan déclenché, **Then** scan annulé, `🚨 RÉGIME DE PANIQUE`, 1 entrée `regime='panic'` dans `scans`, 0 entrée dans `signals`
2. **Given** SPY < EMA200 ET VIX entre 25 et 35, **When** scan exécuté, **Then** chaque signal Top 10 contient flag `⚠️ RÉGIME DE PRUDENCE`
3. **Given** SPY < EMA200 ET VIX ≤ 25, **When** scan exécuté, **Then** scan normal, warning log interne uniquement
4. **Given** SPY ≥ EMA200 ET VIX ≤ 25, **When** scan exécuté, **Then** scan complet, Top 10 émis sans flag de régime

---

### User Story 3 — Entonnoir qualité données (Priorité : P2)

Filtre d'éligibilité strict sur ~700 tickers, scoring sur les 30 meilleurs en momentum. Seules des données fraîches et fiables entrent dans le scoring.

**Test indépendant** : Injecter tickers avec données manquantes, vieilles, secteur=None → vérifier exclusions + logs.

**Scénarios d'acceptation** :

1. **Given** `marketCap < 2B$` ou `volume_dollar_20j < 5M$` ou `price < 5$`, **When** filtre éligibilité, **Then** ticker exclu, loggé `eligibility_filter`
2. **Given** `sector = None` (yfinance), **When** pipeline Actions, **Then** exclu avec motif `sector_missing`
3. **Given** données FMP > 120 jours, **When** ticker dans Top 10, **Then** flag `⚠️ données potentiellement périmées`
4. **Given** données FMP > 180 jours, **When** ranking final, **Then** ticker exclu du Top 10
5. **Given** univers post-chalutier < 100 tickers, **When** scoring déclenché, **Then** scan annulé, warning log `universe_too_small`
6. **Given** secteur < 3 tickers dans la shortlist scorée, **When** ranking intra-secteur, **Then** bascule automatique vers ranking cross-universe

---

### User Story 4 — Persistance et suivi de performance (Priorité : P2)

Chaque scan enregistré en SQLite. Les signaux Top 10 stockés avec prix au signal. Job de fond met à jour retour 30j/90j.

**Test indépendant** : 2 scans successifs → vérifier tables `scans` et `signals` avec champs obligatoires.

**Scénarios d'acceptation** :

1. **Given** scan complété, **When** Top 10 émis, **Then** 1 entrée `scans` + ≤ 10 entrées `signals` avec `price_at_signal` non-null
2. **Given** ticker réapparaît dans Top 10 après absence, **When** stockage, **Then** `first_seen_date` conservée (non réinitialisée)
3. **Given** signal ≥ 30 jours, **When** `update_signal_returns()` exécuté, **Then** `price_30d_later` et `return_30d` mis à jour (yfinance seul, aucun appel FMP)
4. **Given** scan en régime Panique, **When** exécuté, **Then** 1 entrée `scans` avec `regime='panic'`, 0 entrée `signals`

---

### User Story 5 — ETFs sectoriels en pipeline séparé (Priorité : P3)

ETFs scorés sur momentum pur (sector rotation), pipeline et section Telegram séparés, leveraged/inverses exclus.

**Test indépendant** : TQQQ (leveraged) → exclu. XLK → scoré. Section Telegram distincte vérifiée.

**Scénarios d'acceptation** :

1. **Given** ETF avec "ULTRA", "3X", "BEAR" dans le nom, **When** pipeline ETF, **Then** exclu
2. **Given** Top 5 ETFs scorés, **When** message Telegram, **Then** section `📦 TOP ETFs DU JOUR` séparée des Actions
3. **Given** ETF scoré, **When** scoring, **Then** `score = 50% Perf 6M + 50% Surperf vs SPY`, aucune métrique fondamentale

---

### Cas limites (Edge Cases)

- `book_value_per_share ≤ 0` : ticker exclu du pilier Qualité (ROE mathématiquement sans sens)
- `ROE > 150%` avec `book_value_per_share < 5$` : flag `⚠️ ROE possiblement gonflé par buybacks`, score ROE plafonné au percentile 80
- `EBITDA ≤ 0` ou `Dette/EBITDA > 6x` : exclusion inconditionnelle
- `P/E Forward absent (~40-60% des tickers)` : fallback P/E TTM avec pénalité -5 pts sur pilier Valorisation
- `P/E Forward ET P/E TTM absents` : pilier Valorisation exclu, repondération `Qualité × 0.50 + Momentum × 0.50`
- Secteurs Financials / Real Estate / Utilities : exclusion Dette/EBITDA du pilier Qualité
- Biotech (Health Care, marketCap < 5B$) : gate P/E négatif suspendu
- Earnings dans les 14 prochains jours : tag `📅 Earnings à venir` (informatif, non bloquant)
- yfinance batch download partiel (< 60% tickers valides) : scan interrompu, alerte Telegram erreur

---

### Exigences Fonctionnelles

- **FR-001** : Le scan DOIT s'exécuter uniquement les jours de bourse NYSE (via `pandas_market_calendars`)
- **FR-002** : Le Market Gate DOIT évaluer VIX et SPY/EMA200 en priorité absolue avant tout scoring
- **FR-003** : `yfinance` NE DOIT PAS être utilisé pour ROE, marges, FCF, ou toute donnée bilancielle
- **FR-004** : FMP DOIT être utilisé pour les 7 endpoints de la shortlist (30 tickers max, 210 calls nominaux)
- **FR-005** : Si FMP indisponible → Telegram `⚠️ Sniper FMP indisponible` + scan arrêté — aucun fallback yfinance fondamentaux
- **FR-006** : Scoring Actions = 3 piliers (Qualité 35%, Valorisation 30%, Momentum 35%) avec percentile ranking
- **FR-007** : Scoring Momentum = 5 critères incluant révision estimations analystes (FMP `analyst-estimates`)
- **FR-008** : Earnings Surprise DOIT avoir décroissance temporelle linéaire sur 90 jours post-résultats
- **FR-009** : Ranking intra-secteur DOIT basculer en cross-universe si secteur a < 3 tickers dans la shortlist
- **FR-010** : Tous les messages Telegram DOIVENT être html.escape()'és et tronqués à 4096 chars max
- **FR-011** : SQLite WAL mode OBLIGATOIRE pour l'accès concurrent bot/dashboard
- **FR-012** : Toutes les constantes métier DOIVENT être dans `config.yaml` (pas de magic numbers dans le code)

### Critères de Succès Mesurables

- **SC-001** : Budget FMP ≤ 250 calls/jour en conditions nominales
- **SC-002** : Durée totale du scan ≤ 15 minutes de 09h35 ET à réception Telegram
- **SC-003** : `score_global` ∈ [0, 100] pour chaque ticker du Top 10, jamais NaN
- **SC-004** : Aucun scan ne crash silencieusement — toute erreur critique produit un message Telegram
- **SC-005** : 100% des tests passent en isolation réseau (VCR cassettes, aucun appel API live)
- **SC-006** : Après 90 jours, `SELECT avg(return_30d) FROM signals` retourne un résultat calculable

---

## Spécifications Techniques Complètes

---

## 1. Vue d'ensemble du système

```
Nom du projet    : ValueMomentum Scanner
Version          : 1.0
Horizon cible    : Position Trading (Hold) — 3 à 6 mois (sweet spot momentum académique)
Type de stratégie : Investissement Quantitatif Factoriel (Quality × Momentum)
Fréquence        : Quotidienne (jours de bourse US uniquement)
Déclenchement    : 09h30 ET (après ouverture NYSE)
Sortie principale : Alertes Telegram + Base de données SQLite (`scanner_history.db`)
Environnement    : Mac Mini (serveur local), macOS
Langage          : Python 3.11+

### Synthèse de l'Horizon de Trading

Le bot est conçu pour le **Position Trading**. Contrairement à l'Intraday (scalping, day trading) ou au Swing Trading classique (quelques jours), cette stratégie vise à capturer des tendances de fond sur plusieurs **trimestres**.
- **Style** : "Buy and Hold" dynamique.
- **Vecteur de temps** : On ne cherche pas le profit immédiat, mais la convergence de la Qualité fondamentale et du Momentum de prix.
- **Rotation** : Le portefeuille est réévalué quotidiennement mais la rotation réelle des titres s'effectue généralement tous les 3 à 6 mois.
```

> **Jours de bourse vs jours ouvrés** : APScheduler déclenche sur `cron` lundi-vendredi mais ignore les jours fériés NYSE (Thanksgiving, Christmas, MLK Day, etc.). Avant chaque scan, vérifier via `pandas_market_calendars` :
>
> ```python
> import pandas_market_calendars as mcal
> nyse = mcal.get_calendar("NYSE")
> schedule = nyse.schedule(start_date=today, end_date=today)
> if schedule.empty:
>     logger.info(f"Jour férié NYSE {today} — scan annulé")
>     return
> ```

---

## 2. Architecture générale : L'Entonnoir (Funnel)

Pour maximiser l'univers tout en garantissant la qualité institutionnelle des signaux finaux sans coût d'API, le système adopte une architecture asymétrique :

### Étape 1 : Le Chalutier (yfinance)

- **Cible** : ~700 tickers.
- **Action** : Batch download des prix historiques (OHLCV).
- **Filtres** : Liquidité, Market Cap, Momentum (3M, 6M, Relatif).
- **Sortie** : Une "Shortlist" des **30 meilleurs** potentiels techniques.

### Étape 2 : Le Sniper (API Officielle - ex: FMP)

- **Cible** : Le **Top 30** issu du Chalutier.
- **Action** : Fetch des fondamentaux propres via API versionnée.
- **Calcul** : Qualité (ROE, Marges, Dette/EBITDA) et Valorisation (P/E, PEG).
- **Sortie** : Le Top 10 final envoyé sur Telegram.

> **Bénéfice** : Cette méthode protège contre le rate-limiting de yfinance (car les appels `.info` sont limités à 50) et contre l'imprécision des données gratuites sur les actions que vous allez réellement acheter.

> **Contrainte FMP free tier (250 calls/jour) — CRITIQUE** : Le tier gratuit FMP est **limité à 250 appels/jour**, sans possibilité d'upgrade. Budget alloué par run :
>
> | Endpoint FMP                               | Appels (30 tickers) | Objet                                              |
> | ------------------------------------------ | ------------------- | -------------------------------------------------- |
> | `ratios-ttm/{symbol}`                      | 30                  | P/E, EV/EBITDA, marge op., FCF yield, dette/EBITDA |
> | `key-metrics-ttm/{symbol}`                 | 30                  | ROE TTM, métriques complémentaires                 |
> | `profile/{symbol}`                         | 30                  | Secteur GICS, market cap, description              |
> | `income-statement/{symbol}?limit=3`        | 30                  | ROE moyen 3 ans (annuels)                          |
> | `balance-sheet-statement/{symbol}?limit=1` | 30                  | Bilan : totalDebt, totalCash                       |
> | `earnings-surprises/{symbol}`              | 30                  | Surprise Earnings %                                |
> | `analyst-estimates/{symbol}`               | 30                  | Révision estimations analystes 3M                  |
> | **Total**                                  | **210 calls/run**   | Marge : 40 calls pour retries ciblés               |
>
> **SHORTLIST_SIZE = 30 est non négociable** : 30 × 7 endpoints = 210 calls nominaux. Avec cache 27h actif sur les tickers non-earnings, les retries ne concernent qu'une minorité. Circuit-breaker à **2 retries max** (pas 3) : si un ticker échoue 2 fois → skip + flag, pas de 3ème tentative. Budget réel estimé : 210 calls nominaux + ~15 retries = 225 calls/run. Ne pas dépasser 30 tickers sans audit budget préalable.
>
> **Disjoncteur global FMP (hard limit 245 calls)** : Le système DOIT maintenir un compteur global d'appels FMP par run (`fmp_call_counter`). Dès que ce compteur atteint **245 calls**, les fetches FMP des tickers restants sont interrompus immédiatement. Le scoring et le ranking sont finalisés avec les données disponibles à ce moment. Un flag `⚠️ Budget FMP proche du quota — shortlist partielle` est ajouté au message Telegram. Cette limite de 245 (non 250) conserve 5 calls de marge pour les éventuels retries de notification Telegram et les opérations de fin de run.
>
> ```python
> FMP_CALL_BUDGET_HARD_LIMIT = 245  # Disjoncteur — 5 calls de marge sur quota 250
>
> fmp_call_counter = 0
>
> async def fmp_fetch(endpoint: str, symbol: str) -> dict:
>     global fmp_call_counter
>     if fmp_call_counter >= FMP_CALL_BUDGET_HARD_LIMIT:
>         logger.warning(f"Budget FMP atteint ({fmp_call_counter} calls) — skip {symbol}/{endpoint}")
>         return {}
>     fmp_call_counter += 1
>     # ... appel HTTP normal ...
> ```
>
> **Si FMP est indisponible (clé absente ou erreur 5xx persistante)** : envoyer une alerte Telegram `🚨 Sniper FMP indisponible — aucun signal émis aujourd'hui` et arrêter le scan. **Aucun fallback vers yfinance pour les fondamentaux** — cf. Règle d'Or du besoin.

---

## 3. Module 1 — Universe Builder

### 3.1 Univers de départ (Master List & Refresh Automatique)

L'univers est géré via un fichier JSON central (`tickers_universe.json`). Contrairement à la v1 initiale, le système supporte désormais le **rafraîchissement automatique** via `scanner/refresh_universe.py`.

- **S&P 500** : Import automatique depuis Wikipedia.
- **Nasdaq 100** : Import automatique.
- **Indices Mondiaux** : _(Roadmap v2 uniquement)_ — NIFTY 50 (.NS), MSCI World, CAC 40, DAX. En v1.0, l'univers est **strictement limité aux actions US** (NYSE / NASDAQ / AMEX). Tout ticker `.NS` ou hors-US présent dans `tickers_universe.json` sera éliminé par le filtre listing — ne pas les inclure pour éviter du fetch inutile.
- **Mode Explorer** : _(Roadmap v2)_ Import de tableaux Wikipedia via URL custom.

### 3.2 Filtres d'éligibilité obligatoires (appliqués chaque jour)

Les filtres suivants éliminent les instruments non tradables avant toute analyse :

| Filtre                | Seuil                           | Source                  | Raison                              |
| --------------------- | ------------------------------- | ----------------------- | ----------------------------------- |
| Market Cap minimum    | > 2 000 M$                      | yfinance `marketCap`    | Éviter les micro-caps volatiles     |
| Volume moyen 20j      | > 5 000 000 $                   | yfinance OHLCV          | Exécutable institutionnel           |
| Prix unitaire         | > 5.00 $                        | yfinance `currentPrice` | Éviter zones penny stock            |
| Listing               | NYSE / NASDAQ / AMEX            | yfinance `exchange`     | Exclure OTC, marchés exotiques      |
| Ancienneté données    | > 2 ans d'historique disponible | yfinance date min       | Track record minimum value          |
| Données fondamentales | Disponibles et < 180 jours      | yfinance `financials`   | Données trop vieilles = non fiables |

> **Note technique** : Le filtre volume se calcule comme `avg(volume_20j) × avg(close_20j)`. Ne pas utiliser le volume brut (actions) mais le volume en dollars.

> **Application aux ETFs** : Les ETFs n'ont pas de données fondamentales au sens action (P/E, ROE, etc.). Le filtre "Données fondamentales" ne s'applique PAS aux ETFs — ils passent directement vers le pipeline ETF après les 5 premiers filtres (market cap, volume, prix, listing, ancienneté prix). Le filtre ancienneté utilise l'historique de prix (2 ans d'OHLCV), applicable aux ETFs.

> **Secteur GICS manquant (sector = None)** : Source de vérité = champ `sector` yfinance (`.info["sector"]`). Si la valeur est `None` ou absente (~5-10% des tickers), le ticker est **exclu du scoring Actions** — il ne peut pas être comparé à ses pairs sectoriels pour P/E, EV/EBITDA et Marge opérationnelle, rendant son score incomparable. L'exclusion doit être loggée avec le motif `"sector_missing"`. Ces tickers restent dans l'univers pour les runs suivants (le champ peut être alimenté après mise à jour yfinance).

---

## 3bis. Module 2 — Data Fetcher

### 2.1 Stratégie de fetch asynchrone (Non-bloquant)

Pour garantir que l'Event Loop d'asyncio ne gèle jamais (notamment pour les notifications Telegram et le scheduler), le fetcher utilise une approche hybride :

**Fetch prix OHLCV (yfinance via Threads — téléchargement par chunks obligatoire) :**
`yfinance` étant purement synchrone, ses appels sont enveloppés dans des threads pour ne pas bloquer la boucle principale. Le batch download sur ~700 tickers en un seul appel déclenche systématiquement des erreurs HTTP 429 (ban IP temporaire). Le téléchargement DOIT être découpé en chunks de **100 tickers maximum** avec une pause de **2 secondes** entre chaque chunk.

```python
import asyncio
import yfinance as yf

YFINANCE_CHUNK_SIZE = 100        # Tickers par batch — au-delà, risque 429 élevé
YFINANCE_CHUNK_DELAY_S = 2.0     # Pause entre chunks (secondes)

async def fetch_prices_chunked(tickers: list[str], period: str = "1y") -> dict:
    """Télécharge les prix OHLCV par chunks pour éviter le ban IP yfinance."""
    all_prices = {}
    chunks = [tickers[i:i + YFINANCE_CHUNK_SIZE] for i in range(0, len(tickers), YFINANCE_CHUNK_SIZE)]

    for i, chunk in enumerate(chunks):
        chunk_data = await asyncio.to_thread(
            yf.download,
            tickers=" ".join(chunk),
            period=period,
            group_by="ticker",
            auto_adjust=True,
            threads=False,     # Pas de multi-thread interne yfinance (amplifie les 429)
            progress=False
        )
        all_prices.update(chunk_data)

        if i < len(chunks) - 1:
            await asyncio.sleep(YFINANCE_CHUNK_DELAY_S)  # Pause entre chunks

    return all_prices
```

> **Pourquoi `threads=False` en interne** : `yf.download(threads=True)` ouvre plusieurs connexions simultanées vers Yahoo Finance depuis le même IP. Combiné à ~700 tickers, cela simule une attaque DDoS du point de vue des serveurs Yahoo, déclenchant un ban immédiat. Avec `threads=False` + chunks de 100 + pause 2s, le profil de requêtes ressemble à un navigateur humain naviguant rapidement — acceptable pour Yahoo Finance.

> **Session User-Agent rotatif** : Pour réduire davantage le risque de détection, les sessions yfinance peuvent être instanciées avec des User-Agents différents par chunk (via `yf.Ticker._session`). En v1.0, la rotation est optionnelle — la stratégie de chunking seule est suffisante pour l'univers ~700 tickers.

> **Fallback batch partiel** : Si un chunk retourne < 60% de tickers valides (`len(valid) / len(chunk) < 0.6`), logguer `⚠️ batch_partial_failure` et continuer — ne pas annuler le scan entier pour un chunk défaillant. Si **tous** les chunks échouent sous 60% : déclencher l'arrêt du scan + alerte Telegram erreur yfinance (cf. §13.4).

**Fetch fondamentaux (httpx pour FMP) :**
L'API FMP est interrogée via `httpx.AsyncClient` pour une asynchronicité native.

```python
async with httpx.AsyncClient() as client:
    response = await client.get(f"{base_url}/ratios-ttm/{symbol}?apikey={api_key}")
    data = response.json()
```

### 2.2 Rate limiting et résilience

Le système applique un **Rate Limiting Séquentiel** strict pour éviter le bannissement IP (Erreur 429) :

1. **Délai asynchrone jittered** : Entre chaque appel `.info` (yfinance) ou API (FMP), un délai aléatoire compris entre **0.8s et 1.5s** (`await asyncio.sleep(random.uniform(0.8, 1.5))`) est observé pour simuler un comportement humain et éviter le bannissement IP.
2. **INTER_REQUEST_DELAY** : Fixé à 1.0s par défaut pour garantir la pérennité de l'accès Yahoo Finance.
3. **FMP_MAX_RETRIES** : **2 tentatives maximum** avec backoff exponentiel asynchrone (cf. §2 budget FMP — 3 retries dépasserait le budget 250 calls).
4. **Aucun fallback FMP → yfinance** : Si FMP échoue après 2 retries pour un ticker, le ticker est ignoré (skip + flag dans les logs). La Règle d'Or est absolue — voir §16 contrainte 1.

### 2.3 Validation des données reçues

```python
def is_valid_ticker_data(data: dict) -> bool:
    price = data.get("regularMarketPrice")  # None-safe check
    return price is not None and price > 0
```

> **Important** : `"regularMarketPrice" in data` est insuffisant — la clé peut exister avec valeur None. Toujours utiliser `.get()` + check de valeur.

### 2.4 Cache

```python
CACHE_TTL_FUNDAMENTALS = 27 * 3600   # 27h — voir note race condition ci-dessous
CACHE_TTL_PRICE_HISTORY = 4 * 3600   # 4h — prix plus frais pour le momentum
```

> **⚠️ Race condition TTL à 24h** : Le scan se déclenche à 09h35 ET. Un cache créé à 09h32 la veille expire exactement à 09h32 le lendemain — 3 minutes *avant* le prochain scan. Toute la shortlist de 30 tickers déclenche simultanément 210 appels FMP à 09h35 ET, annulant le bénéfice du cache et consommant l'intégralité du quota en un seul run. TTL à **27h** garantit que le cache reste valide pour le scan suivant, quel que soit le délai d'exécution réel (congestion réseau, retry, heure d'été/hiver). La valeur `97200s` (27×3600) est la valeur de référence dans `config.yaml`.

**Invalidation post-earnings** : si un ticker est dans l'earnings calendar avec date = J-1 (résultats publiés la veille), son cache fondamentaux est invalidé forcément avant le scan.

**Structure cache entry :**

```json
{
  "ticker": "MSFT",
  "fetched_at": "2025-01-15T09:32:00Z",
  "expires_at": "2025-01-16T12:32:00Z",
  "data": { "...": "..." }
}
```

### 2.5 Bootstrap tickers_universe.json

Fichier créé une fois manuellement. Structure :

```json
{
  "stocks": ["AAPL", "MSFT", "..."],
  "etfs": ["XLK", "XLV", "SPY", "..."]
}
```

**Sources pour la liste initiale :**

- S&P 500 : Wikipedia `List of S&P 500 companies` (table HTML parseable via pandas)
- Russell 1000 : disponible sur le site iShares (ETF IWB) — fichier CSV téléchargeable
- ETFs : liste manuelle des SPDR sectoriels + ETFs thématiques majeurs

Script de bootstrap suggéré (à exécuter une fois) :

```python
import pandas as pd
sp500 = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]["Symbol"].tolist()
# Sauvegarder dans tickers_universe.json
```

Mise à jour mensuelle manuelle (±5 min de travail) : ajouter/supprimer les entrants/sortants de l'indice.

---

## 4. Module 3 — Scoring Engine

### 4.0 Filtre de Régime (Market Gate) — PRIORITÉ SURVIE

Pour éviter l'effet de "Whipsaw" (oscillations autour d'une moyenne simple), le système utilise un double filtre de stress à **quatre niveaux** :

- **Indicateurs** : Moyenne Mobile Exponentielle 200 jours (EMA 200) du SPY + Indice de Volatilité (VIX).

Les conditions sont évaluées **dans l'ordre de priorité suivant** (first match wins) :

| Priorité | Condition                                         | Régime         | Comportement                                                                        |
| -------- | ------------------------------------------------- | -------------- | ----------------------------------------------------------------------------------- |
| 1        | VIX > 35 (quelle que soit la position SPY/EMA200) | **Panique**    | Scan annulé + alerte Telegram `🚨 RÉGIME DE PANIQUE : EXPOSITION DÉCONSEILLÉE`      |
| 2        | SPY < EMA200 **ET** VIX entre 25 et 35            | **Prudence**   | Scan complet + flag `⚠️ RÉGIME DE PRUDENCE : VOLATILITÉ ÉLEVÉE` sur chaque signal   |
| 3        | SPY < EMA200 **ET** VIX ≤ 25                      | **Bear Light** | Scan normal + log warning interne uniquement (pas de flag sur les signaux Telegram) |
| 4        | SPY ≥ EMA200 **ET** VIX ≤ 25                      | **Normal**     | Scan complet, Top 10 émis normalement                                               |

> **Pourquoi VIX > 35 déclenche la Panique quelle que soit la position du SPY** : L'EMA200 réagit avec un lag de plusieurs semaines. Début de crise (mars 2020 J+1 à J+7), le VIX était déjà à 40-80 alors que le SPY était encore au-dessus de son EMA200. Sans priorité sur le VIX, le bot émettrait des signaux "Normal" pendant un choc de volatilité extrême. Le VIX est le signal avancé de panique, l'EMA200 est le signal retardé de tendance — le VIX prévaut.
>
> **Pourquoi VIX > 35 et non > 25** : En 2022, le VIX est resté au-dessus de 25 pendant plus de 8 mois consécutifs. Le seuil de 35 correspond à une panique réelle (COVID 2020, Lehman 2008), pas à une nervosité de marché. Entre 25 et 35, les signaux sont émis avec avertissement — l'utilisateur décide.
>
> **Scan annulé en mode Panique** : la table `scans` en SQLite reçoit quand même une entrée avec `regime='panic'`. La table `signals` ne reçoit aucune entrée. Le Telegram envoie uniquement le message d'alerte de panique (voir section 6.3).

### 4.1 Pipeline Actions : définition des critères

#### PILIER 1 : QUALITÉ (pondération 35%)

| Métrique             | Source               | Calcul                                                             | Ranking            |
| -------------------- | -------------------- | ------------------------------------------------------------------ | ------------------ |
| ROE (Moyenne 3 ans)  | **API FMP (Sniper)** | Moyenne du ROE sur les 3 derniers bilans (income + balance)        | Cross-universe     |
| Marge opérationnelle | **API FMP (Sniper)** | `operatingProfitMarginTTM` via `ratios-ttm`                        | Intra-secteur GICS |
| Dette nette / EBITDA | **API FMP (Sniper)** | `netDebt` / `ebitda` — exclus : Financials, Real Estate, Utilities | Cross-universe     |
| FCF Yield proxy      | **API FMP (Sniper)** | `freeCashFlowTTM` (key-metrics-ttm) / marketCap                    | Cross-universe     |

> **Note ROE** : L'utilisation du ROE TTM est proscrite car potentiellement faussée par des effets de levier ou des cessions exceptionnelles. Le calcul moyen sur 3 ans est **obligatoire** et récupéré via les endpoints `income-statement` et `balance-sheet-statement` de l'API FMP.

> **Note secteurs exclus du calcul dette/EBITDA** : Financières (banques, assurances) et REITs ont des structures bilancielles incompatibles avec ce ratio. Traitement spécifique documenté en section 4.4.

**Règle de qualité minimale (gate, non scoré) :**

- ROE < 0% → ticker exclu du scoring (business structurellement défaillant)
- `book_value_per_share ≤ 0` → ticker exclu du scoring qualité (ROE mathématiquement non interprétable)
- ROE > 150% avec `book_value_per_share < 5$` → flag `⚠️ ROE possiblement gonflé par buybacks` (non exclu, mais score ROE plafonné au percentile 80)
- EBITDA ≤ 0 → ticker exclu (ratio dette/EBITDA sans sens + business déficitaire)
- Dette nette / EBITDA > 6x → exclu (risque bilan trop élevé)

> **Pourquoi le filtre book_value et ROE > 150%** : Le ROE = Net Income / Book Equity. Des programmes massifs de rachats d'actions réduisent le Book Equity jusqu'à le rendre négatif ou quasi-nul, produisant des ROE de 100-500% qui ne reflètent pas l'excellence opérationnelle mais le levier comptable. Apple (ROE ~160%), MSFT (~35% stable), sans ce filtre, dominent le percentile Qualité pour la mauvaise raison. Un `book_value_per_share ≤ 0` rend le ROE mathématiquement sans sens et doit exclure le titre du pilier Qualité.

**Winsorisation des ratios avant percentile ranking (obligatoire) :**

Avant tout calcul de percentile, les ratios bruts DOIVENT être clampés dans des plages réalistes. Des erreurs d'API (ex: FMP retourne `0.001` ou `999` pour un ratio en erreur de parsing) ou des cas extrêmes légitimes mais statistiquement aberrants (ex: ROE = 500% post-restructuration) corrompent le ranking entier si non traités.

```python
RATIO_CLAMP = {
    "roe":               (0.0, 1.50),    # 0% à 150% — au-delà → gate buyback flag
    "operating_margin":  (-0.50, 0.60),  # -50% à +60% — marges au-delà sont anomalies
    "fcf_yield":         (-0.20, 0.30),  # -20% à +30%
    "debt_ebitda":       (0.0, 10.0),    # 0x à 10x — au-delà → gate exclusion à 6x déjà
    "pe_ratio":          (1.0, 60.0),    # P/E ≤ 1 ou > 60 → anomalie de parsing FMP
    "ev_ebitda":         (0.0, 40.0),    # 0x à 40x — gate exclusion à 40 déjà
    "peg_ratio":         (-5.0, 5.0),    # PEG hors [-5, 5] = signal non interprétable
}

def winsorize(value: float, low: float, high: float) -> float:
    """Clamp à la plage [low, high]. Valeurs hors plage = anomalies de données, pas de signaux."""
    return max(low, min(high, value))
```

> **Pourquoi winsoriser et non exclure** : Les gates d'exclusion (ROE < 0, EV/EBITDA > 40) éliminent les cas inacceptables. La winsorisation traite les valeurs aberrantes qui passent les gates mais perturberaient le ranking — un EV/EBITDA de 39.8 est valide mais si l'autre extrême est 0.01 (erreur de parsing), le percentile de 39.8 plafonne artificiellement tous les tickers intermédiaires. Le clamping nivelle les extremes sans exclure les tickers.

**Score Qualité** = moyenne pondérée des 4 percentile rangs

- ROE (Moyenne 3 ans) : 40%
- Marge opérationnelle : 35%
- FCF Yield proxy : 15%
- Dette/EBITDA (inversé) : 10%

---

#### PILIER 2 : VALORISATION (pondération 30%)

| Métrique    | Source               | Champ FMP                    | Calcul                    | Ranking            |
| ----------- | -------------------- | ---------------------------- | ------------------------- | ------------------ |
| P/E Forward | **API FMP (Sniper)** | `peRatioTTM` (ratios-ttm)    | Valeur directe (inversée) | Intra-secteur GICS |
| EV/EBITDA   | **API FMP (Sniper)** | `enterpriseValueMultipleTTM` | Valeur directe (inversée) | Intra-secteur GICS |
| PEG Ratio   | **API FMP (Sniper)** | `pegRatioTTM`                | Valeur directe (inversée) | Cross-universe     |

**Règles gates valorisation (filtres d'exclusion, non scorés) :**

- P/E Forward > 50 → exclu sauf si secteur = Technology ou Health Care (inclut Biotech, seuil 80)
- P/E Forward négatif → exclu (pertes prévues) — exception : si P/E Forward absent ET P/E TTM disponible, voir gestion données manquantes ci-dessous
- EV/EBITDA > 40 → exclu

**Score Valorisation** = moyenne pondérée des percentile rangs inversés (un P/E BAS = bon score)

- P/E Forward inversé : 45%
- EV/EBITDA inversé : 35%
- PEG inversé : 20%

> **Gestion données manquantes** :
>
> - **P/E Forward absent (cas fréquent, ~40-60% des tickers yfinance)** → utiliser P/E TTM **par défaut** (pas comme fallback exceptionnel) avec pénalité de -5 points sur le **score pilier Valorisation**. Si P/E TTM aussi négatif → appliquer le gate P/E négatif normalement.
> - Aucun P/E disponible → pilier Valorisation exclu. Score global recalculé : `score_qualite * 0.50 + score_momentum * 0.50` (renormalisé sur 100). Flag `⚠️ Valorisation non calculée` ajouté.
> - PEG Ratio absent (fréquent) → critère PEG exclu du pilier. Les 20% sont redistribués : P/E Forward → 56%, EV/EBITDA → 44%.
>
> **Pourquoi P/E TTM comme défaut** : En pratique, yfinance retourne `forwardPE = None` pour 40 à 60% des tickers, ce qui en fait l'exception plutôt que la règle. Traiter le TTM comme fallback "dégradé" introduit une incohérence : certains tickers sont scorés sur Forward, d'autres sur TTM, sans que le classement le reflète clairement. La pénalité -5 pts sur le pilier Valorisation est conservée pour signaler que la précision est moindre (P/E TTM regarde le passé, pas les bénéfices futurs attendus).
>
> **Règle NaN dans percentile ranking** : tout sous-critère avec valeur NaN ou manquante est exclu du calcul du percentile pour ce ticker. Si plus de 2 sous-critères d'un pilier sont NaN, le pilier entier est exclu (voir logique de repondération ci-dessus).

---

#### PILIER 3 : MOMENTUM (pondération 35%)

| Métrique                          | Calcul                                            | Source                   | Ranking        |
| --------------------------------- | ------------------------------------------------- | ------------------------ | -------------- |
| Performance 6 mois                | (Prix J0 - Prix J-126) / Prix J-126               | yfinance                 | Cross-universe |
| Surperformance sectorielle 6M     | Perf 6M ticker - Perf 6M ETF sectoriel SPDR       | yfinance                 | Intra-secteur  |
| Performance 3 mois                | (Prix J0 - Prix J-63) / Prix J-63                 | yfinance                 | Cross-universe |
| Surprise Earnings % (Sniper)      | (BPA Publié - BPA Attendu) / BPA Attendu          | FMP `earnings-surprises` | Cross-universe |
| Révision estimations analystes 3M | % de variation médiane des EPS forward sur 3 mois | FMP `analyst-estimates`  | Cross-universe |

> **Note Momentum Fondamental** : Deux signaux fondamentaux complémentaires :
>
> - **Surprise Earnings %** (backward) : la dernière publication a-t-elle battu les attentes ? Signal fort immédiatement post-résultats, décroissant avec le temps (voir formule ci-dessous).
> - **Révision estimations 3M** (forward) : les analystes ont-ils révisé leurs estimations de BPA à la hausse sur les 3 derniers mois ? Signal d'accélération fondamentale anticipée, stable dans le temps. Calcul : `(median_eps_estimate_now - median_eps_estimate_3M_ago) / abs(median_eps_estimate_3M_ago)`.
>
> **Décroissance temporelle du signal Earnings Surprise** : Une surprise positive enregistrée il y a 90 jours est déjà intégrée dans le prix. Le poids de ce critère décroît linéairement, et les poids libérés sont redistribués proportionnellement aux 4 autres critères :
>
> ```python
> days_since_earnings = (today - last_earnings_date).days
> surprise_weight = 0.15 * max(0.0, 1.0 - (days_since_earnings / 90))
> # Poids = 0.15 à J+0, = 0.075 à J+45, = 0 à J+90 et au-delà
>
> # Redistribution proportionnelle des poids libérés aux 4 autres critères
> # Base sans surprise : perf_6m=0.30, outperf_6m=0.30, perf_3m=0.15, revision=0.10 → total=0.85
> remaining_weight = 1.0 - surprise_weight
> factor = remaining_weight / 0.85
> w_perf_6m    = 0.30 * factor
> w_outperf_6m = 0.30 * factor
> w_perf_3m    = 0.15 * factor
> w_revision   = 0.10 * factor
> # Vérification : w_perf_6m + w_outperf_6m + w_perf_3m + w_revision + surprise_weight = 1.0
> ```
>
> **Pourquoi** : Sans cette décroissance, une entreprise ayant battu les attentes en octobre continue d'être récompensée en janvier pour un signal dont le marché a déjà fait le prix. La Révision estimations n'a pas de décroissance — les révisions d'analystes reflètent une conviction continue, pas un événement ponctuel.

**Benchmarks sectoriels SPDR utilisés pour la surperformance :**

```python
SECTOR_ETF_MAP = {
    "Technology": "XLK",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
    "Unknown": "SPY"  # fallback
}
```

**Ajustement anti-momentum extrême :**

Les pénalités s'appliquent sur le **score momentum final** (après calcul de la moyenne pondérée des 4 sous-critères, avant intégration dans le score global). Le score momentum est clampé à [0, 100] après application des pénalités.

- Si performance 1 mois > +25% → pénalité -10 points sur score momentum (probable mean reversion court terme)
- Si performance 1 mois < -20% → pénalité -5 points (momentum négatif récent)
- Les deux conditions peuvent s'appliquer simultanément (cumul des pénalités)

**Score Momentum** = moyenne pondérée (poids nominaux — avant décroissance earnings) :

- Surperf sectorielle 6M : 30%
- Perf 6 mois : 30%
- Perf 3 mois : 15%
- Surprise Earnings % : 15% _(décroissance temporelle appliquée — voir formule)_
- Révision estimations analystes 3M : 10%

---

### 4.2 Score Global Actions

```python
# Cas nominal (tous piliers disponibles)
score_global = (
    score_qualite * 0.35 +
    score_valorisation * 0.30 +
    score_momentum * 0.35
)

# Cas valorisation exclue (P/E et EV/EBITDA tous absents)
score_global = (
    score_qualite * 0.50 +
    score_momentum * 0.50
)

# Résultat : float entre 0 et 100 dans tous les cas
# Score momentum est clampé à [0, 100] avant intégration (voir pénalités anti-extrême)
```

---

### 4.3 Pipeline ETFs (score momentum pur — sector rotation)

Pour les ETFs, le scoring est purement asymétrique et se concentre sur l'action des prix, excluant le volume (potentiellement toxique en cas de panique) :

| Critère            | Calcul                              | Pondération |
| ------------------ | ----------------------------------- | ----------- |
| Performance 6 mois | (Prix J0 - Prix J-126) / Prix J-126 | 50%         |
| Surperf vs SPY 6M  | Perf 6M ETF - Perf 6M SPY           | 50%         |

> **Note Volume** : Le critère de volume a été supprimé. Une hausse de volume sur un ETF peut signifier une panique vendeuse (liquidation). Le scoring se concentre sur la surperformance relative et le momentum lissé.

**Filtre d'exclusion ETFs à effet de levier et inverses (obligatoire avant scoring) :**

```python
EXCLUDED_ETF_PATTERNS = [
    "3X", "2X", "-3", "-2",           # Levier 2x/3x
    "ULTRA", "ULTRA SHORT",            # ProShares leveraged
    "BEAR", "SHORT", "INVERSE",        # Inverses
    "DAILY", "PROSHARES"               # Fréquemment leveraged
]

def is_eligible_etf(ticker: str, name: str) -> bool:
    name_upper = name.upper()
    return not any(pat in name_upper for pat in EXCLUDED_ETF_PATTERNS)
```

> **Pourquoi** : Un ETF leveraged 3× (ex: TQQQ, SOXL) domine systématiquement le classement momentum en marché haussier avec des performances 6M de +60 à +120%, rendant le signal inutile pour le position trading. Ces instruments sont conçus pour le day trading, pas pour des horizons 3-6 mois (effet de "volatility decay" sur longue période). Le filtre est appliqué sur le **nom** de l'ETF (disponible yfinance), pas sur le ticker seul.

### 4.4 Traitement spécifique des secteurs atypiques

Certains secteurs ont des structures financières incompatibles avec les métriques standard :

| Secteur GICS  | Problème                                                                      | Traitement v1                                                                                 |
| ------------- | ----------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Financials    | Passif = dépôts clients, pas de dette "normale"                               | Exclure dette/EBITDA du calcul. Pilier Qualité sur 3 critères (ROE, marge op., FCF yield)     |
| Real Estate   | FFO ≠ earnings GAAP, EBITDA non standard                                      | Idem Financials : exclure dette/EBITDA                                                        |
| Health Care   | Biotechs pré-revenus : P/E négatif systématique                               | Gate P/E négatif suspendu si secteur = Health Care ET marketCap < 5B$                         |
| **Utilities** | **Levier structurel élevé (monopole réglementé, financement infrastructure)** | **Exclure dette/EBITDA du calcul. Pilier Qualité sur 3 critères (ROE, marge op., FCF yield)** |

> Ces exceptions s'appliquent automatiquement via le champ `sector` yfinance. Elles doivent être loggées explicitement dans les exclusions pour auditabilité.

> **Pourquoi Utilities ajouté** : Les Utilities (NextEra, Duke, Southern Co.) sont par nature très endettées — leur modèle économique repose sur des actifs lourds financés par dette à long terme dans un cadre de prix régulé. Un ratio dette/EBITDA de 5-7x est structurellement normal et non un signal de risque, contrairement à une entreprise technologique avec le même ratio. Sans cette exception, les Utilities sont systématiquement pénalisées sur le pilier Qualité pour une raison sectorielle, pas fondamentale.

---

## 5. Module 4 — Filtres post-scoring et ranking final

### 5.1 Filtres de qualité des données

```
data_freshness_check():
    Si dernières données fondamentales > 120 jours :
        Ajouter flag "⚠️ Données fondamentales potentiellement périmées"
        Maintenir dans le ranking mais alerter l'utilisateur

    Si dernières données > 180 jours :
        Exclure du ranking final
```

### 5.2 Earnings Calendar Check

```
earnings_calendar_check():
    Pour chaque ticker dans le top 20 :
        Récupérer prochaine date de résultats via yfinance.Ticker.calendar
        Si date dans [J0, J+14] (de aujourd'hui jusqu'à dans 14 jours) :
            Ajouter tag "📅 Earnings à venir : [DATE]"
            NE PAS exclure — c'est une information, pas un filtre
```

> **Note** : La fenêtre est [J0, J+14] uniquement (regarder vers le futur). J-3 (après résultats) supprimé — le risque est avant les résultats, pas après. Les dates de résultats yfinance sont parfois imprécises (±1-2 jours) — le tag est informatif, pas actionnable seul.

### 5.3 Concentration Sectorielle (Paramétrable)

Pour équilibrer la capture d'Alpha pur et la gestion du risque, la limite de tickers par secteur est désormais configurable :

- **Paramètre** : `max_tickers_per_sector` (défaut : 3).
- **Mode Alpha Pur** : Fixer à 10 pour autoriser un Top 10 concentré sur un seul secteur leader.
- **Mode Défensif** : Fixer à 3 (par défaut) pour forcer une diversification et réduire le drawdown sectoriel.
- **Logique** : Si un secteur dépasse le plafond, le système remplace les suivants par les meilleurs tickers du reste de l'univers.

> **⚠️ Avertissement Mode Alpha Pur** : `max_tickers_per_sector = 10` autorise un Top 10 composé à 100% d'un seul secteur. En cas de rotation sectorielle soudaine (ex : hausse de taux → décrochage du secteur Technology), un portefeuille entièrement concentré peut perdre 15-25% en quelques semaines. Ce mode est adapté à une conviction forte sur un secteur en phase d'accélération — il ne convient pas comme paramètre par défaut pour un usage quotidien.

### 5.4 Output final

```
actions_ranked : liste triée par score_global décroissant
    → top 10 envoyés par Telegram
    → Historique complet stocké dans SQLite

etfs_ranked : liste triée par score_etf décroissant
    → top 5 envoyés par Telegram
    → Historique complet stocké dans SQLite
```

---

## 6. Module 5 — Telegram Notifier

### 6.1 Structure du message journalier

```
📊 ValueMomentum Scanner — [DATE]
━━━━━━━━━━━━━━━━━━━━━━━━━━
🏆 TOP ACTIONS DU JOUR

[Pour chaque ticker top 10]

#[RANG] [EMOJI_SECTEUR] [NOM] ($[TICKER])
Score Global : [SCORE]/100
├ Qualité     : [SCORE_Q]/100
├ Valorisation: [SCORE_V]/100
└ Momentum    : [SCORE_M]/100

📈 Perf 6M : [+/-X.X%] vs secteur [+/-X.X%]
💰 P/E Fwd : [X.X] | ROE : [X.X%] | Marge op. : [X.X%]
🏢 Secteur : [SECTEUR] | Cap : [$XB]
⏱️ Signal actif depuis : [N] jours

[FLAGS ÉVENTUELS]
📅 Earnings : [DATE SI APPLICABLE]
⚠️ [AVERTISSEMENT DONNÉES SI APPLICABLE]

🔗 Yahoo Finance
━━━━━━━━━━━━━━━
```

> **Signal actif depuis N jours** : Calculé à partir de `first_seen_date` en SQLite (première fois que ce ticker apparaît dans le Top 10). Donne un repère temporel à l'utilisateur pour évaluer si un signal est encore "frais" (< 30 jours) ou persistant (> 60 jours). Ne déclenche pas d'action automatique — sert à contextualiser la décision humaine.
>
> **Règle de persistance du signal** : Si un ticker disparaît du Top 10 puis revient, `first_seen_date` est **conservée** (non réinitialisée). Un signal persistant de conviction > 90 jours consécutifs est une information valide — le score le maintient, pas le calendrier. La rotation forcée est un biais comportemental : si le modèle juge le ticker meilleur, il reste. Le ticker est retiré uniquement si son score descend sous le seuil du Top 10.

Exemple concret :

```
📊 ValueMomentum Scanner — 15 Jan 2025
━━━━━━━━━━━━━━━━━━━━━━━━━━

🏆 TOP ACTIONS DU JOUR

#1 💻 Microsoft Corp ($MSFT)
Score Global : 87/100
├ Qualité     : 91/100
├ Valorisation: 72/100
└ Momentum    : 92/100

📈 Perf 6M : +18.3% vs secteur +11.2% (+7.1%)
💰 P/E Fwd : 28.4 | ROE : 38.2% | Marge op. : 44.1%
🏢 Technology | Cap : $3 100B
📅 Earnings : 29 Jan 2025

🔗 https://finance.yahoo.com/quote/MSFT
━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 6.2 Message de synthèse ETFs

```
📦 TOP ETFs DU JOUR

#1 [NOM ETF] ($[TICKER])
Score : [X]/100 | Perf 6M : [+/-X%] vs SPY [+/-X%]
🔗 [LIEN]
```

### 6.3 Messages système (Panique / Erreur / FMP indisponible)

**Régime Panique (VIX > 35) :**

```
🚨 ValueMomentum Scanner — [DATE]
━━━━━━━━━━━━━━━━━━━━━━━━━━
RÉGIME DE PANIQUE DÉTECTÉ

SPY : [PRIX] | EMA200 : [EMA200] | VIX : [VIX]
→ Aucun signal émis. Exposition déconseillée.
→ Prochain scan demain 09h35 ET.
```

**FMP Sniper indisponible :**

```
⚠️ ValueMomentum Scanner — [DATE]
━━━━━━━━━━━━━━━━━━━━━━━━━━
Sniper FMP indisponible — aucun signal émis aujourd'hui.
Cause : [MESSAGE_COURT]
→ Les fondamentaux ne peuvent pas être calculés sans FMP.
→ Vérifier la clé API et les logs sur le Mac Mini.
```

**Erreur technique (scan échoue) :**

```
🚨 ValueMomentum Scanner — ERREUR [DATE]
Le scan quotidien a rencontré une erreur.
Module : [NOM_MODULE]
Erreur : [MESSAGE_COURT]
→ Vérifier les logs sur le Mac Mini.
```

### 6.4 Configuration Telegram

```python
# config.yaml (jamais en dur dans le code)
telegram:
  bot_token: ${TELEGRAM_BOT_TOKEN}  # Variable d'environnement
  chat_id: ${TELEGRAM_CHAT_ID}      # ID du canal ou chat privé
  parse_mode: "HTML"
  disable_web_page_preview: true
```

### 6.5 HTML escaping obligatoire

`parse_mode: "HTML"` impose d'échapper les caractères spéciaux dans les noms d'entreprises et tickers avant envoi. Tickers courants affectés : `AT&T` ($T), `Johnson & Johnson` ($JNJ), noms contenant `<`, `>`, `&`.

```python
import html

def escape_html(text: str) -> str:
    return html.escape(str(text))

# Appliquer sur : nom entreprise, secteur, toute donnée string dans le message
```

### 6.6 Rate limiting Telegram

Telegram limite les messages à **1 message/seconde** pour un même chat. Le top 10 génère potentiellement 15+ messages (Actions + ETFs).

```python
import asyncio

async def send_signals(tickers: list):
    for ticker_data in tickers:
        await bot.send_message(chat_id=CHAT_ID, text=format_message(ticker_data), parse_mode="HTML")
        await asyncio.sleep(1.5)  # Délai de sécurité asymétrique pour éviter HTTP 429
```

**Limite de taille de message (4096 caractères)** : L'API Telegram rejette tout message dépassant 4096 caractères. Un signal avec tous les flags actifs peut approcher cette limite.

```python
TELEGRAM_MAX_CHARS = 4096

def truncate_message(text: str) -> str:
    if len(text) <= TELEGRAM_MAX_CHARS:
        return text
    # Tronquer proprement à la dernière ligne complète sous la limite
    truncated = text[:TELEGRAM_MAX_CHARS - 30]
    last_newline = truncated.rfind("\n")
    return truncated[:last_newline] + "\n⚠️ [message tronqué]"
```

> Appliquer `truncate_message()` sur chaque message avant envoi. Si le message de synthèse ETFs dépasse 4096 chars, le split en deux messages séquentiels (Top 5 ETFs → Top 3 + Top 2).

> **Architecture async** : `python-telegram-bot==21.x` est async-first (asyncio). Pour éviter tout conflit d'Event Loop et garantir une fiabilité institutionnelle, le système utilise **APScheduler 4.x (v4.0.0a5+)** qui est nativement asynchrone. Cela permet au planificateur de partager la même boucle d'événements que Telegram et httpx, évitant les blocages et les crashs silencieux.

---

## 7. Module 6 — Storage & History (SQLite)

### 7.1 Stratégie de stockage

Le stockage repose sur une base de données **SQLite** (`data/signals/scanner_history.db`). Pour supporter les accès concurrents sans verrouillage (Bot en écriture + Dashboard en lecture), le mode **WAL (Write-Ahead Logging)** est activé (`PRAGMA journal_mode=WAL;`).

### 7.2 Structure de la base de données (SQLite)

- **Table `scans`** : Enregistre chaque run (date, métriques marché comme SPY MA200).
- **Table `signals`** : Stocke les signaux Top 10 et Top 5 ETFs avec tous leurs scores et métriques.
- **Table `universe_metadata`** : Historique de la taille de l'univers et des exclusions.
- **Table `scanned_universe`** : Snapshot complet de l'univers éligible à chaque scan (voir ci-dessous).

> **⚠️ Biais de survivorship — obligation de stocker l'univers complet** : Stocker uniquement le Top 10 dans `signals` introduit un biais de survivorship massif dans tout futur backtesting. Si on retrouve après 6 mois que les tickers dans `signals` ont sous-performé, on ne peut pas savoir si l'ensemble de l'univers éligible a également sous-performé (régime de marché défavorable) ou si le modèle de scoring a sélectionné les mauvais tickers. Sans l'univers complet, le track record est auditer mais pas backtester. La table `scanned_universe` stocke **tous les tickers ayant passé les filtres Chalutier** (univers post-éligibilité, pré-shortlisting) à chaque scan.

```sql
CREATE TABLE IF NOT EXISTS scanned_universe (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_date       TEXT NOT NULL,          -- Date du scan (YYYY-MM-DD)
    ticker          TEXT NOT NULL,
    score_momentum  REAL,                   -- Score Chalutier (momentum seul, pré-Sniper)
    rank_chalutier  INTEGER,                -- Rang dans l'univers Chalutier
    in_shortlist    INTEGER DEFAULT 0,      -- 1 si dans le Top 30 envoyé au Sniper
    in_top10        INTEGER DEFAULT 0,      -- 1 si dans le Top 10 final
    market_cap      REAL,
    sector          TEXT,
    price_at_scan   REAL
);

CREATE INDEX IF NOT EXISTS idx_scanned_universe_date ON scanned_universe(scan_date);
```

> **Usage backtesting** : Requête type pour comparer la performance du Top 10 vs l'univers entier sur 30 jours : `SELECT su.ticker, su.in_top10, s.return_30d FROM scanned_universe su LEFT JOIN signals s ON su.ticker = s.ticker AND su.scan_date = s.scan_date WHERE su.scan_date = '2025-01-15'`. Renseigner `price_at_scan` + `in_top10` permet de recalculer les rendements pour tous les tickers de l'univers — pas seulement ceux du Top 10.

**Champs obligatoires dans `signals` pour le suivi de performance :**

```sql
CREATE TABLE IF NOT EXISTS signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_date       TEXT NOT NULL,          -- Date du scan (YYYY-MM-DD)
    ticker          TEXT NOT NULL,
    rank            INTEGER,
    score_global    REAL,
    score_qualite   REAL,
    score_valorisation REAL,
    score_momentum  REAL,
    price_at_signal REAL NOT NULL,          -- Prix de clôture au moment du signal
    first_seen_date TEXT,                   -- Première apparition dans le Top 10
    -- Suivi de performance (mis à jour en tâche de fond)
    price_30d_later  REAL,                  -- Prix 30 jours après le signal
    price_90d_later  REAL,                  -- Prix 90 jours après le signal
    return_30d       REAL,                  -- (price_30d_later - price_at_signal) / price_at_signal
    return_90d       REAL,
    -- Métadonnées
    flags           TEXT,                   -- JSON array des flags actifs (earnings, stale data, etc.)
    signal_type     TEXT DEFAULT 'action'   -- 'action' ou 'etf'
);
```

> **Pourquoi `price_at_signal` + `return_30d/90d`** : Sans ces champs, il est impossible de savoir si le scoring génère réellement de la valeur. Après 3 mois d'utilisation, une simple requête SQL permet de calculer le rendement moyen des signaux et de valider (ou invalider) la stratégie. Ces champs sont remplis en deux temps : `price_at_signal` au moment du scan, `price_30d_later` et `return_30d` par une tâche de fond 30 jours plus tard (yfinance, aucun appel FMP nécessaire).

### 7.3 Tâche de suivi de performance (background job)

```python
# Exécuté quotidiennement, indépendant du scan principal
async def update_signal_returns():
    """Retrouve les signaux sans price_30d_later où scan_date <= aujourd'hui - 30j"""
    signals_to_update = db.query(
        "SELECT id, ticker, scan_date, price_at_signal FROM signals "
        "WHERE price_30d_later IS NULL AND scan_date <= date('now', '-30 days')"
    )
    for signal in signals_to_update:
        current_price = await fetch_current_price(signal.ticker)  # yfinance seul
        return_30d = (current_price - signal.price_at_signal) / signal.price_at_signal
        db.update(signal.id, price_30d_later=current_price, return_30d=return_30d)
```

### 7.3 Cache & Univers (JSON)

Les fichiers JSON sont conservés uniquement pour le cache temporaire et la gestion de l'univers de départ.

---

## 8. Interface HTML (v1.0 Statique / v1.1 Dynamique)

### 8.1 Approche v1.0

Une page HTML statique interrogeant un export JSON temporaire généré depuis la base **SQLite**.

- **Stack** : Vanilla JS + http.server.

### 8.2 Transition v1.1 (Roadmap)

Migration vers une API **FastAPI** interrogeant la base **SQLite** locale pour un dashboard interactif.

---

## 9. Structure du projet Python

```
valuemomentum-scanner/
├── main.py                     # Point d'entrée, orchestration
├── config.yaml                 # Configuration (pas de secrets)
├── .env                        # Secrets (gitignored)
├── requirements.txt
│
├── scanner/
│   ├── __init__.py
│   ├── universe.py             # Module 1 : Universe Builder
│   ├── fetcher.py              # Module 2 : Data Fetcher (yfinance + cache)
│   ├── scoring/
│   │   ├── __init__.py
│   │   ├── quality.py          # Pilier Qualité
│   │   ├── valuation.py        # Pilier Valorisation
│   │   ├── momentum.py         # Pilier Momentum
│   │   └── engine.py           # Score global + ranking
│   ├── filters.py              # Module 4 : Post-scoring filters
│   ├── notifier.py             # Module 5 : Telegram
│   └── storage.py              # Module 6 : SQLite storage
│
├── data/
│   ├── universe/
│   ├── signals/
│   ├── cache/
│   └── logs/
│
├── web/
│   └── index.html              # Interface HTML viewer
│
└── tests/
    ├── test_scoring.py
    ├── test_fetcher.py
    └── test_filters.py
```

---

## 10. Stack technique et dépendances

```
# requirements.txt
# Versions épinglées — mettre à jour explicitement, pas de wildcards pip

# Données marché
yfinance>=0.2.40,<0.3.0
pandas>=2.1.0,<3.0.0
numpy>=1.26.0,<2.0.0          # >= 1.26 requis par pandas 2.x

# Scheduling
apscheduler>=4.0.0a5           # v4.x natif async (résout les conflits d'event loop)
pandas-market-calendars>=4.3.0 # Calendrier trading US — exclure jours fériés NYSE

# Alertes
python-telegram-bot>=21.0,<22.0   # API async-first (asyncio)
httpx>=0.27.0,<0.28.0             # Client HTTP asynchrone pour FMP API

# Configuration
PyYAML>=6.0.1,<7.0.0
python-dotenv>=1.0.0,<2.0.0

# Logging
loguru>=0.7.2,<1.0.0

# Utilitaires
pytz>=2024.1                   # Requis par APScheduler 3.x
requests>=2.31.0,<3.0.0

# Tests
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

> **Note async** : La version 4.x d'APScheduler permet une intégration native avec `asyncio`. Le scheduler est lancé au sein de la même boucle d'événements que le bot Telegram, garantissant une fiabilité totale 24/7.

---

## 11. Déploiement sur Mac Mini (macOS)

### 11.1 Prérequis système

Le projet est un stack **100% Python** — aucune dépendance Node.js ou npm n'est nécessaire. `supervisor` est installé via `requirements.txt` comme n'importe quelle autre dépendance Python.

```bash
# Python 3.11+ via Homebrew
brew install python@3.11

# Cloner le projet et créer l'environnement virtuel
git clone https://github.com/SirHarveyBix/bot-value.git
cd bot-value
python3.11 -m venv venv
source venv/bin/activate

# Installe toutes les dépendances, y compris supervisor
pip install -r requirements.txt
```

### 11.2 Configuration supervisord

Le process manager est **supervisord** (paquet Python `supervisor`). La configuration se trouve à la racine du projet dans `supervisord.conf`.

```ini
[supervisord]
logfile=data/logs/supervisord.log
pidfile=/tmp/valuemomentum-supervisord.pid
loglevel=info

[unix_http_server]
file=/tmp/valuemomentum-supervisor.sock

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix:///tmp/valuemomentum-supervisor.sock

[program:scanner]
command=%(here)s/venv/bin/python main.py
directory=%(here)s
environment=TZ="America/New_York",PYTHONPATH="%(here)s"
autostart=true
autorestart=true
startretries=5
stdout_logfile=data/logs/scanner_stdout.log
stderr_logfile=data/logs/scanner_stderr.log

[program:web]
command=%(here)s/venv/bin/python -m http.server 8080 --directory web
directory=%(here)s
autostart=true
autorestart=true
stdout_logfile=data/logs/web_stdout.log
stderr_logfile=data/logs/web_stderr.log
```

Points clés :

- `%(here)s` résout automatiquement au dossier contenant `supervisord.conf` — aucun chemin absolu à renseigner.
- `TZ="America/New_York"` est injecté directement dans l'environnement du processus `scanner`.
- `startretries=5` relance le scanner jusqu'à 5 fois en cas de crash.
- Les deux programmes (`scanner` et `web`) sont gérés indépendamment : un crash du dashboard n'affecte pas le scanner.

**Commandes courantes :**

```bash
source venv/bin/activate

# Démarrer supervisord (et tous les programmes)
supervisord -c supervisord.conf

# Vérifier l'état des processus
supervisorctl -c supervisord.conf status

# Arrêter supervisord proprement
supervisorctl -c supervisord.conf shutdown

# Redémarrer uniquement le scanner
supervisorctl -c supervisord.conf restart scanner
```

### 11.3 Prévention veille Mac Mini

```bash
# Désactiver la mise en veille système (à exécuter une fois en setup)
sudo pmset -a sleep 0
sudo pmset -a disksleep 0
sudo pmset -a hibernatemode 0
sudo pmset -a powernap 0

# Permettre le réveil réseau (optionnel mais utile)
sudo pmset -a womp 1

# Vérification de la configuration
pmset -g
```

### 11.4 Démarrage et persistence au reboot

Le démarrage automatique au reboot est géré par **launchd** (gestionnaire de services natif macOS). Exécuter ce bloc **depuis le dossier racine du projet** :

```bash
PROJECT_DIR="$(pwd)"
PLIST=~/Library/LaunchAgents/com.valuemomentum.plist

cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.valuemomentum</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PROJECT_DIR}/venv/bin/supervisord</string>
        <string>-c</string>
        <string>${PROJECT_DIR}/supervisord.conf</string>
        <string>-n</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
    <key>StandardOutPath</key>
    <string>${PROJECT_DIR}/data/logs/launchd_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${PROJECT_DIR}/data/logs/launchd_stderr.log</string>
</dict>
</plist>
EOF

launchctl load "$PLIST"
echo "Service installé. Le scanner démarrera à chaque boot."
```

> **Note** : Le flag `-n` (nodaemon) est requis par le mécanisme `KeepAlive` de launchd — supervisord doit rester en foreground pour que launchd puisse le surveiller et le relancer.

Pour désinstaller :

```bash
launchctl unload ~/Library/LaunchAgents/com.valuemomentum.plist
rm ~/Library/LaunchAgents/com.valuemomentum.plist
```

---

## 12. Sécurité

### 12.1 Gestion des secrets

```bash
# Fichier .env (dans .gitignore OBLIGATOIREMENT)
TELEGRAM_BOT_TOKEN=xxxxxxxxxxxxx
TELEGRAM_CHAT_ID=xxxxxxxxxxxxx
```

```python
# Chargement dans main.py
from dotenv import load_dotenv
import os

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN manquant dans .env")
```

> **Note** : Contrairement au bot de trading IBKR qui nécessite le macOS Keychain (exécution d'ordres réels), le fichier `.env` est acceptable ici. Ce scanner n'exécute aucun ordre financier — il n'y a pas de risque de perte de capital si les credentials Telegram sont compromis. La seule exposition est la réception de faux signaux ou le spam du canal.

### 12.2 Bonnes pratiques

- `.env` dans `.gitignore` — ne jamais committer
- Créer un bot Telegram dédié (pas le compte personnel)
- Utiliser un canal Telegram privé (pas public)
- Ne pas logguer les tokens dans les fichiers de log

---

## 13. Gestion des erreurs et résilience

### 13.1 Stratégie de retry pour yfinance

```python
# fetcher.py — logique de retry
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5

def fetch_with_retry(ticker: str) -> dict:
    for attempt in range(MAX_RETRIES):
        try:
            data = yf.Ticker(ticker).info
            if data and data.get("regularMarketPrice") is not None:  # None-safe check
                return data
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                logger.warning(f"Échec fetch {ticker} après {MAX_RETRIES} tentatives : {e}")
                return {}
            time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
    return {}
```

### 13.2 Cache des données fondamentales

Les données fondamentales (P/E, ROE, marges) ne changent pas d'un jour à l'autre entre les publications de résultats. Le fetcher les met en cache pour éviter d'épuiser les 250 calls FMP/jour sur des données déjà récupérées.

```python
# Règle de cache — TTL 27h pour éviter la race condition à 24h
# (scan à 09h35 ET, cache J-1 créé à ~09h32 → expirerait 3min avant le prochain scan)
CACHE_TTL_FUNDAMENTALS = 27 * 3600   # 97 200 secondes
CACHE_TTL_PRICE_HISTORY = 4 * 3600   # 4 heures (prix intraday)
```

### 13.4 Fragilité du Scraping (yfinance)

L'utilisation de `yfinance` présente un risque structurel car il s'agit d'un wrapper non-officiel. En cas de changement majeur de Yahoo Finance :

1. **Surveillance** : Le bot logue tout échec de fetch. Si le ratio de données valides tombe sous 60%, le scan s'arrête.
2. **Maintenance** : Une mise à jour régulière de la bibliothèque `yfinance` est nécessaire.
3. **Roadmap v2** : Envisager la migration vers une API officielle (AlphaVantage, FMP) pour la stabilité long-terme.

---

## 14. Stratégie de Test et Assurance Qualité

### 14.1 Protocoles de Test Hermétiques (Obligatoires)

Pour garantir la fiabilité de la suite de tests sans épuiser les quotas d'API (FMP 250/jour) ni dépendre de la stabilité du réseau, le système impose l'isolation totale :

- **VCR.py (Isolation Réseau)** : Les tests d'intégration enregistrent les requêtes réelles dans des "cassettes" YAML. Les exécutions suivantes rejouent ces cassettes, garantissant un déterminisme total et une consommation API nulle.
- **Freezegun (Déterminisme Temporel)** : Le temps système est "gelé" (ex: simulation d'un mercredi à 10:00) pour tester les règles de marché ouvert/fermé et les fenêtres d'earnings de manière reproductible.
- **Mocks & Fixtures** : La logique mathématique pure (Scoring) est testée via des objets Mock pré-remplis pour éviter tout effet de bord.

### 14.2 Structure de la Suite

- `tests/test_logic.py` : Calculs (ROE, Surprise, Pénalités) sur données statiques.
- `tests/test_fetcher_vcr.py` : Validation des connecteurs yfinance/FMP via cassettes.
- `tests/test_integration_vcr.py` : Pipeline complet (EMA 200, VIX, Scoring, SQLite) simulé avec VCR et Freezegun.

---

## 15. Roadmap et évolutions futures

### v1.0 (scope actuel - TERMINÉ)

- [x] Scanner quotidien Actions + ETFs
- [x] Scoring 3 piliers (Qualité, Valorisation, Momentum)
- [x] **Intégration API FMP** pour le Sniper (fondamentaux fiables)
- [x] Alertes Telegram (Asynchrones)
- [x] **Orchestration Native Asynchrone** (APScheduler 4.x)
- [x] **Stockage SQLite** (scanner_history.db)
- [x] **Market Gate** (Filtre SPY MA200)

### v1.1

- [ ] Interface HTML viewer (dynamique via FastAPI)
- [ ] Historique de performance des signaux (track record automatique)
- [ ] Alertes de changement de régime de marché en temps réel

---

## 16. Contraintes et hypothèses de développement

1. **Hybride yfinance / FMP — Séparation stricte des responsabilités** : yfinance est utilisé **exclusivement** pour les données prix/volume (OHLCV, momentum). FMP est utilisé **exclusivement** pour les données bilancielles (ROE, marges, dette/EBITDA, FCF, P/E forward, surprise earnings, révisions analystes). **Il n'existe aucun fallback de FMP vers yfinance pour les fondamentaux** — cf. Règle d'Or du besoin. Si FMP est indisponible (clé absente, erreur 5xx persistante après 2 retries) : envoyer le message Telegram `⚠️ Sniper FMP indisponible` et arrêter le scan. Un scan sans données FMP est un scan sans pilier Qualité — il ne doit pas émettre de signaux.

2. **Le Mac Mini est en local** — pas de cloud. Le stockage est 100% **SQLite** pour l'historique, avec des fichiers JSON pour l'univers et le cache.

3. **Aucun ordre n'est exécuté** — ce système est un scanner de décision.

4. **Focus Prix pour les ETFs** : Le volume est exclu du scoring ETF pour éviter les faux signaux de panique/liquidation.

5. **Univers limité aux actions US** — focus initial sur la fiabilité des données.

---

---

## 17. Table des constantes configurables

Toutes les constantes métier sont centralisées dans `config.yaml`. Valeurs de référence, plages valides et section source :

| Constante                       | Valeur par défaut | Plage valide                                                      | Section spec |
| ------------------------------- | ----------------- | ----------------------------------------------------------------- | ------------ |
| `SHORTLIST_SIZE`                | 30                | [20, 30] — **ne pas dépasser 30** sans audit budget FMP           | §2           |
| `VIX_PANIC_THRESHOLD`           | 35                | [30, 45]                                                          | §4.0         |
| `VIX_WARNING_THRESHOLD`         | 25                | [20, 30]                                                          | §4.0         |
| `MAX_TICKERS_PER_SECTOR`        | 3                 | [1, 10] — 10 = mode alpha pur (risque concentration)              | §5.3         |
| `DATA_FRESHNESS_WARNING_DAYS`   | 120               | [60, 150]                                                         | §5.1         |
| `DATA_FRESHNESS_EXCLUSION_DAYS` | 180               | [120, 365]                                                        | §5.1         |
| `MAX_WORKERS_UNIVERSE`          | 4                 | [2, 6] — au-delà de 6, risque ban IP yfinance                     | §3.2         |
| `INTER_REQUEST_DELAY`           | 1.0s              | [0.5, 2.0]                                                        | §3bis.2.1    |
| `FMP_MAX_RETRIES`               | 2                 | [1, 3] — **2 max** pour tenir dans le budget 250 calls            | §2           |
| `FMP_CALL_BUDGET_HARD_LIMIT`    | 245               | [230, 249] — disjoncteur global, 5 calls de marge sur quota 250   | §2           |
| `YFINANCE_CHUNK_SIZE`           | 100               | [50, 150] — tickers par batch, au-delà risque ban IP 429          | §3bis.2.1    |
| `YFINANCE_CHUNK_DELAY_S`        | 2.0s              | [1.0, 5.0] — pause entre chunks yfinance                          | §3bis.2.1    |
| `CACHE_TTL_FUNDAMENTALS`        | 97200s (27h)      | [86400, 172800] — **min 27h** pour éviter race condition 09h35    | §3bis.2.4    |
| `CACHE_TTL_PRICE_HISTORY`       | 14400s (4h)       | [3600, 86400]                                                     | §3bis.2.4    |
| `EARNINGS_WINDOW_DAYS`          | 14                | [7, 21]                                                           | §5.2         |
| `MIN_UNIVERSE_SIZE`             | 100               | [50, 200] — en dessous : percentile ranking invalide, scan annulé | §4           |
| `TELEGRAM_MAX_CHARS`            | 4096              | fixe (limite API)                                                 | §6.6         |

> **Règle de modification** : Toute modification d'une constante doit être accompagnée d'une note datée dans ce tableau (`[YYYY-MM-DD] Modifié X → Y — raison : ...`). La spec et le code doivent rester synchrones.

---

_Document rédigé pour transmission à Claude (modèle de génération de code). Toutes les décisions d'architecture ont été prises pour maximiser la fiabilité des données et la maintenabilité du code, en tenant compte des contraintes de l'environnement Mac Mini local et des limites de l'API yfinance gratuite._
\_
