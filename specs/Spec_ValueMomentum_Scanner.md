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

- Market cap minimum 500M$ (mid-cap et plus)
- Volume journalier moyen 20 jours > 1M$ (exécutable)
- Prix > 5$ (éviter les zones penny stock, split post-crise)
- Listé sur NYSE, NASDAQ, ou AMEX (pas OTC)

**VE :** Ajoute un filtre sur l'ancienneté des données : au moins 2 ans de données financières disponibles. Une entreprise qui vient d'entrer en bourse n'a pas assez de track record pour une analyse value sérieuse.

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

**PO :** Bonne remarque. On implémentera deux types de ranking : **cross-universe** pour les métriques universelles (momentum, croissance CA), et **intra-sector** pour les métriques de valorisation (P/E, EV/EBITDA).

---

### Acte 4 — Ce qui peut mal tourner ?

**VE :** Le principal risque opérationnel de ce système, c'est la **fraîcheur des données fondamentales**. Les trimestriels ne sortent pas tous les jours. Un P/E calculé sur des earnings vieux de 9 mois peut être complètement trompeur. Le bot doit afficher la date des dernières données fondamentales utilisées dans chaque signal.

**PO :** On ajoutera une "data freshness flag" : si les données financières d'une entreprise ont plus de 120 jours, on la marque `⚠️ données potentiellement périmées` dans le message Telegram.

**VE :** Deuxième risque : les faux positifs autour des résultats trimestriels (Earnings). Une entreprise peut scorer fort juste avant ses résultats, puis s'effondrer de 20% si les earnings déçoivent. Le bot doit filtrer ou au minimum signaler les entreprises avec des résultats attendus dans les 14 prochains jours.

**PO :** On intègre un **Earnings Calendar check** via yfinance. Les tickers avec earnings dans ±14 jours seront tagués `📅 Earnings à venir` — inclus dans les signaux mais avec avertissement explicite.

**VE :** Troisième risque : les ETFs et les actions ne se comparent pas sur les critères fondamentaux. Un ETF n'a pas de P/E, pas de ROE.

**PO :** Bonne observation. On crée deux pipelines de scoring distincts : un pipeline **Actions** avec les 5 critères complets, et un pipeline **ETFs** limité aux critères momentum + flux de capitaux (AUM trend). Les ETFs auront leur propre classement et leur propre section dans le rapport Telegram.

---

## Spécifications Techniques Complètes

---

## 1. Vue d'ensemble du système

```
Nom du projet    : ValueMomentum Scanner
Version          : 1.0
Horizon cible    : Signals pour positions 3 à 6 mois
Fréquence        : Quotidienne (jours ouvrés US)
Déclenchement    : 09h30 ET (après ouverture NYSE)
Sortie principale : Alertes Telegram + fichier JSON historique
Environnement    : Mac Mini (serveur local), macOS
Langage          : Python 3.11+
```

---

## 2. Architecture générale

```
┌─────────────────────────────────────────────────────────────┐
│                     SCHEDULER (APScheduler)                  │
│                     Déclenchement 09h30 ET                   │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   MODULE 1 : UNIVERSE BUILDER                │
│  Charge la liste de tickers → applique filtres d'éligibilité │
│  Résultat : eligible_universe.json (~600-700 instruments)    │
└───────────────────────────┬─────────────────────────────────┘
                            │
                    ┌───────┴──────┐
                    ▼              ▼
┌─────────────────────┐  ┌─────────────────────┐
│  PIPELINE ACTIONS   │  │  PIPELINE ETFs       │
│  (scores complets)  │  │  (momentum + flux)   │
└──────────┬──────────┘  └──────────┬───────────┘
           │                        │
           ▼                        ▼
┌─────────────────────────────────────────────────────────────┐
│               MODULE 2 : DATA FETCHER                        │
│  yfinance → price history, fundamentals, earnings calendar   │
│  Gestion cache Redis/JSON, retry logic, data quality checks  │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│               MODULE 3 : SCORING ENGINE                      │
│  Calcul des 3 piliers (Qualité / Valorisation / Momentum)    │
│  Percentile ranking cross-universe et intra-secteur          │
│  Score global pondéré 0-100                                  │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│               MODULE 4 : FILTER & RANKING                    │
│  Élimination des données périmées                            │
│  Tagging earnings calendar                                   │
│  Ranking final → top 10 Actions + top 5 ETFs                │
└───────────────────────────┬─────────────────────────────────┘
                            │
                    ┌───────┴──────┐
                    ▼              ▼
┌─────────────────────┐  ┌─────────────────────────────────┐
│  MODULE 5 : TELEGRAM │  │  MODULE 6 : STORAGE & HISTORY   │
│  Formatage messages  │  │  signals_YYYY-MM-DD.json        │
│  Envoi alertes bot   │  │  Interface HTML viewer           │
└─────────────────────┘  └─────────────────────────────────┘
```

