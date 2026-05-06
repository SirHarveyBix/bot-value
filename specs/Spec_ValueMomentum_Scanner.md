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

- Qualité : 40%
- Valorisation : 25%
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
Fréquence        : Quotidienne (jours de bourse US uniquement)
Déclenchement    : 09h30 ET (après ouverture NYSE)
Sortie principale : Alertes Telegram + fichier JSON historique
Environnement    : Mac Mini (serveur local), macOS
Langage          : Python 3.11+
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
- **Sortie** : Une "Shortlist" des 50 meilleurs potentiels techniques.

### Étape 2 : Le Sniper (API Officielle - ex: FMP)

- **Cible** : Le Top 50 issu du Chalutier.
- **Action** : Fetch des fondamentaux propres via API versionnée.
- **Calcul** : Qualité (ROE, Marges, Dette/EBITDA) et Valorisation (P/E, PEG).
- **Sortie** : Le Top 10 final envoyé sur Telegram.

> **Bénéfice** : Cette méthode protège contre le rate-limiting de yfinance (car les appels `.info` sont limités à 50) et contre l'imprécision des données gratuites sur les actions que vous allez réellement acheter.

---

## 3. Module 1 — Universe Builder

### 3.1 Univers de départ (Master List & Refresh Automatique)

L'univers est géré via un fichier JSON central (`tickers_universe.json`). Contrairement à la v1 initiale, le système supporte désormais le **rafraîchissement automatique** via `scanner/refresh_universe.py`.

- **S&P 500** : Import automatique depuis Wikipedia.
- **Nasdaq 100** : Import automatique.
- **Indices Mondiaux** : Support du NIFTY 50 (Inde) avec formatage `.NS`, et MSCI World.
- **Mode Explorer** : Possibilité d'importer n'importe quel tableau Wikipedia via URL custom pour une découverte de marché dynamique (ex: CAC 40, DAX).

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

---

## 3bis. Module 2 — Data Fetcher

### 2.1 Stratégie de fetch asynchrone (Non-bloquant)

Pour garantir que l'Event Loop d'asyncio ne gèle jamais (notamment pour les notifications Telegram et le scheduler), le fetcher utilise une approche hybride :

**Fetch prix OHLCV (yfinance via Threads) :**
`yfinance` étant purement synchrone, ses appels sont enveloppés dans des threads pour ne pas bloquer la boucle principale.

```python
# Utilisation de asyncio.to_thread pour libérer l'event loop
prices = await asyncio.to_thread(
    yf.download,
    tickers=" ".join(all_tickers),
    period="1y",
    group_by="ticker",
    auto_adjust=True,
    threads=True,
    progress=False
)
```

**Fetch fondamentaux (httpx pour FMP) :**
L'API FMP est interrogée via `httpx.AsyncClient` pour une asynchronicité native.

```python
async with httpx.AsyncClient() as client:
    response = await client.get(f"{base_url}/ratios-ttm/{symbol}?apikey={api_key}")
    data = response.json()
```

### 2.2 Rate limiting et résilience

Le système applique un **Rate Limiting Séquentiel** strict pour éviter le bannissement IP (Erreur 429) :

1. **Délai asynchrone** : Entre chaque appel `.info` (yfinance) ou API (FMP), un `await asyncio.sleep(INTER_REQUEST_DELAY)` est observé.
2. **INTER_REQUEST_DELAY** : Fixé à 1.0s par défaut pour garantir la pérennité de l'accès Yahoo Finance.
3. **MAX_RETRIES** : 3 tentatives avec backoff exponentiel asynchrone.
4. **Fallback** : Si FMP échoue sur un ticker de la shortlist, le système tente un fallback asynchrone vers `yf.Ticker(ticker).info` (via `to_thread`).

### 2.3 Validation des données reçues

```python
def is_valid_ticker_data(data: dict) -> bool:
    price = data.get("regularMarketPrice")  # None-safe check
    return price is not None and price > 0
```

> **Important** : `"regularMarketPrice" in data` est insuffisant — la clé peut exister avec valeur None. Toujours utiliser `.get()` + check de valeur.

### 2.4 Cache

```python
CACHE_TTL_FUNDAMENTALS = 24 * 3600   # 24h — fondamentaux changent peu entre résultats
CACHE_TTL_PRICE_HISTORY = 4 * 3600   # 4h — prix plus frais pour le momentum
```

**Invalidation post-earnings** : si un ticker est dans l'earnings calendar avec date = J-1 (résultats publiés la veille), son cache fondamentaux est invalidé forcément avant le scan.

**Structure cache entry :**

