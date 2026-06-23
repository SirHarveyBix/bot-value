# API Contracts: ValueMomentum Scanner V1

**Branch**: `001-spec-review-fixes` | **Date**: 2026-05-19

---

## Module Interfaces Internes

### `fetcher.py` → `engine.py` (via `all_data`)

```python
all_data: dict[str, {
    "info": {
        # Identité
        "symbol": str,
        "source": "FMP",                    # toujours FMP — yfinance = OHLCV uniquement (Règle d'Or)
        "longName": str | None,
        "sector": str | None,               # None → exclusion pipeline Actions (sector_missing)
        "marketCap": int | None,

        # Pilier Qualité — tous via FMP
        "roe_ttm": float | None,
        "roe_3y": float | None,             # ROE moyen 3 ans (income-statement 3 périodes)
        "operatingMargins": float | None,
        "totalDebt": float | None,
        "totalCash": None,                  # Toujours None (FMP stable API n'expose pas totalCash)
        "netDebt": float | None,            # netDebtTTM via key-metrics-ttm
        "ebitda": float | None,
        "freeCashflow": float | None,       # freeCashFlowPerShareTTM × sharesOutstanding

        # Pilier Valorisation — via FMP ratios-ttm
        "forwardPE": float | None,
        "enterpriseToEbitda": float | None,
        "pegRatio": float | None,

        # Pilier Momentum fondamental — via FMP
        "surprise_pct": float | None,       # None — earnings-surprises endpoint indisponible plan gratuit
        "surprise_date": str | None,        # ISO 'YYYY-MM-DD' (pour décroissance temporelle)
        "analyst_revision_3m": float | None, # % révision EPS 3M (analyst-estimates endpoint)

        # Méta
        "bookValuePerShare": float | None,  # pour détection ROE gonflé par buybacks
        "roicTTM": float | None,           # None si FMP key-metrics-ttm manquant
    } | None,                               # None = ticker FMP indisponible (402/quota) ou FMPUnavailableError (401/403/5xx)

    "prices": pd.DataFrame | None          # OHLCV, index datetime UTC, colonnes Open/High/Low/Close/Volume
}]
```

### `engine.py` — Winsorisation obligatoire avant percentile ranking

Avant tout calcul de percentile, les ratios bruts sont clampés dans des plages réalistes (`RATIO_CLAMP`). Les valeurs hors plage (erreurs de parsing FMP : `0.001`, `999`) corrompent le ranking entier si non traitées.

```python
RATIO_CLAMP: dict[str, tuple[float, float]] = {
    "roe":              (0.0, 1.50),
    "operating_margin": (-0.50, 0.60),
    "fcf_yield":        (-0.20, 0.30),
    "debt_ebitda":      (0.0, 10.0),
    "pe_ratio":         (1.0, 60.0),
    "ev_ebitda":        (0.0, 40.0),
    "peg_ratio":        (-5.0, 5.0),
}

def winsorize(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
```

La winsorisation s'applique **après** les gates d'exclusion (ROE < 0, EV/EBITDA > 40 déjà gérés) et **avant** `percentile_rank()`.

---

### `engine.py` → `notifier.py` (via `top_10_stocks`)

```python
top_10_stocks: pd.DataFrame
# Colonnes garanties (jamais NaN en sortie d'engine) :
symbol: str
name: str
sector: str                         # toujours non-None (exclusion en amont)
mcap_b: float                       # marketCap / 1e9
roe: float
margin: float
score_quality: float                # [0, 100]
score_valuation: float | None       # None si v_ok=False
score_momentum: float               # [0, 100], après pénalités anti-extrême
score_global: float                 # [0, 100]
perf_6m: float
perf_1m: float                      # pour affichage contexte
outperf_6m: float | None
pe: float | None
surprise_pct: float
surprise_date: str | None
analyst_revision_3m: float | None
v_ok: bool                          # True = pilier Valorisation calculé
pe_flag: str | None                 # "TTM" si P/E Forward absent
earnings_date: str | None           # tag 📅 si dans les 14 prochains jours
warning: str | None                 # tag ⚠️ données périmées si > 120j
use_cross_universe_ranking: bool    # True = secteur < 3 tickers (info pour audit)
first_seen_date: str                # ISO 'YYYY-MM-DD' — depuis SQLite
```

### `engine.py` → `notifier.py` (via `market_regime`)

```python
market_regime: str
# Valeurs exactes :
"normal"     # Scan complet, pas de flag Telegram
"bear_light" # Scan complet, warning log interne uniquement
"prudence"   # Scan + flag ⚠️ RÉGIME DE PRUDENCE sur chaque signal
"panic"      # Scan annulé avant scoring — notify_panic() appelé depuis main.py
```

### `fetcher.py` exceptions

```python
class FMPUnavailableError(Exception):
    """Levée quand FMP est inaccessible (clé absente ou 5xx après FMP_MAX_RETRIES tentatives)."""
    pass
```

