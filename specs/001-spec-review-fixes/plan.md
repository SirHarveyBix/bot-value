# Implementation Plan: ValueMomentum Scanner V1 — Spec Review Fixes

**Branch**: `001-spec-review-fixes` | **Date**: 2026-05-19 | **Spec**: `specs/001-spec-review-fixes/spec.md`

**Input**: Feature specification from `/Users/guillaume/code/bot-value/specs/001-spec-review-fixes/spec.md`

---

## Summary

The ValueMomentum Scanner V1 is a quantitative scanning bot that runs daily at 09h35 ET on NYSE trading days, fetching OHLCV data for ~700 tickers via yfinance (Chalutier), scoring the top 30 momentum candidates with FMP fundamental data (Sniper), and dispatching a Telegram report with Top 10 stocks and Top 5 ETFs scored on Quality (35%), Valuation (30%), and Momentum (35%).

This feature branch corrects **4 critical bugs** that cause silent crashes or wrong budget consumption, implements **9 missing behaviors** mandated by the constitution v1.1.0, and brings the test suite to hermetic isolation (VCR + Freezegun).

---

## Technical Context

**Language/Version**: Python 3.11 (Mac Mini local, no Docker, no CI/CD)

**Primary Dependencies**: yfinance 0.2.x, httpx 0.27.x (FMP async), python-telegram-bot 21.x, APScheduler 4.0a5 (AsyncScheduler), pandas 2.1, numpy 1.26, pandas-market-calendars 4.3, loguru, PyYAML, python-dotenv, vcrpy, freezegun, pytest-asyncio

**Storage**: SQLite WAL (`data/signals/scanner_history.db`), JSON file cache (`data/cache/`), static JSON universe (`data/universe/tickers_universe.json`)

**Testing**: pytest 8.x, pytest-asyncio, pytest-vcr + vcrpy (cassette network isolation), freezegun (temporal determinism)

**Target Platform**: macOS Mac Mini, asyncio event loop, single process

**Performance Goals**: Full scan ≤ 15 minutes from 09h35 ET trigger to Telegram receipt; FMP budget ≤ 250 calls/day

**Constraints**: FMP free-tier ≤ 250 calls/day (hard limit); SQLite WAL for concurrent access; no blocking calls in asyncio loop; all strings html.escape()'d before Telegram; messages truncated at 4096 chars

---

## Constitution Check

- [x] **I. Funnel Architecture**: Chalutier (yfinance OHLCV only) / Sniper (FMP 30 tickers max) strictly separated. Bug 3 fix (head(50) → head(30)) and Lacune 13 fix (no yfinance fundamental fallback) enforce this.
- [x] **II. Quality & Stability**: ROE 3Y from FMP `income-statement` (3 periods), never yfinance TTM. Data freshness at 120d warning / 180d exclusion in `filters.py`. Lacune 7 (sector=None exclusion) added to quality gate.
- [x] **III. Market Gate**: Bug 4 fix upgrades 2-level (bull/stress) to 4-level VIX-priority cascade: Panique (VIX > 35 regardless of SPY), Prudence (SPY < EMA200 AND 25 < VIX ≤ 35), Bear Light (SPY < EMA200 AND VIX ≤ 25), Normal.
- [x] **IV. Institutional Liquidity**: Existing filters (Cap > 2B, Vol > 5M USD 20d, Price > 5, NYSE/NASDAQ/AMEX) preserved. Universe US-only (no `.NS` tickers).
- [x] **V. Quantitative Momentum**: 5th criterion (analyst estimate revisions via FMP `analyst-estimates`, weight 10%) added. Earnings surprise decay formula (linear 90-day per-row) implemented.
- [x] **VI. Sector GICS Integrity**: sector=None → exclusion with `sector_missing` log. Intra-sector < 3 tickers → automatic cross-universe fallback. MIN_UNIVERSE_SIZE=100 check.
- [x] **VII. Signal Persistence**: first_seen_date conserved on ticker reappearance. Score-driven exit only.
- [x] **Technical Standards**: SQLite WAL, asyncio APScheduler 4.x, jitter 0.8–1.5s, FMP circuit-breaker 2 retries, html.escape() + 4096-char truncation on all Telegram messages.
- [x] **Quality Gates**: VCR.py cassettes for all integration tests, Freezegun for Market Gate + earnings decay, FMP budget mock counter test.

---

## Project Structure