---

## 3. Module 1 — Universe Builder

### 3.1 Univers de départ (fichier statique maintenu manuellement)

```
tickers_universe.json
├── stocks: [liste S&P 500 + Russell 1000 complémentaires ~1200 tickers]
└── etfs: [liste ~150 ETFs sectoriels, thématiques, smart beta]
```

Le fichier sera mis à jour **manuellement une fois par mois** par l'opérateur (ajout des nouveaux entrants S&P, suppression des délistés). Ce n'est pas automatisé en v1 — les APIs de composition d'indices sont payantes et hors scope.

### 3.2 Filtres d'éligibilité obligatoires (appliqués chaque jour)

Les filtres suivants éliminent les instruments non tradables avant toute analyse :

| Filtre                | Seuil                           | Source                  | Raison                              |
| --------------------- | ------------------------------- | ----------------------- | ----------------------------------- |
| Market Cap minimum    | > 500 M$                        | yfinance `marketCap`    | Éliminer illiquidité structurelle   |
| Volume moyen 20j      | > 1 000 000 $                   | yfinance OHLCV          | Exécutable sans impact marché       |
| Prix unitaire         | > 5.00 $                        | yfinance `currentPrice` | Éviter zones penny stock            |
| Listing               | NYSE / NASDAQ / AMEX            | yfinance `exchange`     | Exclure OTC, marchés exotiques      |
| Ancienneté données    | > 2 ans d'historique disponible | yfinance date min       | Track record minimum value          |
| Données fondamentales | Disponibles et < 180 jours      | yfinance `financials`   | Données trop vieilles = non fiables |

> **Note technique** : Le filtre volume se calcule comme `avg(volume_20j) × avg(close_20j)`. Ne pas utiliser le volume brut (actions) mais le volume en dollars.

---

## 4. Module 3 — Scoring Engine

### 4.1 Pipeline Actions : définition des critères

#### PILIER 1 : QUALITÉ (pondération 35%)

| Métrique             | Donnée yfinance                          | Calcul                                        | Ranking            |
| -------------------- | ---------------------------------------- | --------------------------------------------- | ------------------ |
| ROE TTM              | `returnOnEquity`                         | Valeur directe (TTM — voir note)              | Cross-universe     |
| Marge opérationnelle | `operatingMargins`                       | Valeur directe                                | Intra-secteur GICS |
| Dette nette / EBITDA | `totalDebt`, `totalCash`, `ebitda`       | Calcul : (totalDebt - totalCash) / ebitda     | Cross-universe     |
| FCF Yield proxy      | `freeCashflow`, `marketCap`              | freeCashflow / marketCap                      | Cross-universe     |

> **Note ROE** : `yfinance` retourne uniquement le ROE TTM via `returnOnEquity`. La moyenne 3 ans nécessite `ticker.financials` (3 bilans annuels) — complexité supplémentaire documentée dans le Module 2. En v1, ROE TTM est utilisé comme proxy. Si la stabilité du ROE est critique, v1.1 pourra ajouter la moyenne glissante.

> **Note secteurs exclus du calcul dette/EBITDA** : Financières (banques, assurances) et REITs ont des structures bilancielles incompatibles avec ce ratio. Traitement spécifique documenté en section 4.4.

**Règle de qualité minimale (gate, non scoré) :**

- ROE < 0% → ticker exclu du scoring (business structurellement défaillant)
- EBITDA ≤ 0 → ticker exclu (ratio dette/EBITDA sans sens + business déficitaire)
- Dette nette / EBITDA > 6x → exclu (risque bilan trop élevé)

**Score Qualité** = moyenne pondérée des 4 percentile rangs

- ROE 3 ans : 35%
- Marge opérationnelle : 30%
- FCF Yield proxy : 25%
- Dette/EBITDA (inversé — plus c'est bas, mieux c'est) : 10%

---

#### PILIER 2 : VALORISATION (pondération 30%)

| Métrique    | Donnée yfinance      | Calcul                    | Ranking            |
| ----------- | -------------------- | ------------------------- | ------------------ |
| P/E Forward | `forwardPE`          | Valeur directe (inversée) | Intra-secteur GICS |
| EV/EBITDA   | `enterpriseToEbitda` | Valeur directe (inversée) | Intra-secteur GICS |
| PEG Ratio   | `pegRatio`           | Valeur directe (inversée) | Cross-universe     |

