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
        "source": "FMP",                    # toujours FMP en V1 (pas de yfinance fallback)
        "longName": str | None,
        "sector": str | None,               # None → exclusion pipeline Actions (sector_missing)
        "marketCap": int | None,

        # Pilier Qualité — tous via FMP
        "roe_ttm": float | None,
        "roe_3y": float | None,             # ROE moyen 3 ans (income-statement 3 périodes)
        "operatingMargins": float | None,
        "totalDebt": float | None,
        "totalCash": None,                  # Toujours None (Bug 2 fix — FMP n'expose pas totalCash)
        "netDebt": float | None,            # netDebtTTM via key-metrics-ttm
        "ebitda": float | None,
        "freeCashflow": float | None,       # freeCashFlowPerShareTTM × sharesOutstanding

        # Pilier Valorisation — via FMP ratios-ttm
        "forwardPE": float | None,
        "enterpriseToEbitda": float | None,
        "pegRatio": float | None,

        # Pilier Momentum fondamental — via FMP
        "surprise_pct": float,              # 0.0 si absent (earnings-surprises endpoint)
        "surprise_date": str | None,        # ISO 'YYYY-MM-DD' (pour décroissance temporelle)
        "analyst_revision_3m": float | None, # % révision EPS 3M (analyst-estimates endpoint)

        # Méta
        "book_value_per_share": float | None,  # pour détection ROE gonflé par buybacks
    } | None,                               # None = FMPUnavailableError (toute la shortlist concernée)

    "prices": pd.DataFrame | None          # OHLCV, index datetime UTC, colonnes Open/High/Low/Close/Volume
}]
```

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

---

## FMP Endpoints Budget (30 tickers)

| Endpoint                                            | Appels  | Données extraites                         |
| --------------------------------------------------- | ------- | ----------------------------------------- |
| `ratios-ttm/{symbol}`                               | 30      | P/E, EV/EBITDA, marge op., FCF yield, PEG |
| `key-metrics-ttm/{symbol}`                          | 30      | ROE TTM, netDebt                          |
| `profile/{symbol}`                                  | 30      | Secteur GICS, market cap, nom             |
| `income-statement/{symbol}?limit=3`                 | 30      | ROE moyen 3 ans                           |
| `balance-sheet-statement/{symbol}?limit=1`          | 30      | totalDebt                                 |
| `earnings-surprises/{symbol}`                       | 30      | surprise_pct, surprise_date               |
| `analyst-estimates/{symbol}?period=quarter&limit=3` | 30      | analyst_revision_3m                       |
| **Total nominal**                                   | **210** | **Marge : 40 calls pour retries ciblés**  |

Circuit-breaker : 2 retries max par ticker. Après 2 échecs 5xx → `FMPUnavailableError` pour ce ticker.

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