### Documentation (this feature)

```text
specs/001-spec-review-fixes/
├── plan.md              # This file
├── spec.md              # Feature user stories and requirements
├── research.md          # Architecture decisions and rationale
├── data-model.md        # SQLite + cache + universe schema
└── contracts/
    └── api-contracts.md # Module interfaces + Telegram message formats
```

### Source Code — Files Modified

```text
main.py                        # Bugs 1, 3, 4
config.yaml                    # Lacune 12 — missing constants
scanner/
  universe.py                  # max_workers_universe: 2→4
  fetcher.py                   # Bug 2, Lacune 5, Lacune 13
  notifier.py                  # Lacune 9, Lacune 10, regime string fix
  storage.py                   # Lacune 11
  scoring/
    quality.py                 # Lacune 7
    momentum.py                # Lacune 5, Lacune 6
    engine.py                  # Lacune 6, Lacune 8, MIN_UNIVERSE_SIZE
tests/
  test_logic.py                # 13 new unit tests
  test_integration_vcr.py      # 3 new integration tests
  cassettes/                   # VCR cassette directory (must be created)
```

---

## Complexity Tracking

No constitution violations in this plan. All changes reduce divergence from the constitution.

---

## Phase 0 — Bugs Bloquants (Priorité Absolue)

**Hard prerequisite for everything. Fix these first.**

### Bug 1 — NameError `main.py:107`

**Error**: `await notify(..., market_regime=regime)` — `regime` is undefined. Variable is `market_regime`.  
**Impact**: Every run silently crashes after scoring. No Telegram notification ever sent.  
**Fix**: `market_regime=regime` → `market_regime=market_regime`

### Bug 2 — `fetcher.py` : `totalCash = netDebtTTM`

**Error**: `"totalCash": k.get("netDebtTTM")` — Net Debt ≠ Total Cash. Corrupts debt/EBITDA calculation in `quality.py` fallback path.  
**Fix**: `"totalCash": None` — FMP `key-metrics-ttm` does not expose raw totalCash. `net_debt` field already maps `netDebtTTM` correctly. The direct `net_debt / ebitda` path in `quality.py` is used when FMP is source.

### Bug 3 — `main.py:78` : `.head(50)` → `.head(30)`

**Error**: 50 tickers × 7 FMP endpoints = 350 calls/day → quota exhausted mid-run.  
**Fix**: `.head(CONFIG["scanner"]["shortlist_size"])` (default 30 via config.yaml — added in Phase 1).

### Bug 4 — Market Gate: 2-level → 4-level VIX-priority cascade

**Error**: Current: 3 branches (stress/bear_light/bull). VIX > 35 not distinct from Prudence. SPY position checked before VIX.

**Fix**:

```python
VIX_PANIC = CONFIG["scanner"]["vix_panic_threshold"]    # 35
VIX_WARN  = CONFIG["scanner"]["vix_warning_threshold"]  # 25

if current_vix > VIX_PANIC:
    market_regime = "panic"
elif current_spy < ema200 and current_vix > VIX_WARN:
    market_regime = "prudence"
elif current_spy < ema200:
    market_regime = "bear_light"
else:
    market_regime = "normal"

if market_regime == "panic":
    save_scan_entry(market_data)           # 1 row scans, 0 rows signals
    await notify_panic(current_vix, current_spy, ema200)
    return
```

---

## Phase 1 — Infrastructure Config

### Lacune 12 — `config.yaml` : constantes manquantes

Add to `config.yaml` under `scanner:`:

```yaml
  shortlist_size: 30
  vix_panic_threshold: 35
  vix_warning_threshold: 25
  max_workers_universe: 4        # rename from max_workers (was defaulting to 8 in code)
  fmp_max_retries: 2
  min_universe_size: 100
  telegram_max_chars: 4096
  min_tickers_intra_sector: 3
```

Update `universe.py` to read `CONFIG["scanner"]["max_workers_universe"]`.

---

## Phase 2 — Moteur Momentum

### Lacune 5 — 5ème critère : révision estimations analystes

**Files**: `scanner/fetcher.py` (7th FMP endpoint), `scanner/scoring/momentum.py` (metric calc), `scanner/scoring/engine.py` (rank + score), `config.yaml` (weights)

**FMP endpoint**: `GET /analyst-estimates/{symbol}?period=quarter&limit=3&apikey={key}`