```json
{
  "ticker": "MSFT",
  "fetched_at": "2025-01-15T09:32:00Z",
  "expires_at": "2025-01-16T09:32:00Z",
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

Avant tout calcul de scoring ou d'éligibilité shortlist, le système vérifie la tendance globale du marché US.

- **Indicateur** : Moyenne Mobile Simple 200 jours (MA200) du SPY.
- **Règle de Survie** : Si `Prix SPY < MA200 SPY`, le marché est considéré en régime baissier (Bear Market).
- **Conséquence** : Le scan continue pour information, mais tous les signaux sont marqués d'une alerte critique `🚨 MARCHÉ BAISSIER (SPY < MA200) : EXPOSITION DÉCONSEILLÉE`. Aucun signal "Top Action" ne doit être considéré comme une recommandation d'achat immédiate dans ce régime.

### 4.1 Pipeline Actions : définition des critères

#### PILIER 1 : QUALITÉ (pondération 35%)

| Métrique             | Donnée yfinance                    | Calcul                                    | Ranking            |
| -------------------- | ---------------------------------- | ----------------------------------------- | ------------------ |
| ROE (Moyenne 3 ans)  | `ticker.financials`                | Moyenne du ROE sur les 3 derniers bilans  | Cross-universe     |
| Marge opérationnelle | `operatingMargins`                 | Valeur directe                            | Intra-secteur GICS |
| Dette nette / EBITDA | `totalDebt`, `totalCash`, `ebitda` | Calcul : (totalDebt - totalCash) / ebitda | Cross-universe     |
| FCF Yield proxy      | `freeCashflow`, `marketCap`        | freeCashflow / marketCap                  | Cross-universe     |

> **Note ROE** : `yfinance` retourne uniquement le ROE TTM via `returnOnEquity`. La moyenne 3 ans nécessite `ticker.financials` (3 bilans annuels) — complexité supplémentaire documentée dans le Module 2. En v1, ROE TTM est utilisé comme proxy. Si la stabilité du ROE est critique, v1.1 pourra ajouter la moyenne glissante.

> **Note secteurs exclus du calcul dette/EBITDA** : Financières (banques, assurances) et REITs ont des structures bilancielles incompatibles avec ce ratio. Traitement spécifique documenté en section 4.4.

**Règle de qualité minimale (gate, non scoré) :**

- ROE < 0% → ticker exclu du scoring (business structurellement défaillant)
- EBITDA ≤ 0 → ticker exclu (ratio dette/EBITDA sans sens + business déficitaire)
- Dette nette / EBITDA > 6x → exclu (risque bilan trop élevé)

**Score Qualité** = moyenne pondérée des 4 percentile rangs

- ROE (TTM) : 40%
- Marge opérationnelle : 35%
- FCF Yield proxy : 15%
- Dette/EBITDA (inversé) : 10%

---

#### PILIER 2 : VALORISATION (pondération 30%)

| Métrique    | Donnée yfinance      | Calcul                    | Ranking            |
| ----------- | -------------------- | ------------------------- | ------------------ |
| P/E Forward | `forwardPE`          | Valeur directe (inversée) | Intra-secteur GICS |
| EV/EBITDA   | `enterpriseToEbitda` | Valeur directe (inversée) | Intra-secteur GICS |
| PEG Ratio   | `pegRatio`           | Valeur directe (inversée) | Cross-universe     |

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
> - P/E Forward absent → utiliser P/E TTM avec pénalité de -5 points sur le **score pilier Valorisation** (pas le score global). Si P/E TTM aussi négatif → appliquer le gate P/E négatif normalement.
> - Aucun P/E disponible → pilier Valorisation exclu. Score global recalculé : `score_qualite * 0.50 + score_momentum * 0.50` (renormalisé sur 100). Flag `⚠️ Valorisation non calculée` ajouté.
> - PEG Ratio absent (fréquent) → critère PEG exclu du pilier. Les 20% sont redistribués : P/E Forward → 56%, EV/EBITDA → 44%.
>
> **Règle NaN dans percentile ranking** : tout sous-critère avec valeur NaN ou manquante est exclu du calcul du percentile pour ce ticker. Si plus de 2 sous-critères d'un pilier sont NaN, le pilier entier est exclu (voir logique de repondération ci-dessus).

---

#### PILIER 3 : MOMENTUM (pondération 35%)

| Métrique                      | Calcul                                         | Ranking        |
| ----------------------------- | ---------------------------------------------- | -------------- |
| Performance 6 mois            | (Prix J0 - Prix J-126) / Prix J-126            | Cross-universe |
| Performance 3 mois            | (Prix J0 - Prix J-63) / Prix J-63              | Cross-universe |
| Surperformance sectorielle 6M | Perf 6M ticker - Perf 6M ETF sectoriel SPDR    | Intra-secteur  |
| Traction Fondamentale (proxy) | `revenueGrowth` (TTM yfinance) — croissance CA | Cross-universe |

> **Définition Prix J0** : close du dernier jour de bourse disponible avant le déclenchement du scan (= close J-1). À 09h30 ET, le marché vient d'ouvrir — les prix intraday ne sont pas utilisés. `yf.download(ticker, period="1d")["Close"].iloc[-1]` du jour précédent.

> **Honnêteté sur le Momentum Fondamental** : En l'absence de données de révision de consensus (donnée forward-looking payante) au niveau du screening global, nous utilisons la croissance du chiffre d'affaires TTM. C'est un indicateur **rétrospectif** (backward-looking). Pour pallier cela, le système utilise l'API FMP à l'étape 2 (Sniper) pour valider la traction fondamentale avec des données institutionnelles.

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

**Score Momentum** = moyenne pondérée :

- Perf 6 mois : 30%
- Surperf sectorielle 6M : 35%
- Perf 3 mois : 20%
- Traction Fondamentale (CA) : 15%

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

### 4.3 Pipeline ETFs (score simplifié)

Pour les ETFs, le scoring est purement asymétrique et se concentre sur l'action des prix, excluant le volume (potentiellement toxique en cas de panique) :

| Critère            | Calcul                              | Pondération |
| ------------------ | ----------------------------------- | ----------- |
| Performance 6 mois | (Prix J0 - Prix J-126) / Prix J-126 | 50%         |
| Surperf vs SPY 6M  | Perf 6M ETF - Perf 6M SPY           | 50%         |

> **Note Volume** : Le critère de volume a été supprimé. Une hausse de volume sur un ETF peut signifier une panique vendeuse (liquidation). Le scoring se concentre sur la surperformance relative et le momentum lissé.

### 4.4 Traitement spécifique des secteurs atypiques

Certains secteurs ont des structures financières incompatibles avec les métriques standard :

| Secteur GICS | Problème                                        | Traitement v1                                                                             |
| ------------ | ----------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Financials   | Passif = dépôts clients, pas de dette "normale" | Exclure dette/EBITDA du calcul. Pilier Qualité sur 3 critères (ROE, marge op., FCF yield) |
| Real Estate  | FFO ≠ earnings GAAP, EBITDA non standard        | Idem Financials : exclure dette/EBITDA                                                    |
| Health Care  | Biotechs pré-revenus : P/E négatif systématique | Gate P/E négatif suspendu si secteur = Health Care ET marketCap < 5B$                     |

> Ces exceptions s'appliquent automatiquement via le champ `sector` yfinance. Elles doivent être loggées explicitement dans les exclusions pour auditabilité.

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

### 5.3 Diversification forcée

Pour éviter que le top 10 soit dominé par un seul secteur :

- Maximum 3 tickers du même secteur GICS dans le top 10
- Si un secteur dépasse 3 représentants, le 4ème est remplacé par le meilleur ticker hors top 10 actuel n'appartenant pas aux secteurs déjà au plafond (tri décroissant par score global sur le reste de la liste)

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

> **Architecture async** : `python-telegram-bot==21.x` est async-first (asyncio). Pour éviter tout conflit d'Event Loop et garantir une fiabilité institutionnelle, le système utilise **APScheduler 4.x (v4.0.0a5+)** qui est nativement asynchrone. Cela permet au planificateur de partager la même boucle d'événements que Telegram et httpx, évitant les blocages et les crashs silencieux.

---

## 7. Module 6 — Storage & History (SQLite)

### 7.1 Stratégie de stockage

Le stockage repose sur une base de données **SQLite** (`data/signals/scanner_history.db`) pour garantir l'intégrité des données lors d'accès concurrents (Bot + Dashboard Web).

### 7.2 Structure de la base de données

- **Table `scans`** : Enregistre chaque run (date, métriques marché comme SPY MA200).
- **Table `signals`** : Stocke les signaux Top 10 et Top 5 ETFs avec tous leurs scores et métriques.
- **Table `universe_metadata`** : Historique de la taille de l'univers et des exclusions.

### 7.3 Cache (JSON persistant)

```
data/
├── universe/
│   ├── tickers_universe.json          # Fichier statique mis à jour mensuellement
│   └── eligible_universe_YYYY-MM-DD.json  # Univers filtré du jour
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

