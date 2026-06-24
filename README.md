# ValueMomentum Scanner

Scanner quantitatif quotidien pour identifier des opportunités d'investissement basées sur la Qualité, la Valorisation et le Momentum.

---

## Sommaire

1. [Stratégie](#stratégie)
2. [Prérequis](#prérequis)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Test rapide](#test-rapide)
6. [Tests unitaires & Qualité du code](#tests-unitaires--qualité-du-code)
7. [Mode production (24/7)](#mode-production-247)
8. [Déploiement Mac Mini (production complète)](#déploiement-mac-mini-production-complète)
9. [Gestion de l'univers de tickers](#gestion-de-lunivers-de-tickers)
10. [Dashboard Web](#dashboard-web)
11. [Logs](#logs)
12. [Structure des fichiers](#structure-des-fichiers)

---

## Stratégie

Le bot est conçu pour le **Position Trading** (horizon 3 à 6 mois). Il ne s'agit pas de day trading.

- **Philosophie** : Acheter des entreprises exceptionnelles (ROE stable sur 3 ans) au moment où le marché commence à les réévaluer à la hausse (Surprise Earnings + Momentum 6M).
- **Gestion du risque** : Market Gate automatique (SPY > EMA 200 + VIX < 25). En régime de panique (VIX > 35), le bot envoie une alerte et n'émet aucun signal.
- **Pipeline** :
  - Étape 1 (Chalutier) : screening technique massif sur l'univers complet via yfinance (prix OHLCV uniquement).
  - Étape 2 (Sniper) : analyse fondamentale via FMP API sur une shortlist de 30 tickers — résultats **cachés 7 jours** (fondamentaux trimestriels, quota FMP préservé).
- **Séparation stricte des sources** : yfinance = prix/momentum, FMP = fondamentaux (ROE, marge, dette). Aucun fallback croisé.

---

## Prérequis

- **macOS** (optimisé Mac Mini, mais fonctionne sur tout Mac)
- **Python 3.11+** — vérifiez avec `python3 --version`
- **Git** — pour cloner le projet
- **Compte Financial Modeling Prep** (gratuit) — 250 appels/jour, consommés **1 fois/semaine** grâce au cache 7 jours
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

Le scanner utilise une architecture à **sources découplées** :

| Source | Rôle | Fréquence |
|--------|------|-----------|
| **yfinance** | Prix OHLCV, momentum 6M, EMA200 | Quotidien |
| **FMP API** | Fondamentaux (ROE, marge, dette, P/E) | 1×/semaine via cache 7 jours |

> Les fondamentaux ne changent qu'à chaque publication trimestrielle. Le cache 7 jours évite de consommer les 250 appels/jour FMP quotidiennement — ils sont utilisés ~1 fois par semaine.

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

**Option recommandée — FMP Screener dynamique (v1.3.0+)**

Découvre automatiquement tous les titres US (NYSE/NASDAQ) répondant aux critères de liquidité (cap > 2B$, volume > 5M$/j). Non limité aux indices connus, inclut les mid-caps hors S&P 500.

```bash
source venv/bin/activate
PYTHONPATH=. python3 scanner/refresh_universe.py screener   # ~800-1500 tickers via FMP API
```

**Option fallback — Sources Wikipedia statiques**

```bash
PYTHONPATH=. python3 scanner/refresh_universe.py sp500      # ~503 tickers S&P 500
PYTHONPATH=. python3 scanner/refresh_universe.py nasdaq100  # +100 tickers Nasdaq
```

Après cette étape, l'univers contient suffisamment de tickers pour démarrer.

### Sources disponibles

| Commande    | Source                         | Tickers                 |
| ----------- | ------------------------------ | ----------------------- |
| `screener`  | FMP Stock Screener (dynamique) | ~800–1500 ⭐ recommandé |
| `sp500`     | Wikipedia — S&P 500            | ~503                    |
| `nasdaq100` | Wikipedia — Nasdaq-100         | ~100                    |
| `india`     | Wikipedia — NIFTY 50           | 50 (suffixe `.NS`)      |

> Un scan complet sur 800+ tickers prend **10 à 20 minutes** (délais volontaires entre chunks yfinance pour éviter le ban IP).

---

## Dashboard Web

Le dashboard est accessible à :

```
http://localhost:8080/
```

Il affiche le Top 10 actions avec scores, poids suggérés, régime de marché et signal insider buying (🏦). Il est démarré automatiquement par supervisord. Pour le lancer manuellement :

```bash
source venv/bin/activate
python3 -m http.server 8080 --directory web
```

Les données (`signals_latest.json`) sont copiées automatiquement dans `web/` à chaque scan — aucune configuration supplémentaire requise.

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
│   ├── cache.py               # Cache SQLite TTL namespaces FMP/yfinance
│   ├── config.py              # Chargement config + logging
│   ├── fetcher.py             # Récupération données (yfinance + FMP)
│   ├── filters.py             # Filtres pré/post scoring
│   ├── market_gate.py         # Filtre régime de marché (VIX + SPY momentum)
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
│   ├── cache/                      # Cache fondamentaux 7j FMP + sentinels 402 (non versionné)
│   └── logs/                       # Logs rotation quotidienne (non versionné)
└── web/
    └── index.html             # Dashboard de visualisation
```
