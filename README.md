# ValueMomentum Scanner

Scanner quantitatif quotidien pour identifier des opportunités d'investissement basées sur la Qualité, la Valorisation et le Momentum.

---

## Sommaire

1. [Stratégie](#stratégie)
2. [Ce que vous recevez](#ce-que-vous-recevez)
3. [Prérequis](#prérequis)
4. [Installation](#installation)
5. [Configuration](#configuration)
6. [Test rapide](#test-rapide)
7. [Tests unitaires & Qualité du code](#tests-unitaires--qualité-du-code)
8. [Mode production (24/7)](#mode-production-247)
9. [Déploiement Mac Mini (production complète)](#déploiement-mac-mini-production-complète)
10. [Gestion de l'univers de tickers](#gestion-de-lunivers-de-tickers)
11. [Dashboard Web](#dashboard-web)
12. [Logs](#logs)
13. [Structure des fichiers](#structure-des-fichiers)

---

## Stratégie

Le bot est conçu pour le **Position Trading** (horizon 3 à 6 mois). Il ne s'agit pas de day trading.

- **Philosophie** : Acheter des entreprises structurellement excellentes (ROE/ROIC composite stable sur 3 ans) au moment exact où le flux institutionnel valide la réévaluation (Momentum 6M ajusté à la volatilité + Surprise Résultats).
- **Scoring** : 3 piliers pondérés — Qualité 35% (ROE/ROIC composite, marge, FCF), Valorisation 30% (P/E Forward, EV/EBITDA, PEG), Momentum 35% (performance ajustée à la volatilité, surperformance sectorielle).
- **Gestion du risque** : Market Gate automatique à 4 niveaux (priorité VIX sur EMA200). En régime de panique (VIX > 35), le bot envoie une alerte et n'émet aucun signal.
- **Pipeline** :
  - Étape 1 (Chalutier) : screening technique massif sur l'univers complet via yfinance (gratuit) + plafond sectoriel 5 tickers/secteur.
  - Étape 2 (Sniper) : analyse fondamentale institutionnelle via FMP API sur une shortlist de 30 tickers (limite stricte 175 appels/jour).
  - Signaux : Top 10 actions avec pondération inverse-volatilité suggérée + Top 5 ETFs de rotation sectorielle.

---

## Ce que vous recevez

Chaque jour de bourse à 09h35 ET (heure de New York), le bot envoie une série de messages Telegram. Voici comment les lire.

---

### Le régime de marché (en tête de message)

Avant tout signal, le bot indique l'état du marché :

| Indicateur        | Signification                                                     | Action suggérée                                                     |
| ----------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------- |
| ✅ **NORMAL**     | Marché haussier (SPY au-dessus de sa moyenne 200 jours, VIX < 25) | Signaux fiables, fonctionnement standard                            |
| 🐻 **BEAR LIGHT** | SPY sous sa moyenne 200 jours, mais panique absente (VIX < 25)    | Signaux émis, vigilance accrue conseillée                           |
| ⚠️ **PRUDENCE**   | Tension visible (VIX entre 25 et 35)                              | Signaux émis avec avertissement — réduire les positions si possible |
| 🚨 **PANIQUE**    | VIX > 35 — crise systémique en cours                              | **Aucun signal émis.** Alerte uniquement. Ne rien acheter.          |

> Le VIX (indice de volatilité) est le thermomètre de la peur sur les marchés américains. Un VIX > 35 correspond à des crises comme mars 2020 (COVID) ou octobre 2008 (Lehman).

---

### Les signaux d'actions (Top 10)

Pour chaque action du Top 10, vous recevez un message de ce type :

```
#1
🚀 ACHAT (Nouveau signal)
📈 Apple Inc. ($AAPL)
Score Global : 87/100
├ Qualité     : 91/100
├ Valorisation: 72/100
└ Momentum    : 88/100

📈 Perf 6M : +18.4% vs secteur +5.2%
💰 P/E Fwd : 28.3 | ROE : 41.2%
🏢 Technology | Cap : $2850.0B
⏱️ Signal actif depuis : 12 jours
🔗 Yahoo Finance
```

**Ce que chaque ligne signifie :**

- **Score Global /100** : Note synthétique combinant les 3 piliers. Au-dessus de 75 = signal solide. En dessous de 60 = signal faible, présent uniquement par faute de mieux.
- **Qualité /100** : L'entreprise génère-t-elle des profits durables ? Calculé à partir du ROE (Retour sur Capitaux Propres) sur 3 ans, des marges opérationnelles, et du niveau d'endettement. Score > 80 = entreprise avec un avantage compétitif durable.
- **Valorisation /100** : L'action est-elle abordable par rapport à ses bénéfices attendus ? Calculé à partir du P/E Forward (prix divisé par les bénéfices prévus), de l'EV/EBITDA, et du PEG. Score > 70 = relativement bon marché dans son secteur.
- **Momentum /100** : Le marché commence-t-il à acheter cette action ? Calculé à partir de la performance sur 6 mois ajustée à la volatilité, et de la surperformance vs les autres entreprises du même secteur. Score > 75 = flux institutionnels en accélération visible.
- **Perf 6M / vs secteur** : La performance de l'action sur 6 mois, et l'écart avec son secteur (positif = surperforme ses concurrents du même secteur).
- **P/E Fwd** : Combien d'années de bénéfices attendus vous payez. P/E de 28 = vous payez 28 fois les bénéfices prévus pour l'année suivante. À comparer uniquement dans le même secteur (Tech à 35x est normal, Industrie à 35x est cher).
- **ROE** : Le pourcentage de profit que l'entreprise génère sur les capitaux propres. ROE de 41% = pour 100€ investis par les actionnaires, l'entreprise génère 41€ de profit par an. Au-dessus de 15% est considéré excellent.
- **Cap** : La capitalisation boursière en milliards de dollars. Le bot ne couvre que les entreprises au-dessus de 2 milliards de dollars (liquidité institutionnelle minimale).

**Les statuts de position :**

| Statut                       | Signification                                                |
| ---------------------------- | ------------------------------------------------------------ |
| 🚀 **ACHAT**                 | Nouveau signal, apparu aujourd'hui pour la première fois     |
| ⏳ **MATURATION** (Jour X/3) | Signal de 2 ou 3 jours — en phase de confirmation avant HOLD |
| 🟢 **HOLD** (X jours)        | Signal confirmé, présent depuis plus de 3 jours consécutifs  |

**Les avertissements possibles :**

- `📅 Earnings : 2026-06-15` — Des résultats trimestriels sont attendus dans moins de 14 jours. Le cours peut bouger fortement dans les deux sens le jour de la publication. Informatif uniquement — le bot ne bloque pas le signal.
- `⚠️ ROE possiblement gonflé par buybacks` — L'entreprise a massivement racheté ses propres actions, ce qui peut artificiellement élever le ROE. Le signal reste valide mais la qualité est à vérifier manuellement.
- `⚠️ données potentiellement périmées` — Les données financières datent de plus d'un an. Le signal est conservé mais les fondamentaux peuvent avoir changé depuis.

---

### Les sorties de position (🚨 SORTIE)

Si une action quitte votre Top 10, un message séparé est envoyé **avant** les signaux du jour :

```
🚨 SORTIE DE POSITION
━━━━━━━━━━━━━━━━━━━━━━━━━━
❌ Microsoft Corp. ($MSFT)
├ Raison: Rang 16 (>15) ou Score 68/100 (<70)
└ Détention consécutive: 47 jours
```

Cela signifie que l'action a glissé hors du Top 15 **ou** que son score global est passé sous 70/100. Ce n'est pas une vente automatique — c'est une information : la conviction du modèle sur ce titre a diminué. À vous de décider si vous souhaitez réduire ou conserver votre position.

---

### Les signaux d'ETF (Top 5)

```
#1 XLK — Technology Select Sector SPDR Fund
Score : 84/100
Perf 6M : +22.1% | vs SPY : +8.4%
🔗 Yahoo Finance — Technology Select Sector SPDR Fund
```

**Important : les ETFs ne sont pas des recommandations d'achat d'ETF.** Ce sont des indicateurs de **rotation sectorielle** — ils vous indiquent quels secteurs ont le momentum le plus fort en ce moment sur les marchés américains.

- **XLK** = Technologie, **XLV** = Santé, **XLF** = Finance, **XLE** = Énergie, **XLI** = Industrie, **XLB** = Matériaux, **XLRE** = Immobilier, **XLU** = Services aux collectivités, **XLC** = Communication, **XLP** = Consommation défensive, **XLY** = Consommation cyclique.
- Si XLK domine le Top ETFs depuis plusieurs semaines, le secteur technologique bénéficie des flux institutionnels en ce moment.
- Utilisez cette information pour **renforcer la conviction** sur les signaux actions : une action technologique dans le Top 10 est d'autant plus convaincante si XLK est aussi en tête des ETFs.

> Les ETFs sont scorés uniquement sur leur momentum (performance 6 mois vs SPY). Ils n'ont pas de score de Qualité ni de Valorisation — comparer leur score avec celui des actions n'a pas de sens.

---

### Le message épinglé (résumé permanent)

Après chaque scan, un message est **épinglé** en haut de votre conversation Telegram. Il remplace automatiquement le précédent et donne un coup d'œil immédiat :

```
📌 ValueMomentum — 2026-06-05
Régime : ✅ NORMAL
━━━━━━━━━━━━━━━━━━━━━━━━
🏆 Top stocks
  1. AAPL — 87/100 | Perf 6M +18.4%
  2. MSFT — 84/100 | Perf 6M +15.2%
  ...
📦 Top ETFs
  1. XLK — 82/100
  2. XLV — 78/100
━━━━━━━━━━━━━━━━━━━━━━━━
Commandes : /scan /status /help
```

---

### Ce que le bot ne fait pas

- Il **ne passe pas d'ordres** et ne se connecte à aucun compte de courtier.
- Il **ne garantit aucune performance** — les signaux sont basés sur des données historiques et des modèles quantitatifs. Les marchés peuvent contredire n'importe quel modèle.
- Il **n'adapte pas les signaux à votre profil de risque** — à vous de décider la taille de chaque position selon votre tolérance au risque.
- L'horizon cible est **3 à 6 mois** — ce n'est pas un outil de day trading. Les signaux peuvent mettre des semaines à se matérialiser.

---

## Prérequis

- **macOS** (optimisé Mac Mini, mais fonctionne sur tout Mac)
- **Python 3.11+** — vérifiez avec `python3 --version`
- **Git** — pour cloner le projet
- **Compte Financial Modeling Prep** (gratuit) — limite nominale 250 appels/jour, disjoncteur hard limit à 175 (30 tickers × 5 endpoints + marge retry)
- **Bot Telegram** — pour recevoir les alertes

---

## Installation

### 1. Cloner le projet

```bash
git clone https://github.com/SirHarveyBix/bot-value.git
cd bot-value
```

### 2. Créer l'environnement Python et installer les dépendances

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Configuration

Le scanner utilise un pipeline hybride : **yfinance** (gratuit, sans clé) pour les données de prix, et **Financial Modeling Prep (FMP)** pour les fondamentaux institutionnels.

### 1. Créer le fichier `.env`

```bash
cp .env.example .env
```

Ouvrez `.env` et renseignez les trois valeurs :

```env
TELEGRAM_BOT_TOKEN=votre_token_botfather
TELEGRAM_CHAT_ID=votre_id_userinfobot
FMP_API_KEY=votre_cle_fmp_gratuite
```

### 2. Obtenir les identifiants

#### A. Clé FMP (`FMP_API_KEY`)

1. Créez un compte gratuit sur [financialmodelingprep.com](https://financialmodelingprep.com/developer/docs/).
2. Copiez votre clé API depuis le tableau de bord.

#### B. Token du Bot Telegram (`TELEGRAM_BOT_TOKEN`)

1. Ouvrez Telegram, cherchez **@BotFather**.
2. Envoyez `/newbot` et suivez les instructions.
3. BotFather vous donnera un token (ex : `123456789:ABCDefgh...`).

#### C. Votre Chat ID (`TELEGRAM_CHAT_ID`)

1. Cherchez **@userinfobot** sur Telegram.
2. Envoyez-lui n'importe quel message.
3. Il répond avec votre `Id` (ex : `987654321`).

> **Canal Telegram** : ajoutez votre bot comme Admin du canal et utilisez @getidsbot pour l'ID (commence par `-100`).

### 3. Paramètres avancés (optionnel)

Les seuils de scoring et les filtres sont dans `config.yaml`. Vous pouvez les ajuster librement — le fichier est commenté.

---

## Test rapide

Pour vérifier que tout fonctionne **immédiatement** (même le weekend ou en dehors des heures de marché) :

```bash
source venv/bin/activate
python3 main.py --now --force
```

- `--now` : lance le scan et quitte (pas de scheduler).
- `--force` : ignore la vérification du calendrier NYSE.

⚠️ **Prérequis** : le fichier univers doit contenir ≥ 100 tickers. Si ce n'est pas fait, lancez d'abord `PYTHONPATH=. python3 scanner/refresh_universe.py sp500` (voir section [Gestion de l'univers](#gestion-de-lunivers-de-tickers)).

Un scan complet (~600 tickers) prend environ **10 à 15 minutes**. Vous recevrez un message Telegram à la fin.

---

## Commandes Telegram (depuis votre téléphone)

Une fois le bot lancé en mode scheduler (`python3 main.py`), vous pouvez lui envoyer des commandes directement depuis l'application Telegram :

| Commande  | Description                                                                                                    |
| --------- | -------------------------------------------------------------------------------------------------------------- |
| `/scan`   | Déclenche un scan immédiat (ignore le calendrier NYSE)                                                         |
| `/status` | Affiche la date et le régime de marché du dernier scan                                                         |
| `/aide`   | Explique le score, les piliers (qualité/momentum/valorisation), les gates d'exclusion et les régimes de marché |
| `/help`   | Liste toutes les commandes disponibles                                                                         |

> **Note** : le bot n'accepte les commandes que depuis votre `TELEGRAM_CHAT_ID` configuré dans `.env`. Les messages d'autres chats sont ignorés.
>
> **Garde concurrente** : si un scan est déjà en cours, `/scan` répond `⚠️ Scan déjà en cours, patientez.` plutôt que de lancer un second scan en parallèle (ce qui provoquerait un ban IP yfinance).

---

## Tests unitaires & Qualité du code

### Lancer les tests

```bash
source venv/bin/activate

# Tous les tests avec sortie détaillée
pytest tests/ -v --tb=short

# Un fichier spécifique
pytest tests/test_logic.py -v

# Un test précis
pytest tests/test_logic.py::test_market_gate_panic_vix_over_35 -v

# Tests en parallèle (si pytest-xdist installé)
pytest tests/ -n auto
```

> Les tests sont **hermétiques** (aucun appel réseau réel) : ils utilisent `freezegun` pour les dates, des mocks pour les APIs et des fixtures statiques pour les prix.

### Linter — Ruff

Le projet utilise **[Ruff](https://docs.astral.sh/ruff/)** comme linter et formateur (configuré dans `pyproject.toml`).

```bash
source venv/bin/activate

# Vérification lint
ruff check .

# Correction automatique
ruff check . --fix

# Vérification formatage
ruff format --check .

# Appliquer le formatage
ruff format .
```

### Pre-commit (optionnel)

Un hook pre-commit est configuré pour lancer Ruff automatiquement à chaque commit :

```bash
pip install pre-commit
pre-commit install
```

Les hooks s'exécutent ensuite à chaque `git commit`. Pour lancer manuellement sur tous les fichiers :

```bash
pre-commit run --all-files
```

### CI/CD

Les tests et le lint s'exécutent automatiquement sur GitHub Actions à chaque push/PR sur `main` (voir `.github/workflows/`).

---

## Mode production (24/7)

Le scanner est géré par **supervisord** (100% Python, inclus dans `requirements.txt`).

### Démarrer

```bash
source venv/bin/activate
supervisord -c supervisord.conf
```

### Vérifier le statut

```bash
source venv/bin/activate
supervisorctl -c supervisord.conf status
```

Vous devriez voir `scanner` et `web` en statut `RUNNING`.

### Arrêter

```bash
source venv/bin/activate
supervisorctl -c supervisord.conf shutdown
```

Le scanner se déclenche automatiquement chaque jour ouvré à **09h35 ET** (heure de New York). Les retours sont mis à jour à **18h00 ET**.

---

## Déploiement Mac Mini (production complète)

Séquence complète pour un Mac Mini en production 24/7.

### Étape 1 — Prévenir la mise en veille

```bash
sudo pmset -a sleep 0 disksleep 0 hibernatemode 0 powernap 0
```

| Option          | Valeur | Effet                               |
| --------------- | ------ | ----------------------------------- |
| `sleep`         | 0      | Désactive la mise en veille système |
| `disksleep`     | 0      | Disque jamais mis en veille         |
| `hibernatemode` | 0      | Pas d'hibernation                   |
| `powernap`      | 0      | Désactive les tâches en veille      |

### Étape 2 — Installation

```bash
git clone https://github.com/SirHarveyBix/bot-value.git
cd bot-value
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env   # Renseigner les 3 clés
```

### Étape 3 — Peupler l'univers de tickers (obligatoire au premier démarrage)

```bash
PYTHONPATH=. ./venv/bin/python scanner/refresh_universe.py sp500
PYTHONPATH=. ./venv/bin/python scanner/refresh_universe.py nasdaq100
```

### Étape 4 — Test rapide (vérifier la config avant prod)

```bash
./venv/bin/python main.py --now --force
# Vous devez recevoir un message Telegram dans les 10–15 minutes
```

### Étape 5 — Démarrage automatique au boot (LaunchAgent)

```bash
bash scripts/install-launchd.sh
```

Vérifier que le service est actif :

```bash
launchctl list | grep valuemomentum
# Un PID non-zéro = service en cours d'exécution
```

Vérifier supervisord :

```bash
./venv/bin/supervisorctl -c supervisord.conf status
# scanner    RUNNING   pid XXXXX, uptime 0:00:XX
# web        RUNNING   pid XXXXX, uptime 0:00:XX
```

### Désinstaller le LaunchAgent

```bash
launchctl unload ~/Library/LaunchAgents/com.valuemomentum.plist
rm ~/Library/LaunchAgents/com.valuemomentum.plist
```

---

## Gestion de l'univers de tickers

L'univers par défaut (`data/universe/tickers_universe.json`) contient ~40 tickers pour le test initial. Le scanner requiert **au minimum 100 tickers éligibles** pour lancer un scan. Pour peupler l'univers complet :

### Étape obligatoire avant le premier scan réel

```bash
source venv/bin/activate
pip install -r requirements.txt   # s'assure que lxml est installé

PYTHONPATH=. python3 scanner/refresh_universe.py sp500      # ~503 tickers S&P 500
PYTHONPATH=. python3 scanner/refresh_universe.py nasdaq100  # +100 tickers Nasdaq
```

Après cette étape, l'univers contient ~600 tickers et le scanner peut démarrer normalement.

### Sources disponibles

| Commande    | Source                 | Tickers            |
| ----------- | ---------------------- | ------------------ |
| `sp500`     | Wikipedia — S&P 500    | ~503               |
| `nasdaq100` | Wikipedia — Nasdaq-100 | ~100               |
| `india`     | Wikipedia — NIFTY 50   | 50 (suffixe `.NS`) |

> Un scan complet sur 600+ tickers prend **10 à 15 minutes** (délais volontaires entre chunks yfinance pour éviter le ban IP).

---

## Dashboard Web

Le dashboard est accessible à :

```
http://localhost:8080/
```

Il est démarré automatiquement par supervisord. Pour le lancer manuellement :

```bash
source venv/bin/activate
python3 -m http.server 8080 --directory web
```

---

## Logs

| Fichier                            | Contenu                                        |
| ---------------------------------- | ---------------------------------------------- |
| `data/logs/scanner_YYYY-MM-DD.log` | Log applicatif détaillé (rotation quotidienne) |
| `data/logs/scanner_stdout.log`     | Sortie standard du processus scanner           |
| `data/logs/scanner_stderr.log`     | Erreurs du processus scanner                   |
| `data/logs/supervisord.log`        | Log du process manager                         |

Suivi en temps réel :

```bash
tail -f data/logs/scanner_$(date +%Y-%m-%d).log
```

---

## Structure des fichiers

```
bot-value/
├── main.py                    # Point d'entrée principal
├── config.yaml                # Paramètres de scoring et filtres
├── supervisord.conf           # Configuration du process manager
├── requirements.txt           # Dépendances Python
├── .env                       # Secrets (non versionné)
├── .env.example               # Modèle de configuration
├── scanner/
│   ├── config.py              # Chargement config + logging
│   ├── fetcher.py             # Récupération données (yfinance + FMP)
│   ├── filters.py             # Filtres pré/post scoring
│   ├── notifier.py            # Envoi Telegram
│   ├── scoring/               # Moteur de scoring (qualité, valuation, momentum)
│   ├── storage.py             # Base de données SQLite
│   ├── universe.py            # Filtrage éligibilité
│   └── refresh_universe.py    # Rechargement de l'univers de tickers
├── data/
│   ├── universe/
│   │   └── tickers_universe.json   # Liste des tickers (versionné)
│   ├── signals/
│   │   └── scanner_history.db      # Historique SQLite (non versionné)
│   ├── cache/                      # Cache fondamentaux 24h (non versionné)
│   └── logs/                       # Logs rotation quotidienne (non versionné)
└── web/
    └── index.html             # Dashboard de visualisation
```