## 8. Interface HTML (v1.0 Statique / v1.1 Dynamique)

### 8.1 Approche v1.0

Une page HTML statique générée quotidiennement depuis le JSON `signals_latest.json`.

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

```
# requirements.txt
# Versions épinglées — mettre à jour explicitement, pas de wildcards pip

# Données marché
yfinance>=0.2.40,<0.3.0
pandas>=2.1.0,<3.0.0
numpy>=1.26.0,<2.0.0          # >= 1.26 requis par pandas 2.x

# Scheduling
APScheduler>=3.10.0,<4.0.0    # 3.x = synchrone, compatible avec asyncio.run()
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

> **Note async** : `python-telegram-bot 21.x` est async. Nous utilisons `AsyncIOScheduler` (APScheduler 3.x) pour une intégration native. La boucle d'événement est gérée par `asyncio.run(main())` qui maintient le scheduler actif.

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

Les données fondamentales (P/E, ROE, marges) ne changent pas d'un jour à l'autre entre les publications de résultats. Les fetcher en cache avec un TTL de 24h pour éviter d'interroger yfinance 600 fois par run.

```python
# Règle de cache
CACHE_TTL_FUNDAMENTALS = 24 * 3600   # 24 heures
CACHE_TTL_PRICE_HISTORY = 4 * 3600   # 4 heures (prix intraday)
```

### 13.4 Fragilité du Scraping (yfinance)

L'utilisation de `yfinance` présente un risque structurel car il s'agit d'un wrapper non-officiel. En cas de changement majeur de Yahoo Finance :

1. **Surveillance** : Le bot logue tout échec de fetch. Si le ratio de données valides tombe sous 60%, le scan s'arrête.
2. **Maintenance** : Une mise à jour régulière de la bibliothèque `yfinance` est nécessaire.
3. **Roadmap v2** : Envisager la migration vers une API officielle (AlphaVantage, FMP) pour la stabilité long-terme.

---

## 14. Tests

### 14.1 Tests unitaires obligatoires avant déploiement

Le projet utilise `pytest` pour valider la logique métier. Les tests couvrent :

**Logic & Scoring (`tests/test_logic.py`) :**

- `test_quality_logic()` : Vérifie le calcul du ROE, Dette/EBITDA (avec fallback FMP/yfinance) et les gates d'exclusion.
- `test_valuation_logic()` : Vérifie les limites de P/E par secteur (80 pour Tech/Health, 50 ailleurs).
- `test_momentum_logic()` : Vérifie le calcul des performances 3M/6M et le proxy de croissance CA.
- `test_momentum_penalties()` : Valide les pénalités anti-momentum extrême (>25% ou <-20% sur 1 mois).
- `test_etf_pipeline()` : Valide le nouveau scoring 50/50 Pur Prix (sans volume).
- `test_sector_diversification()` : Vérifie que le Top 10 ne contient pas plus de 3 tickers du même secteur.
- `test_sector_exceptions()` : Valide les exceptions pour les Financials (dette) et Biotechs (P/E).

**Intégration & Fetcher (`tests/test_scoring_engine.py`) :**

- `test_scoring()` : Test de bout en bout récupérant des données réelles (yfinance/FMP) pour valider le pipeline complet.

---

## 15. Roadmap et évolutions futures

### v1.0 (scope actuel)

- [x] Scanner quotidien Actions + ETFs
- [x] Scoring 3 piliers (Qualité, Valorisation, Momentum)
- [x] **Intégration API FMP** pour le Sniper (fondamentaux fiables)
- [x] Alertes Telegram
- [x] Stockage JSON

### v1.1

- [ ] Interface HTML viewer
- [ ] Migration vers **SQLite** pour le stockage historique
- [ ] Historique de performance des signaux (track record)

---

## 16. Contraintes et hypothèses de développement

1. **Hybride yfinance / FMP** : yfinance est utilisé pour le volume (prix OHLCV) et FMP pour la précision (fondamentaux shortlist). Le bot doit pouvoir fonctionner avec yfinance seul si la clé FMP est absente (fallback).

2. **Le Mac Mini est en local** — pas de cloud. Le stockage reste local (JSON puis SQLite).

3. **Aucun ordre n'est exécuté** — ce système est un scanner de décision.

4. **Focus Prix pour les ETFs** : Le volume est exclu du scoring ETF pour éviter les faux signaux de panique/liquidation.

5. **Univers limité aux actions US** — focus initial sur la fiabilité des données.

---

_Document rédigé pour transmission à Claude (modèle de génération de code). Toutes les décisions d'architecture ont été prises pour maximiser la fiabilité des données et la maintenabilité du code, en tenant compte des contraintes de l'environnement Mac Mini local et des limites de l'API yfinance gratuite._
\_
