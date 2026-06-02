<!--
SYNC IMPACT REPORT — 2026-06-02
Version change: 1.1.3 → 1.2.0 (MINOR: ROE yfinance fallback + sector cap at shortlist level)

Root cause: FMP free tier returns [] for income-statement and balance-sheet-statement → roe_3y = None → 100% quality exclusions daily. Bot producing zero stock signals.

Modified principles:
- I. Funnel Architecture → Added yfinance IS/BS fallback exception for roe_3y. FMP still primary. Added shortlist_sector_cap constant (default 5). Updated FMP strict separation rule to distinguish "FMP unavailable (5xx/missing key)" from "FMP plan gap ([] response)".
- II. Quality & Stability → ROE source amended: primary FMP IS/BS; fallback yfinance financials/balance_sheet (annual, pretty=False) when FMP returns []. TTM-only (yf.info returnOnEquity) still explicitly forbidden.
- VIII. Simplicity First → Added. No overengineering, no redundancies unless justified.
- Technical Standards → Added shortlist_sector_cap to constants table.

Templates requiring update:
- ✅ .specify/memory/constitution.md (this file)
- ✅ specs/spec.md — FR-003, FR-004, §16 contrainte 1, §2.2 point 4, §17 table
- ⏳ specs/plan.md — Phase 4 (Sniper), Phase 8 (Shortlist), Constants table
- ⏳ specs/tasks.md — new tasks for fallback + sector cap

Previous amendment (v1.1.3 — 2026-06-02):
- VIII. Simplicity First added (no overengineering, no redundancies)

Previous amendment (v1.1.2 — 2026-05-22):
- I. Funnel Architecture → FMP budget updated (BF-010)
- V. Quantitative Momentum → earnings-surprises/analyst-estimates documented as free tier degraded mode

Follow-up TODOs:
- Backtest framework (v1.1 roadmap): out-of-sample signal validation over 6M horizon
- Si upgrade plan FMP disponible : réactiver earnings-surprises + analyst-estimates + supprimer fallback yfinance, revenir à Principe I strict
-->

# ValueMomentum Scanner Constitution

<!-- High-fidelity quantitative scanning for Quality, Valuation, and Momentum -->

## Core Principles

### I. Funnel Architecture & FMP/yfinance Strict Separation

The scanner MUST operate as a two-stage funnel to balance scale and precision.

- **Stage 1 (Chalutier)**: Broad technical screening (~700 tickers) using `yfinance` exclusively for price action, volume, and momentum (OHLCV). `yfinance` MUST NOT be used for ratio data or any fundamental metric other than the `roe_3y` fallback defined below.
- **Stage 1b (Shortlist Sector Cap)**: After momentum ranking, before Stage 2, apply `SHORTLIST_SECTOR_CAP` (default 5) tickers max per sector. Prevents systematic sector concentration (semis sweeping all 30 slots). Sector read from `fundamentals` cache (populated by build_eligible_universe). Implementation: `filters.py::cap_sector_shortlist()`.
- **Stage 2 (Sniper)**: Deep fundamental analysis on a shortlist of exactly **SHORTLIST_SIZE = 30 tickers** using FMP official API. This value is non-negotiable: 30 × 5 FMP endpoints = 150 calls nominal + 25 retry margin = **175 hard limit** against a 250 calls/day quota (BF-010). Exceeding 30 tickers requires a budget audit first.
- **FMP Unavailability** (missing key or persistent 5xx after 2 retries): Send Telegram alert `⚠️ Sniper FMP indisponible` and stop the scan. No fallback — a signal without any FMP data is worse than no signal.
- **FMP Plan Gap** (IS/BS endpoints return `[]` on free tier): NOT an unavailability event. Fallback to yfinance `get_income_stmt(pretty=False)` + `get_balance_sheet(pretty=False)` (annual) is authorized **exclusively for `roe_3y` calculation**. All other FMP-sourced metrics (P/E, EV/EBITDA, ROIC, FCF, margins) remain `None` and are handled by existing scoring engine fallback logic. This distinction is critical: circuit-breaker (5xx) and plan-gap (empty `[]` response) are different failure modes.
- The `roe_3y` yfinance fallback is a documented exception — NOT a precedent for other metrics.
- **ETF Pipeline**: ETFs use a **momentum-only** scoring pipeline (Perf 6M 50% + Surperf vs SPY 50%). ETFs have no P/E, ROE, or balance sheet data — framing ETF signals as "undervalued" is incorrect. The correct framing is **sector rotation momentum** (identifying sectors with accelerating price leadership). Leveraged/inverse ETFs MUST be excluded by name pattern before scoring.

