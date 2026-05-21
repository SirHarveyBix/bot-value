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
8. [Démarrage automatique au boot](#démarrage-automatique-au-boot-mac)
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
  - Étape 1 (Chalutier) : screening technique massif sur l'univers complet via yfinance (gratuit).
  - Étape 2 (Sniper) : analyse fondamentale institutionnelle via FMP API sur une shortlist de 30 tickers.

---

## Prérequis

- **macOS** (optimisé Mac Mini, mais fonctionne sur tout Mac)
- **Python 3.11+** — vérifiez avec `python3 --version`
- **Git** — pour cloner le projet
- **Compte Financial Modeling Prep** (gratuit) — limite nominale 250 appels/jour, disjoncteur hard limit à 245
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

## Déploiement Mac Mini

### Prévenir la mise en veille

Sur Mac Mini en production, désactivez tous les modes de veille pour éviter toute interruption :

```bash
sudo pmset -a sleep 0 disksleep 0 hibernatemode 0 powernap 0
```

| Option          | Valeur | Effet                               |
| --------------- | ------ | ----------------------------------- |
| `sleep`         | 0      | Désactive la mise en veille système |
| `disksleep`     | 0      | Disque jamais mis en veille         |
| `hibernatemode` | 0      | Pas d'hibernation                   |
| `powernap`      | 0      | Désactive les tâches en veille      |

### Installation complète sur Mac Mini

```bash
# 1. Cloner et configurer
git clone https://github.com/SirHarveyBix/bot-value.git
cd bot-value
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env   # Renseigner les 3 clés

# 2. Lancer supervisord (process manager)
supervisord -c supervisord.conf
supervisorctl -c supervisord.conf status   # Doit afficher scanner + web RUNNING
```

---

## Démarrage automatique au boot (Mac)

Pour que le scanner redémarre automatiquement au démarrage du Mac Mini, exécutez ce bloc **depuis le dossier du projet** :

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

Pour désinstaller :

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