**Budget**: 7 × 30 = 210 calls nominal — within 250 quota.

**Metric**:
```python
def compute_analyst_revision_3m(estimates: list) -> float | None:
    if len(estimates) < 2:
        return None
    current_eps = estimates[0].get("estimatedEpsAvg")
    prev_eps = estimates[-1].get("estimatedEpsAvg")
    if not current_eps or not prev_eps or abs(prev_eps) < 1e-6:
        return None
    return (current_eps - prev_eps) / abs(prev_eps)
```

**New weights** in `config.yaml`:
```yaml
momentum_subweights:
  perf_6m: 0.30
  outperf_6m: 0.30        # was 0.35
  perf_3m: 0.15           # was 0.20
  surprise_earnings: 0.15
  analyst_revision: 0.10  # NEW
```

### Lacune 6 — Redistribution poids earnings decay (per-row)

**File**: `scanner/scoring/engine.py`

```python
def compute_momentum_weights(surprise_date: str | None, base_weights: dict, today) -> dict:
    w = base_weights.copy()
    if surprise_date:
        from datetime import date as _date
        days_since = (today - _date.fromisoformat(surprise_date)).days
        effective_surprise = w["surprise_earnings"] * max(0.0, 1.0 - days_since / 90)
    else:
        effective_surprise = 0.0
    freed = w["surprise_earnings"] - effective_surprise
    w["surprise_earnings"] = effective_surprise
    if freed > 0:
        others = {k: v for k, v in w.items() if k != "surprise_earnings"}
        total_others = sum(others.values())
        for k in others:
            w[k] += freed * (w[k] / total_others)
    return w
```

Freezegun mandatory in tests.

---

## Phase 3 — Pilier Qualité

### Lacune 7 — Exclusion `sector = None`

**File**: `scanner/scoring/engine.py` (in `stock_scoring_pipeline()`)

```python
if info.get("sector") is None:
    logger.warning(f"Exclusion {symbol}: sector=None (sector_missing)")
    continue
```

### Lacune 8 — Intra-sector fallback < 3 tickers + MIN_UNIVERSE_SIZE

**File**: `scanner/scoring/engine.py`

```python
# MIN_UNIVERSE_SIZE check before percentile ranking
if len(scored_rows) < CONFIG["scanner"]["min_universe_size"]:
    logger.warning(f"universe_too_small ({len(scored_rows)} tickers)")
    return pd.DataFrame()

# Intra-sector fallback
sector_counts = df["sector"].value_counts()
min_s = CONFIG["scanner"]["min_tickers_intra_sector"]
small_sectors = set(sector_counts[sector_counts < min_s].index)
# For intra-sector columns: tickers in small_sectors use cross-universe rank
```

---

## Phase 4 — Notifier

### Lacune 9 — Templates Panique + FMP indisponible

**File**: `scanner/notifier.py`

```python
async def notify_panic(vix: float, spy: float, ema200: float):
    msg = (
        "🚨 <b>RÉGIME DE PANIQUE — SCAN ANNULÉ</b>\n"
        f"VIX : {vix:.1f} &gt; 35\n"
        f"SPY : {spy:.2f} vs EMA200 : {ema200:.2f}\n"
        "<i>Aucun signal émis. Capital preservation prioritaire.</i>"
    )
    await bot.send_message(chat_id=CHAT_ID, text=truncate_message(msg), parse_mode="HTML")

async def notify_fmp_unavailable():
    msg = (
        "⚠️ <b>Sniper FMP indisponible</b>\n"
        "<i>Aucune clé API valide ou erreur 5xx persistante après 2 retries.\n"
        "Scan arrêté — aucun signal émis.</i>"
    )
    await bot.send_message(chat_id=CHAT_ID, text=truncate_message(msg), parse_mode="HTML")
```

**Fix regime string check**: `if market_regime.get("status") == "Stress Majeur"` → `if market_regime == "prudence":`

### Lacune 10 — 4096 chars truncation

**File**: `scanner/notifier.py`

```python
def truncate_message(msg: str, max_chars: int = None) -> str:
    if max_chars is None:
        max_chars = CONFIG["scanner"].get("telegram_max_chars", 4096)
    if len(msg) <= max_chars:
        return msg
    suffix = "\n[message tronqué]"
    return msg[:max_chars - len(suffix)] + suffix
```

Apply to every `bot.send_message()` text argument.

### Lacune 13 — FMP indisponible : scan avorté, aucun fallback