### II. Quality & Stability (The Moat)

Investment signals MUST be rooted in structural quality.

- A 3-year average Return on Equity (ROE > 0) is the primary quality gate. ROE < 0 = unconditional exclusion. ROE MUST be computed from 3 annual IS/BS periods. **Source priority**: (1) FMP `income-statement` + `balance-sheet-statement`; (2) yfinance `get_income_stmt(pretty=False)` + `get_balance_sheet(pretty=False)` when FMP returns `[]` (plan gap). `yf.info["returnOnEquity"]` (TTM) is **never** permitted as a source. If `roe_3y` remains `None` after both sources fail, the ticker MUST be excluded.
- **book_value_per_share gates**: `book_value_per_share ≤ 0` → ticker excluded from Quality scoring (ROE is mathematically undefined). `ROE > 150%` with `book_value_per_share < $5` → ROE percentile score capped at 80 + flag `⚠️ ROE possiblement gonflé par buybacks` (buyback-inflated leverage, not operational excellence).
- **Debt/EBITDA exclusion sectors**: Financials (deposits ≠ normal debt), Real Estate (FFO ≠ GAAP EBITDA), and **Utilities** (structurally high leverage from regulated infrastructure — 5-7x normal and non-predictive of risk) MUST NOT have debt/EBITDA included in Quality scoring. The Quality pillar for these sectors uses 3 sub-criteria: ROE, operating margin, FCF yield.
- EBITDA ≤ 0 → unconditional exclusion (debt/EBITDA ratio meaningless; business loss-making). Net debt/EBITDA > 6x → unconditional exclusion (excessive balance sheet risk).
- Fundamental data MUST be verified for freshness: data older than 120 days triggers a warning flag `⚠️ données potentiellement périmées`; data older than 180 days results in automatic exclusion from the final ranking.
- Tickers with `sector = None` (GICS missing) are excluded from the Actions scoring pipeline — no intra-sector comparison is possible without a valid sector label.

### III. Market Gate (Survival Priority — Priority Cascade)

Capital preservation is the absolute priority. The Market Gate MUST evaluate conditions in strict priority order (first match wins):

1. **Panique** (Priority 1): `VIX > 35` — regardless of SPY position. Scan MUST be cancelled. Telegram alert sent. One entry written to `scans` table with `regime='panic'`. No entries written to `signals`.
2. **Prudence** (Priority 2): `SPY < EMA200 AND VIX between 25 and 35`. Scan runs. Every signal flagged `⚠️ RÉGIME DE PRUDENCE`.
3. **Bear Light** (Priority 3): `SPY < EMA200 AND VIX ≤ 25`. Scan runs normally. Internal log warning only — no flag on Telegram signals.
4. **Normal** (Priority 4): `SPY ≥ EMA200 AND VIX ≤ 25`. Full scan, unrestricted signal emission.

The VIX takes precedence over EMA200 because VIX is a leading indicator of panic; EMA200 lags by weeks. A crash in progress (VIX > 35) MUST trigger Panique even if SPY has not yet crossed below EMA200.

### IV. Institutional Liquidity & Execution

To ensure tradeability and minimize slippage, the scanner MUST only consider institutional-grade instruments.

