# ValueMomentum Scanner 📊

Scanner quantitatif quotidien pour identifier des opportunités d'investissement basées sur la Qualité, la Valorisation et le Momentum.

## 🚀 Fonctionnalités
- **Scoring Actions (3 piliers)** :
  - **Qualité** : ROE, Marges opérationnelles, Dette/EBITDA, FCF Yield.
  - **Valorisation** : P/E Forward (intra-secteur), EV/EBITDA, PEG.
  - **Momentum** : Performance 6M/3M, surperformance sectorielle (vs SPDR ETFs).
- **Scoring ETFs** : Performance 6M, surperformance vs SPY, Volume Trend.
- **Orchestration** :
  - Scan automatique à 09h35 ET les jours de bourse (NYSE).
  - Notifications Telegram (HTML formaté).
  - Cache local pour éviter le rate-limiting.
  - Stockage historique des signaux en JSON.

## 🛠 Installation

### 1. Prérequis
- Python 3.11+
- Un Bot Telegram (créé via @BotFather)

### 2. Setup
```bash
# Entrer dans le dossier
cd bot-value

# Créer l'environnement virtuel
python3 -m venv venv
source venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt
```

### 3. Configuration
Créez un fichier `.env` à la racine :
```env
TELEGRAM_BOT_TOKEN=votre_token
TELEGRAM_CHAT_ID=votre_chat_id
```

#### Comment obtenir ces valeurs ?
1. **TELEGRAM_BOT_TOKEN** :
   - Ouvrez Telegram et cherchez le bot **@BotFather**.
   - Tapez `/newbot` et suivez les instructions.
   - @BotFather vous donnera un **API Token**.
2. **TELEGRAM_CHAT_ID** :
   - Cherchez le bot **@userinfobot** sur Telegram et envoyez-lui un message. Il vous répondra avec votre `Id`.

## 📈 Utilisation

### Mode Automatique (Production)
Le scheduler gère les jours fériés NYSE automatiquement.
```bash
source venv/bin/activate
python3 main.py
```

### Mode Manuel (Test immédiat)
Pour lancer un scan immédiatement :
```bash
source venv/bin/activate
PYTHONPATH=. python3 -c "from main import run_scanner; run_scanner()"
```

## 🖥️ Dashboard Web (Local)
Visualisez les résultats du dernier scan dans votre navigateur :
```bash
# Dans un terminal séparé
source venv/bin/activate
python3 -m http.server 8080
```
Puis ouvrez : `http://localhost:8080/web/`

## 📂 Structure des fichiers
- `scanner/` : Code source du moteur.
- `data/universe/` : Liste des tickers à scanner.
- `data/signals/` : Historique des scans quotidiens (JSON).
- `data/cache/` : Cache temporaire yfinance.
- `data/logs/` : Logs d'exécution quotidiens.

## ➕ Ajouter ou Modifier des valeurs (Stocks / ETFs)
Vous avez le contrôle total sur les actifs scannés. Tout se passe dans le fichier :
`data/universe/tickers_universe.json`

### Comment faire ?
1. Ouvrez le fichier avec un éditeur de texte.
2. Ajoutez vos tickers dans la liste correspondante :
   - `"stocks"` : Pour les entreprises (utilisera le scoring Qualité/Valo/Momentum).
   - `"etfs"` : Pour les fonds (utilisera le scoring simplifié Momentum/Volume).

**Exemple :**
```json
{
  "stocks": ["AAPL", "MSFT", "TSLA", "VOTRE_NOUVELLE_ACTION"],
  "etfs": ["SPY", "QQQ", "VOTRE_NOUVEL_ETF"]
}
```
### Mise à jour Automatique (S&P 500)
Si vous ne voulez pas taper les tickers à la main, vous pouvez demander au bot de récupérer automatiquement les 500 plus grandes entreprises américaines (S&P 500) :
```bash
source venv/bin/activate
PYTHONPATH=. python3 scanner/refresh_universe.py
```
Cela mettra à jour votre fichier `tickers_universe.json` instantanément.

> **Note** : Les filtres d'éligibilité (Market Cap > 500M, Prix > 5$) s'appliqueront toujours aux actions ajoutées. Si une action ne s'affiche pas dans le rapport, vérifiez les logs pour voir si elle a été exclue.

## 📝 Consultation des Logs
Les logs sont cruciaux pour surveiller le bot :
1. **Temps réel** : S'affichent dans votre terminal lors du scan.
2. **Fichiers d'archive** : Dans `data/logs/`.
   - Voir le dernier log : `tail -f data/logs/scanner_$(date +%Y-%m-%d).log`
   - Chercher une erreur : `grep "ERROR" data/logs/*.log`