**File**: `scanner/fetcher.py`

```python
class FMPUnavailableError(Exception):
    pass

# In fetch_fmp_data(): if key missing → raise FMPUnavailableError
# After FMP_MAX_RETRIES 5xx → raise FMPUnavailableError
# In fetch_ticker_info(): remove yfinance fallback when FMP source

# In fetch_all_data(): catch FMPUnavailableError → await notify_fmp_unavailable() → re-raise
```

**File**: `main.py` — wrap `fetch_all_data()` in try/except FMP sentinel → `return`

---

## Phase 5 — Storage

### Lacune 11 — `first_seen_date` conservation + colonnes retour

**File**: `scanner/storage.py`

**Schema migration** (SQLite try/except idiom):
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
        pass
```

**`first_seen_date` conservation**:
```python
def get_first_seen_date(conn, symbol: str) -> str | None:
    row = conn.execute(
        "SELECT first_seen_date FROM signals WHERE symbol = ? "
        "AND first_seen_date IS NOT NULL ORDER BY id DESC LIMIT 1",
        (symbol,)
    ).fetchone()
    return row[0] if row else None

# In save_signals(): first_seen = get_first_seen_date(conn, symbol) or today_str
```

**`update_signal_returns()` job** — called by APScheduler at 18h00 ET (secondary schedule):
```python
async def update_signal_returns():
    signals = db.query(
        "SELECT id, symbol, price_at_signal FROM signals "
        "WHERE price_30d_later IS NULL AND first_seen_date <= date('now', '-30 days')"
    )
    for s in signals:
        price = await asyncio.to_thread(fetch_current_price_yfinance, s.symbol)
        return_30d = (price - s.price_at_signal) / s.price_at_signal
        db.update(s.id, price_30d_later=price, return_30d=return_30d)
```

---

## Phase 6 — Tests

### Nouveaux tests unitaires (`tests/test_logic.py`)

| Test | Validation |
|---|---|
| `test_market_gate_panic_vix_over_35` | VIX=40, SPY above EMA200 → regime="panic" |
| `test_market_gate_panic_regardless_spy` | VIX=36, SPY below EMA200 → regime="panic" |
| `test_market_gate_prudence` | VIX=30, SPY < EMA200 → regime="prudence" |
| `test_market_gate_bear_light` | VIX=20, SPY < EMA200 → regime="bear_light" |
| `test_market_gate_normal` | VIX=15, SPY ≥ EMA200 → regime="normal" |
| `test_sector_none_exclusion` | sector=None → excluded, log "sector_missing" |
| `test_earnings_decay_expired` | surprise_date = today-91d → weight=0 (Freezegun) |
| `test_earnings_decay_partial` | surprise_date = today-45d → weight = base×0.5 (Freezegun) |
| `test_earnings_decay_fresh` | surprise_date = today-5d → weight = full base (Freezegun) |
| `test_intra_sector_fallback` | Sector with 2 tickers → cross-universe rank used |
| `test_truncate_message` | 5000-char string → len==4096, ends "[message tronqué]" |
| `test_first_seen_date_preserved` | AAPL day1→absent→day5 → first_seen_date = day1 |
| `test_totalcash_none_after_fix` | FMP response → totalCash=None, netDebt set correctly |

### Nouveaux tests d'intégration (`tests/test_integration_vcr.py`)

| Test | Validation |
|---|---|
| `test_fmp_budget_counter` | 30-ticker Sniper mock → total FMP HTTP calls ≤ 250 |
| `test_full_pipeline_panic_regime` | VIX=40 → scan exits after panic Telegram, 0 rows signals |
| `test_fmp_unavailable_abort` | FMP 503 ×2 → FMPUnavailableError → notify_fmp_unavailable(), 0 signals |

**Cassettes directory**: Create `tests/cassettes/.gitkeep` — without it, `@pytest.mark.vcr` makes live API calls.

---

## Sequencing and Dependencies

```
Phase 0 (4 Bugs)
    ↓
Phase 1 (Config) ────────────────────────────────────────┐
    ↓                                                     │
Phase 2 (Momentum)  Phase 3 (Quality)  Phase 4 (Notifier) Phase 5 (Storage)
    ↓                    ↓                   ↓                 ↓
                     Phase 6 (Tests — after all above)
```

Phases 2–5 can proceed in parallel after Phase 1. Phase 6 runs last.