- Minimum thresholds (enforced daily before scoring): Market Cap > $2B, Average Daily Dollar Volume (20-day) > $5M, Price > $5, Listed on NYSE/NASDAQ/AMEX only.
- The universe is strictly US-only in v1.0. Non-US tickers (e.g., `.NS` suffixes) MUST NOT be included in `tickers_universe.json`.
- Penny stocks, OTC instruments, and low-liquidity micro-caps are excluded unconditionally.

### V. Quantitative Momentum (The Catalyst — 5 Sub-Criteria)

Strategy focuses on the convergence of price momentum and fundamental acceleration:

- **Primary signals** (price): 6-month performance (30%) and 6-month sector outperformance vs SPDR benchmark (30%).
- **Confirmatory signal** (price): 3-month performance (15%).
- **Fundamental acceleration — backward** (FMP): Earnings Surprise % via `earnings-surprises` (15% nominal weight, with temporal decay: weight → 0 linearly over 90 days post-earnings; freed weight redistributed proportionally to the 4 remaining criteria). **Degraded mode — FMP free tier**: `earnings-surprises` returns HTTP 404; criterion scores 0 for all tickers (symmetric — relative ranking preserved). Weight 15% effectively redistributed to remaining 3 price criteria at runtime.
- **Fundamental acceleration — forward** (FMP): Analyst estimate revisions 3M via `analyst-estimates` (10% nominal weight, no decay — revisions reflect sustained conviction). **Degraded mode — FMP free tier**: `analyst-estimates` returns HTTP 402; criterion scores 0 for all tickers (symmetric — relative ranking preserved). Weight 10% effectively redistributed to remaining criteria at runtime.
- Short-term extremes MUST be penalized: 1-month performance > +25% → -10 pts on momentum score; 1-month < -20% → -5 pts.

### VI. Sector GICS Integrity

The intra-sector percentile ranking is the foundation of fair valuation comparison (P/E, EV/EBITDA, operating margin).

- Source of truth for sector label: yfinance `.info["sector"]`. FMP sector labels are secondary and may diverge.
- If `sector = None`: ticker excluded from Actions scoring (logged as `sector_missing`).
- If a sector has **fewer than 3 tickers** in the scored shortlist: those tickers MUST use cross-universe ranking for all intra-sector metrics. A 1-2 ticker intra-sector percentile is statistically meaningless (single ticker always scores 100th percentile).
- **MIN_UNIVERSE_SIZE = 100 tickers** check MUST be applied to the **full eligible universe after Chalutier eligibility filters** (before shortlisting to 30). The shortlist is always ≤ 30 by design — checking MIN_UNIVERSE_SIZE on the shortlist will always fail. If the post-eligibility universe (pre-shortlist) falls below 100, percentile ranking loses statistical validity and the scan MUST be cancelled.

### VII. Signal Persistence (Conviction over Calendar)

The scoring model — not time — decides when a signal expires.

- `first_seen_date` in SQLite is NEVER reset when a ticker reappears in the Top 10 after an absence. It records the original signal date for historical traceability.
- Tickers present 90+ consecutive days in the Top 10 represent a conviction signal, not a rotation failure. No forced exclusion by calendar.
- A ticker exits the Top 10 only when its `score_global` falls below the 10th threshold in the ranked universe. The `first_seen_date` field is informational — it contextualizes the decision for the human trader, it does not drive mechanical action.

### VIII. Simplicity First (NON-NÉGOCIABLE)

Tout code ajouté doit avoir un besoin prouvé. Pas de spéculation sur des besoins futurs.