Propagation : `fetch_fmp_data()` → `fetch_ticker_info()` → `fetch_all_data()` → `main.py` (catch → `return`)

**Note** : HTTP 402 (ticker hors plan) et 404 ne lèvent pas `FMPUnavailableError` — ils retournent `None` et déclenchent le fallback yfinance dans `fetch_ticker_info`. Seuls 401/403 (auth) et 5xx persistants lèvent l'exception.

---

## FMP Endpoints Budget (30 tickers) — API `/stable/` (BF-010)

| Endpoint (`/stable/`)                                   | Appels  | Données extraites                         |
| ------------------------------------------------------- | ------- | ----------------------------------------- |
| `ratios-ttm?symbol={symbol}`                            | 30      | P/E, EV/EBITDA, marge op., FCF yield, PEG |
| `key-metrics-ttm?symbol={symbol}`                       | 30      | ROIC TTM, métriques complémentaires       |
| `profile?symbol={symbol}`                               | 30      | Secteur GICS, market cap, nom             |
| `income-statement?symbol={symbol}&limit=3`              | 30      | ROE moyen 3 ans (bilans annuels)          |
| `balance-sheet-statement?symbol={symbol}&limit=3`       | 30      | totalDebt, totalCash                      |
| ~~`earnings-surprises/{symbol}`~~                       | ~~30~~  | 404 plan gratuit — supprimé (BF-010)      |
| ~~`analyst-estimates/{symbol}?period=quarter&limit=3`~~ | ~~30~~  | 402 plan gratuit — supprimé (BF-010)      |
| **Total nominal**                                       | **150** | **+ 25 retry margin = 175 hard limit**    |

Circuit-breaker par ticker : 2 retries max. Après 2 échecs 5xx → skip + flag pour ce ticker uniquement.

**Disjoncteur global** (`FMP_CALL_BUDGET_HARD_LIMIT = 175`) : compteur `fmp_call_counter` incrémenté à chaque appel. Si `fmp_call_counter ≥ 175` → `fmp_fetch()` retourne `{}` immédiatement sans appel HTTP. Le scoring finalise avec les données disponibles. Flag `⚠️ Budget FMP proche du quota — shortlist partielle` ajouté au message Telegram.

```python
FMP_CALL_BUDGET_HARD_LIMIT = 175  # 30×5=150 nominal + 25 retry margin (BF-010)
fmp_call_counter: int = 0         # réinitialisé à chaque nouveau scan
```

**`FMPUnavailableError`** (cas global) : levée uniquement si FMP est inaccessible pour toute la shortlist (clé absente ou 5xx persistants avant même le 1er ticker). Propagée jusqu'à `main.py` → `send_fmp_error()` + arrêt du scan.

---

## Formats Messages Telegram

Tous les messages : `parse_mode="HTML"`, html.escape() sur toutes les strings, tronqués à 4096 chars.

### Signal stock standard

```
#1 📈 <b>Apple Inc.</b> ($AAPL)
Score Global : 87/100
├ Qualité     : 91/100
├ Valorisation: 78/100
└ Momentum    : 88/100

📈 Perf 6M : +18.3% vs secteur +5.2%
💰 P/E Fwd : 28.5 | ROE : 147.0%
🏢 Technology | Cap : $3100.0B
⏱️ Signal actif depuis : 23 jours
📅 Earnings : 2026-07-29
⚠️ données potentiellement périmées (125 j)
🔗 <a href='https://finance.yahoo.com/quote/AAPL'>Yahoo Finance</a>
```

Si régime "prudence" : prepend `⚠️ <b>RÉGIME DE PRUDENCE — SPY &lt; EMA200, VIX modéré</b>\n` à chaque signal.

### Signal ETF

```
#1 <b>XLK</b> — Technology Select Sector SPDR
Score : 82/100 | Perf 6M : +12.4% vs SPY +9.1%
🔗 <a href='https://finance.yahoo.com/quote/XLK'>Yahoo Finance</a>
```

### Régime Panique

```
🚨 <b>RÉGIME DE PANIQUE — SCAN ANNULÉ</b>
VIX : 40.2 &gt; 35
SPY : 450.10 vs EMA200 : 462.33
<i>Aucun signal émis. Capital preservation prioritaire.</i>
```

### FMP indisponible

```
⚠️ <b>Sniper FMP indisponible</b>
<i>Aucune clé API valide ou erreur 5xx persistante après 2 retries.
Scan arrêté — aucun signal émis.</i>
```

### Erreur technique

```
🚨 <b>ValueMomentum Scanner — ERREUR [DATE]</b>
Le scan quotidien a rencontré une erreur.
Module : [NOM_MODULE]
Erreur : [MESSAGE_COURT]
→ Vérifier les logs sur le Mac Mini.
```
