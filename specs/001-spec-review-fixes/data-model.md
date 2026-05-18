# Data Model: ValueMomentum Scanner V1

**Branch**: `001-spec-review-fixes` | **Date**: 2026-05-19

---

## SQLite Schema — `data/signals/scanner_history.db`

Mode WAL obligatoire sur chaque connexion : `PRAGMA journal_mode=WAL;`

### Table `scans`

```sql
CREATE TABLE IF NOT EXISTS scans (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_date        TEXT UNIQUE,          -- ISO 'YYYY-MM-DD'
    market_regime    TEXT,                 -- 'normal'|'bear_light'|'prudence'|'panic'
    spy_price        REAL,
    spy_ema200       REAL,
    vix              REAL,
    universe_size    INTEGER,              -- tickers après filtre éligibilité
    eligible_count   INTEGER               -- signaux émis (0 si panic)
);
```

### Table `signals`

```sql
CREATE TABLE IF NOT EXISTS signals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id             INTEGER,
    symbol              TEXT NOT NULL,
    name                TEXT,
    type                TEXT,             -- 'stock' | 'etf'
    rank                INTEGER,
    score_global        REAL,             -- [0, 100]
    score_quality       REAL,             -- [0, 100]
    score_valuation     REAL,             -- [0, 100] | NULL si pilier exclu
    score_momentum      REAL,             -- [0, 100]
    pe                  REAL,
    roe                 REAL,
    margin              REAL,
    perf_6m             REAL,
    -- Suivi temporel
    first_seen_date     TEXT,             -- ISO 'YYYY-MM-DD' — JAMAIS réinitialisé sur réapparition
    price_at_signal     REAL NOT NULL,    -- Prix de clôture au moment du signal
    price_30d_later     REAL,             -- Rempli par update_signal_returns() job
    return_30d          REAL,             -- (price_30d_later - price_at_signal) / price_at_signal
    price_90d_later     REAL,
    return_90d          REAL,
    -- Flags
    flags               TEXT,             -- JSON array: ["⚠️ données périmées", "📅 Earnings 2026-05-28"]
    FOREIGN KEY (scan_id) REFERENCES scans(id)
);
```

### Table `universe_metadata`

```sql
CREATE TABLE IF NOT EXISTS universe_metadata (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id             INTEGER,
    universe_file_date  TEXT,             -- dernière modification tickers_universe.json
    stocks_count        INTEGER,
    etfs_count          INTEGER,
    excluded_count      INTEGER,
    exclusion_reasons   TEXT,             -- JSON: {"sector_missing": 5, "eligibility_filter": 120, ...}
    FOREIGN KEY (scan_id) REFERENCES scans(id)
);
```

### Migration schema (colonnes ajoutées en V1)

```python
NEW_COLS = [
    "ALTER TABLE signals ADD COLUMN first_seen_date TEXT",
    "ALTER TABLE signals ADD COLUMN price_at_signal REAL",
    "ALTER TABLE signals ADD COLUMN price_30d_later REAL",
    "ALTER TABLE signals ADD COLUMN return_30d REAL",
    "ALTER TABLE signals ADD COLUMN price_90d_later REAL",
    "ALTER TABLE signals ADD COLUMN return_90d REAL",
    "ALTER TABLE signals ADD COLUMN flags TEXT",
]
for stmt in NEW_COLS:
    try:
        conn.execute(stmt)
    except sqlite3.OperationalError:
        pass  # colonne déjà existante
```

---

## JSON Cache — `data/cache/`

**Naming**: `fundamentals_{SYMBOL}.json`, `prices_{SYMBOL}.json`

**TTL**: fondamentaux 24h (`CACHE_TTL_FUNDAMENTALS = 86400`), prix 4h (`CACHE_TTL_PRICE_HISTORY = 14400`)

**Invalidation post-earnings**: si `surprise_date = J-1`, invalider le cache fondamentaux avant le scan.

```json
{
  "fetched_at": "2026-05-19T09:45:12.345678",
  "data": {
    "symbol": "AAPL",
    "source": "FMP",
    "longName": "Apple Inc.",
    "sector": "Technology",
    "marketCap": 3100000000000,
    "roe_ttm": 1.47,
    "roe_3y": 1.35,
    "operatingMargins": 0.308,
    "totalDebt": 97000000000,
    "totalCash": null,
    "netDebt": 52000000000,
    "ebitda": 130000000000,
    "freeCashflow": 111000000000,
    "forwardPE": 28.5,
    "enterpriseToEbitda": 22.4,
    "pegRatio": 1.8,
    "surprise_pct": 0.07,
    "surprise_date": "2026-02-06",
    "analyst_revision_3m": 0.03
  }
}
```

**Champ `totalCash`**: toujours `null` pour source FMP (Bug 2 fix). Utilisé uniquement dans le fallback yfinance (chemin retiré en V1).

---

## Universe — `data/universe/tickers_universe.json`

```json
{
  "stocks": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"],
  "etfs": [
    "XLC",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
    "SPY"
  ]
}
```

**Règles**:

- US-only (NYSE/NASDAQ/AMEX). Aucun ticker `.NS` ou hors-US.
- Cible : ~700 stocks. Mise à jour manuelle ≈ mensuelle.
- Les ETFs sectoriels SPDR pour le benchmark de surperformance (`SECTOR_ETF_MAP`) sont hardcodés dans `fetcher.py` — ne pas les dupliquer dans l'univers sauf si on veut les scorer dans le pipeline ETF.

---

## Entités Scoring (DataFrames internes)

### `price_data` (sortie Chalutier yfinance)

```python
price_data: dict[str, pd.DataFrame]
# key = symbol
# DataFrame colonnes : Open, High, Low, Close, Volume
# Index : datetime (UTC)
# Période : 1 an (252 jours de bourse minimum)
```

### `momentum_ranked_df` (sortie momentum_screening_pipeline)

```python
# colonnes :
symbol: str
perf_6m: float      # (Close[-1] - Close[-126]) / Close[-126]
perf_3m: float      # (Close[-1] - Close[-63]) / Close[-63]
perf_1m: float      # (Close[-1] - Close[-21]) / Close[-21]  — pour pénalité anti-extrême
outperf_6m: float   # perf_6m ticker - perf_6m ETF sectoriel SPDR
volume_dollar_20d: float
rank_momentum: int  # tri décroissant sur score momentum partiel
```

### `all_data` (sortie fetch_all_data — entrée Sniper)

```python
all_data: dict[str, {
    "info": dict | None,    # fondamentaux FMP — None si FMPUnavailableError
    "prices": pd.DataFrame | None
}]
```

### `top_10_stocks` (sortie stock_scoring_pipeline — entrée notifier)

```python
# colonnes :
symbol, name, sector, mcap_b,
roe, margin, debt_ebitda, fcf_yield,
pe, ev_ebitda, peg,
perf_6m, perf_3m, perf_1m, outperf_6m,
surprise_pct, surprise_date, analyst_revision_3m,
score_quality, score_valuation, score_momentum, score_global,
v_ok: bool,           # True si pilier Valorisation calculé
pe_flag: str | None,  # "TTM" si P/E Forward absent
earnings_date: str | None,
warning: str | None,
use_cross_universe_ranking: bool
```