- **Pas d'overengineering** : aucune abstraction, helper, ou pattern architectural sans cas d'usage immédiat démontré.
- **Pas de redondances** sauf si explicitement requises : résilience prouvée (ex: retry circuit-breaker déjà en place), ou séparation de responsabilités qui impose une duplication minimale documentée.
- **YAGNI** (You Ain't Gonna Need It) : supprimer le code inutilisé plutôt que le commenter ou le garder "au cas où".
- Trois lignes similaires sont meilleures qu'une abstraction prématurée. Une abstraction ne se justifie que lorsque la quatrième occurrence identique apparaît, ou qu'un couplage fort le nécessite.
- Toute complexité ajoutée doit être justifiée dans le commit message ou l'amendment de constitution.

## Technical Standards

### Core Constraints

- **SQLite WAL**: Mandatory for concurrent bot writing and dashboard reading.
- **Asynchronous Core**: Native `asyncio` (APScheduler 4.x async) for all I/O, scheduling, and notifications. No synchronous blocking in the event loop.
- **API Resilience**: Jittered delay (0.8s–1.5s) between all external fetches. FMP: 2 retries max (circuit-breaker pattern). yfinance: 3 retries with exponential backoff.
- **Telegram**: HTML parse_mode. All string data MUST be html.escape()'d before send. Messages MUST be truncated to 4096 chars maximum (Telegram API limit). Rate limit: 1.5s between messages.

### Configurable Constants (config.yaml — source of truth)

| Constant                 | Default | Constraint                                      |
| ------------------------ | ------- | ----------------------------------------------- |
| `SHORTLIST_SIZE`         | 30      | Hard max 30 (FMP budget)                        |
| `SHORTLIST_SECTOR_CAP`   | 5       | Range [3, 10] — max tickers/sector in shortlist |
| `VIX_PANIC_THRESHOLD`    | 35      | Range [30, 45]                                  |
| `VIX_WARNING_THRESHOLD`  | 25      | Range [20, 30]                                  |
| `MAX_TICKERS_PER_SECTOR` | 3       | 10 = alpha-pure mode (risk) — scoring filter    |
| `MAX_WORKERS_UNIVERSE`   | 4       | Hard max 6 (yfinance ban risk)                  |
| `FMP_MAX_RETRIES`        | 2       | Hard max 2 (budget 175 hard limit)              |
| `MIN_UNIVERSE_SIZE`      | 100     | Below = scan cancelled                          |
| `TELEGRAM_MAX_CHARS`     | 4096    | Fixed (API limit)                               |

> **[2026-05-22 BF-010]** `FMP_CALL_BUDGET_HARD_LIMIT` = 175 (30 × 5 endpoints = 150 nominal + 25 retry margin). `earnings-surprises` et `analyst-estimates` supprimés du plan gratuit FMP — endpoints retirés du Sniper. Principe V fonctionne en mode dégradé symétrique (voir détail Principe V ci-dessus).

## Validation & Quality Gates

- **Hermetic Integration Tests**: All integration tests MUST use `VCR.py` cassettes. First-run cassette recording requires explicit opt-in. Tests MUST NOT make live API calls by default.
- **Temporal Determinism**: `Freezegun` is mandatory for all time-sensitive logic (NYSE calendar, earnings windows, data freshness, earnings surprise decay).
- **Fail-Safe Data Parsing**: All external data MUST pass None-safe validation before entering the scoring engine. `data.get("key")` with value check, never `"key" in data` alone.
- **FMP Budget Monitoring**: Test suite MUST include a mock call counter verifying that a full 30-ticker Sniper run stays within 175 FMP calls (30 × 5 endpoints = 150 nominal + 25 retry margin — BF-010).

## Governance

The ValueMomentum Scanner Constitution is the sovereign source of truth for architectural and strategic decisions.

- **Conflict Resolution**: Any implementation that violates the Funnel Architecture (Principle I), Market Gate priority cascade (Principle III), or FMP/yfinance separation (Principle I) is a critical failure requiring immediate rollback.
- **Amendments**: Changes to core weights, thresholds, or the FMP budget calculation MUST be documented with financial rationale, version bump, and the amendment date added to the Constants table.
- **Spec Alignment**: `specs/Spec_ValueMomentum_Scanner.md` is the authoritative implementation reference. Constitution principles always supersede spec details when they conflict. Spec updates that introduce contradictions with this Constitution MUST trigger a Constitution amendment.

**Version**: 1.2.0 | **Ratified**: 2026-05-18 | **Last Amended**: 2026-06-02