**Règles gates valorisation (filtres d'exclusion, non scorés) :**

- P/E Forward > 50 → exclu sauf si secteur = Technology/Biotech (seuil 80)
- P/E Forward négatif → exclu (pertes prévues)
- EV/EBITDA > 40 → exclu

**Score Valorisation** = moyenne pondérée des percentile rangs inversés (un P/E BAS = bon score)

- P/E Forward inversé : 45%
- EV/EBITDA inversé : 35%
- PEG inversé : 20%

> **Gestion données manquantes** : Si le P/E Forward n'est pas disponible pour un ticker, on utilise le P/E TTM avec une pénalité de -5 points sur le score final (données estimées moins fiables). Si aucun P/E n'est disponible, le critère valorisation est exclu et le score global est recalculé sur Qualité + Momentum uniquement, avec un flag `⚠️ Valorisation non calculée`.

---

#### PILIER 3 : MOMENTUM (pondération 35%)

| Métrique                      | Calcul                                         | Ranking        |
| ----------------------------- | ---------------------------------------------- | -------------- |
| Performance 6 mois            | (Prix J0 - Prix J-126) / Prix J-126            | Cross-universe |
| Performance 3 mois            | (Prix J0 - Prix J-63) / Prix J-63              | Cross-universe |
| Surperformance sectorielle 6M | Perf 6M ticker - Perf 6M ETF sectoriel SPDR    | Intra-secteur  |
| Momentum de révision EPS      | Variation des estimations EPS 12M sur 90 jours | Cross-universe |

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

- Si performance 1 mois > +25% → pénalité -10 points sur score momentum (probable mean reversion court terme)
- Si performance 1 mois < -20% → pénalité -5 points (momentum négatif récent)

**Score Momentum** = moyenne pondérée :

- Perf 6 mois : 30%
- Surperf sectorielle 6M : 35%
- Perf 3 mois : 20%
- Momentum révision EPS : 15%

---

### 4.2 Score Global Actions

```python
score_global = (
    score_qualite * 0.35 +
    score_valorisation * 0.30 +
    score_momentum * 0.35
)
# Résultat : float entre 0 et 100
```

---

### 4.3 Pipeline ETFs (score simplifié)

Pour les ETFs, seuls 3 critères sont calculés :

| Critère            | Calcul                                       | Pondération |
| ------------------ | -------------------------------------------- | ----------- |
| Performance 6 mois | (Prix J0 - Prix J-126) / Prix J-126          | 40%         |
| Surperf vs SPY 6M  | Perf 6M ETF - Perf 6M SPY                    | 35%         |
| Trend AUM          | Variation encours sur 3 mois (si disponible) | 25%         |

> **Note** : L'AUM trend n'est pas disponible via yfinance. En v1, ce critère sera calculé comme proxy via le volume de transactions relatif (augmentation du volume moyen = flux entrants). En v2, on pourra intégrer l'API ETF.com ou VettaFi.

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
        Récupérer prochaine date de résultats via yfinance
        Si date dans [J-3, J+14] :
            Ajouter tag "📅 Earnings à venir : [DATE]"
            NE PAS exclure — c'est une information, pas un filtre
```

### 5.3 Diversification forcée

Pour éviter que le top 10 soit dominé par un seul secteur :

- Maximum 3 tickers du même secteur GICS dans le top 10
- Si un secteur dépasse 3 représentants, le 4ème est remplacé par le meilleur ticker du secteur suivant

### 5.4 Output final

```
actions_ranked : liste triée par score_global décroissant
    → top 10 envoyés par Telegram
    → top 50 stockés en JSON

etfs_ranked : liste triée par score_etf décroissant
    → top 5 envoyés par Telegram
    → top 20 stockés en JSON
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

[FLAGS ÉVENTUELS]
📅 Earnings : [DATE SI APPLICABLE]
⚠️ [AVERTISSEMENT DONNÉES SI APPLICABLE]

🔗 Yahoo Finance
━━━━━━━━━━━━━━━
```

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

### 6.3 Message d'erreur (si scan échoue)

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

---

## 7. Module 6 — Storage & History

### 7.1 Structure fichiers JSON

```
data/
├── universe/
│   ├── tickers_universe.json          # Fichier statique mis à jour mensuellement
│   └── eligible_universe_YYYY-MM-DD.json  # Univers filtré du jour
├── signals/
│   ├── signals_YYYY-MM-DD.json        # Résultats complets du scan du jour
│   └── signals_latest.json            # Symlink vers le fichier du jour (pour l'UI)
├── cache/
│   └── fundamentals_cache.json        # Cache des données yfinance (TTL 24h)
└── logs/
    └── scanner_YYYY-MM-DD.log         # Logs du run quotidien
```

### 7.2 Structure d'un fichier signals_YYYY-MM-DD.json

```json
{
  "scan_date": "2025-01-15",
  "scan_timestamp": "2025-01-15T14:35:22Z",
  "universe_size": 687,
  "eligible_count": 623,
  "metadata": {
    "sp500_performance_day": 0.0032,
    "vix_level": 14.2,
    "market_regime": "bull"
  },
  "top_stocks": [
    {
      "rank": 1,
      "ticker": "MSFT",
      "name": "Microsoft Corp",
      "sector": "Technology",
      "market_cap_b": 3100,
      "score_global": 87.3,
      "score_quality": 91.2,
      "score_valuation": 72.1,
      "score_momentum": 92.4,
      "metrics": {
        "pe_forward": 28.4,
        "ev_ebitda": 21.3,
        "peg_ratio": 2.1,
        "roe_ttm": 0.382,
        "operating_margin": 0.441,
        "net_debt_ebitda": 0.8,
        "fcf_yield": 0.024,
        "perf_6m": 0.183,
        "perf_3m": 0.092,
        "sector_outperf_6m": 0.071,
        "eps_revision_3m": 0.043
      },
      "flags": {
        "earnings_upcoming": true,
        "earnings_date": "2025-01-29",
        "data_freshness_warning": false,
        "valuation_estimated": false
      },
      "yahoo_url": "https://finance.yahoo.com/quote/MSFT"
    }
  ],
  "top_etfs": [],
  "excluded_count": 64,
  "exclusion_reasons": {
    "low_volume": 23,
    "low_market_cap": 18,
    "negative_roe": 9,
    "high_debt": 8,
    "missing_data": 6
  }
}
```

---

## 8. Interface HTML (option v1.1)

Une page HTML statique générée quotidiennement depuis le JSON, consultable via navigateur sur le réseau local.

### 8.1 Fonctionnalités minimales

- Tableau des top 10 avec tri par colonne (score global, qualité, valorisation, momentum)
- Filtrage par secteur
- Historique des 30 derniers jours (graphique de score pour les tickers récurrents)
- Accessible via `http://mac-mini.local:8080/` sur le réseau local

### 8.2 Stack technique

```
- Fichier index.html unique (pas de build step, pas de framework)
- Vanilla JavaScript
- Chart.js pour les graphiques (CDN)
- Données chargées depuis signals_latest.json (fetch local)
- Serveur HTTP : python -m http.server 8080 (lancé par PM2)
```

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
│   └── storage.py              # Module 6 : JSON storage
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

```python
# requirements.txt

# Données marché
yfinance==0.2.x             # Données OHLCV et fondamentaux
pandas==2.x                  # Traitement données
numpy==1.x                   # Calculs numériques

# Scheduling
APScheduler==3.x             # Déclenchement quotidien 09h30 ET

# Alertes
python-telegram-bot==21.x   # API Telegram (async)

# Configuration
PyYAML==6.x                  # Lecture config.yaml
python-dotenv==1.x           # Chargement .env

# Logging
loguru==0.7.x                # Logging structuré (remplace logging standard)

# Utilitaires
pytz==2024.x                  # Gestion fuseaux horaires (ET pour NYSE)
requests==2.x                # HTTP fallback

# Tests
pytest==8.x
pytest-asyncio
```

---

## 11. Déploiement sur Mac Mini (macOS)

### 11.1 Prérequis système

```bash
# Python 3.11+ via Homebrew
brew install python@3.11

# PM2 pour la gestion du processus
npm install -g pm2

# Création de l'environnement virtuel
cd ~/valuemomentum-scanner
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 11.2 Configuration PM2

```javascript
// ecosystem.config.js
module.exports = {
  apps: [
    {
      name: "valuemomentum-scanner",
      script: "venv/bin/python",
      args: "main.py",
      cwd: "/Users/[USER]/valuemomentum-scanner",
      interpreter: "none",
      watch: false,
      autorestart: true,
      restart_delay: 30000, // 30s entre les restarts
      max_restarts: 5,
      log_file: "data/logs/pm2.log",
      error_file: "data/logs/pm2-error.log",
      env: {
        TZ: "America/New_York",
        PYTHONPATH: "/Users/[USER]/valuemomentum-scanner",
      },
    },
    {
      name: "valuemomentum-web",
      script: "venv/bin/python",
      args: "-m http.server 8080 --directory web",
      cwd: "/Users/[USER]/valuemomentum-scanner",
      interpreter: "none",
      watch: false,
      autorestart: true,
    },
  ],
};
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

```bash
# Enregistrement PM2 dans launchd (redémarrage automatique au boot)
pm2 startup launchd
# Exécuter la commande générée par la commande ci-dessus
pm2 save

# Démarrage manuel initial
pm2 start ecosystem.config.js
pm2 status
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
            if data and "regularMarketPrice" in data:
                return data
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                logger.warning(f"Échec fetch {ticker} après {MAX_RETRIES} tentatives : {e}")
                return {}
            time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
    return {}
```

### 13.2 Cache des données fondamentales

Les données fondamentales (P/E, ROE, marges) ne changent pas d'un jour à l'autre entre les publications de résultats. Les fetcher en cache avec un TTL de 24h pour éviter d'interroger yfinance 600 fois par run.

```python
# Règle de cache
CACHE_TTL_FUNDAMENTALS = 24 * 3600   # 24 heures
CACHE_TTL_PRICE_HISTORY = 4 * 3600   # 4 heures (prix intraday)
```

### 13.3 Seuil minimum de données valides

```python
# Si moins de 60% des tickers de l'univers ont des données valides :
# → Ne pas envoyer d'alerte Telegram avec des résultats partiels
# → Envoyer un message d'erreur et logger le problème
MIN_VALID_DATA_RATIO = 0.60
```

---

## 14. Tests

### 14.1 Tests unitaires obligatoires avant déploiement

```
tests/test_scoring.py
├── test_quality_score_calculation()        # Vérifier pondérations
├── test_valuation_intra_sector_ranking()   # Ranking intra-secteur correct
├── test_momentum_sector_outperformance()   # Delta vs ETF sectoriel
├── test_score_global_bounds()              # Score toujours entre 0 et 100
├── test_gate_negative_roe_exclusion()      # Les ROE négatifs sont exclus
└── test_high_debt_exclusion()              # Les bilans dangereux sont exclus

tests/test_fetcher.py
├── test_cache_hit()                        # Cache fonctionne
├── test_retry_on_failure()                 # Retry logic opérationnelle
└── test_data_freshness_flag()             # Données > 120j flaggées

tests/test_filters.py
├── test_earnings_calendar_tag()           # Earnings proches = tag ajouté
├── test_sector_diversification()          # Max 3 par secteur dans top 10
└── test_minimum_data_ratio()             # Block si <60% données valides
```

---

## 15. Roadmap et évolutions futures

### v1.0 (scope actuel)

- [x] Scanner quotidien Actions + ETFs
- [x] Scoring 3 piliers
- [x] Alertes Telegram
- [x] Stockage JSON

### v1.1

- [ ] Interface HTML viewer
- [ ] Historique de performance des signaux (track record)
- [ ] Backtesting simple sur 1 an de signaux historiques

### v2.0

- [ ] Intégration données alternatives (insiders transactions, short interest)
- [ ] Alertes prix en temps réel sur les tickers signalés (suivi de la position)
- [ ] Score de sentiment news (via API NewsAPI ou Finviz)
- [ ] Support multi-marchés (ETFs Europe via IBKR)

---

## 16. Contraintes et hypothèses de développement

1. **yfinance est la seule source de données** — pas d'API payante en v1. Les limitations de yfinance (données manquantes, délais, instabilité) doivent être gérées par le code, pas par un changement de source.

2. **Le Mac Mini est en local** — pas de cloud. La disponibilité dépend de la connexion domestique. Le bot tolère une indisponibilité de 24h (le scan du lendemain suffira).

3. **Aucun ordre n'est exécuté** — ce système est un scanner de décision. L'humain décide d'acheter ou non. Pas de connexion IBKR, pas de gestion de portefeuille automatique.

4. **Pas de machine learning en v1** — scoring purement quantitatif et déterministe. Reproductible et debuggable facilement.

5. **Univers limité aux actions US** — pas d'actions européennes ou asiatiques en v1 (yfinance est moins fiable sur ces marchés pour les fondamentaux).

---

_Document rédigé pour transmission à Claude (modèle de génération de code). Toutes les décisions d'architecture ont été prises pour maximiser la fiabilité des données et la maintenabilité du code, en tenant compte des contraintes de l'environnement Mac Mini local et des limites de l'API yfinance gratuite._
