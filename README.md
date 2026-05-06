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

- **Scoring Actions (3 piliers)** :
  - **Qualité** : ROE, Marges, Dette/EBITDA, FCF Yield.
  - **Valorisation** : P/E Forward (intra-secteur), EV/EBITDA, PEG.
  - **Momentum** : Performance 6M/3M, surperformance sectorielle relative.
- **Scoring ETFs** : Performance 6M, surperformance vs SPY, Volume Trend.
- **Orchestration** :
  - Scan automatique à 09h35 ET (NYSE).
  - Notifications Telegram (HTML).
  - Cache local & Scheduler intelligent.

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

Créez un fichier `.env` à la racine :

```env
TELEGRAM_BOT_TOKEN=votre_token
TELEGRAM_CHAT_ID=votre_chat_id
```

## 📈 Utilisation

### Mode Automatique (Production)

```bash
source venv/bin/activate
python3 main.py
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
