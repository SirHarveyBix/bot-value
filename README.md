# ValueMomentum Scanner 📊

Scanner quantitatif quotidien pour identifier des opportunités d'investissement basées sur la Qualité, la Valorisation et le Momentum.

---

## 📍 Sommaire

1. [🚀 Fonctionnalités](#-fonctionnalités)
2. [🛠 Installation](#-installation)
3. [⚙️ Configuration](#️-configuration)
4. [📈 Utilisation](#-utilisation)
5. [➕ Gestion de l'Univers](#-ajouter-ou-modifier-des-valeurs-stocks--etfs)
6. [🖥️ Dashboard Web](#️-dashboard-web-local)
7. [📝 Logs & Performance](#-consultation-des-logs--performance)
8. [📂 Structure du Projet](#-structure-des-fichiers)

---

## 🚀 Fonctionnalités

- **Filtres de Régime (Market Gate)** : Vérification de la tendance MA200 sur le SPY (Survie du capital).
- **Seuils Institutionnels** : Filtrage strict (Market Cap > 2B$, Volume > 5M$) pour éliminer le slippage.
- **ROE 3 ans** : Validation du Moat sur la durée.
- **Stockage SQLite** : Base de données robuste pour accès concurrents.
- **Pipeline en Entonnoir (Funnel)** :
  - **Étape 1 (Chalutier)** : Screening technique massif sur l'univers Large/Mid Cap.
  - **Étape 2 (Sniper)** : Analyse fondamentale institutionnelle via FMP (API) sur la shortlist.

## 🛠 Installation

### 1. Prérequis

- Python 3.11+
- Un Bot Telegram (via @BotFather)

### 2. Setup

```bash
cd bot-value
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## ⚙️ Configuration

Le scanner utilise un pipeline hybride : **yfinance** (gratuit, sans clé) pour les données de prix massives, et **Financial Modeling Prep (FMP)** pour les fondamentaux institutionnels de la shortlist.

### 1. Créer le fichier .env

Créez un fichier `.env` à la racine du projet en vous basant sur `.env.example`.

### 2. Obtenir vos identifiants

#### A. API Financial Modeling Prep (`FMP_API_KEY`)

1. Créez un compte gratuit sur [Financial Modeling Prep](https://financialmodelingprep.com/developer/docs/).
2. Récupérez votre clé API (le plan gratuit offre 250 appels/jour, suffisant pour le Sniper).

#### B. Token du Bot Telegram (`TELEGRAM_BOT_TOKEN`)

...

1. Cherchez **@BotFather** sur Telegram.
2. Envoyez la commande `/newbot`.
3. Suivez les instructions (nom du bot, username).
4. BotFather vous donnera un token (ex: `123456789:ABCDefgh...`). Copiez-le.

#### B. Votre Chat ID (`TELEGRAM_CHAT_ID`)

1. Cherchez **@userinfobot** sur Telegram.
2. Envoyez-lui n'importe quel message.
3. Il vous répondra avec votre `Id` (ex: `987654321`). Copiez-le.
   - _Note : Si vous utilisez un Canal, ajoutez votre bot comme Admin du canal et utilisez des outils comme @getidsbot pour trouver l'ID du canal (commence souvent par -100)._

### 3. Remplir le fichier .env

```env
TELEGRAM_BOT_TOKEN=votre_token_botfather
TELEGRAM_CHAT_ID=votre_id_userinfobot
FMP_API_KEY=votre_cle_fmp_gratuite
```

## 📈 Utilisation

### Mode Automatique (Production - Recommandé)

Pour garantir que le bot tourne 24/7 et redémarre en cas de crash ou de reboot du Mac Mini, utilisez **PM2** (voir Section 11 des Specs).

```bash
# Démarrage via PM2
pm2 start ecosystem.config.js
# Sauvegarder pour le reboot
pm2 save
```

### Mode Manuel (Test immédiat)

```bash
source venv/bin/activate
PYTHONPATH=. python3 -c "from main import run_scanner; run_scanner()"
```

## ➕ Ajouter ou Modifier des valeurs (Stocks / ETFs)

### 💡 Flux de Données

1. **Master List** (`data/universe/tickers_universe.json`) : La liste lue chaque matin.
2. **Refresh** (`refresh_universe.py`) : Outil pour remplir la liste via des indices mondiaux.

### Mise à jour Automatique

```bash
# S&P 500, Nasdaq 100, Inde (Nifty 50)
PYTHONPATH=. python3 scanner/refresh_universe.py sp500
PYTHONPATH=. python3 scanner/refresh_universe.py nasdaq100
PYTHONPATH=. python3 scanner/refresh_universe.py india
```

## 🖥️ Dashboard Web (Local)

Visualisez les résultats :

```bash
python3 -m http.server 8080
```

Accès : `http://localhost:8080/web/`

## 📝 Consultation des Logs & Performance

### ⏳ Temps d'exécution & Fiabilité

- **Durée** : Pour un univers large (700+ tickers), le scan prend environ **10 à 15 minutes**.
- **Pourquoi ?** Un délai volontaire est appliqué entre chaque ticker pour éviter le bannissement d'IP par Yahoo Finance.
- **Ressources** : Très faible consommation CPU/RAM, optimisé pour tourner 24/7 sur un Mac Mini.

### Lecture des Logs

1. **Fichiers** : `data/logs/` (Rotation quotidienne).
2. **Suivi** : `tail -f data/logs/scanner_$(date +%Y-%m-%d).log`

## 📂 Structure des fichiers

- `scanner/` : Moteur de scoring et fetcher.
- `data/universe/` : Listes de tickers.
- `data/signals/` : Historique des scans (JSON).
- `data/cache/` : Cache yfinance.
- `web/` : Interface HTML.
