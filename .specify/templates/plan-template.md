# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]

**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: [e.g., Python 3.11, Swift 5.9, Rust 1.75 or NEEDS CLARIFICATION]

**Primary Dependencies**: [e.g., FastAPI, UIKit, LLVM or NEEDS CLARIFICATION]

**Storage**: [if applicable, e.g., PostgreSQL, CoreData, files or N/A]

**Testing**: [e.g., pytest, XCTest, cargo test or NEEDS CLARIFICATION]

**Target Platform**: [e.g., Linux server, iOS 15+, WASM or NEEDS CLARIFICATION]

**Project Type**: [e.g., library/cli/web-service/mobile-app/compiler/desktop-app or NEEDS CLARIFICATION]

**Performance Goals**: [domain-specific, e.g., 1000 req/s, 10k lines/sec, 60 fps or NEEDS CLARIFICATION]

**Constraints**: [domain-specific, e.g., <200ms p95, <100MB memory, offline-capable or NEEDS CLARIFICATION]

**Scale/Scope**: [domain-specific, e.g., 10k users, 1M LOC, 50 screens or NEEDS CLARIFICATION]

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [ ] **I. Funnel Architecture**: Chalutier/Sniper separation respected? FMP-only for fundamentals? No yfinance fallback for balance sheet data? ETF pipeline momentum-only (not value — sector rotation framing)?
- [ ] **II. Quality & Stability**: ROE composite formula (0.6 × ROE_3y + 0.4 × ROIC_TTM) used? ROE gate on raw roe_3y (not composite)? book_value_per_share gates (≤ 0 → exclude; ROE > 150% + BVS < $5 → cap percentile 80)? Utilities/Financials/REITs excluded from debt/EBITDA? Data freshness flags (365d warn, 450d exclude — config.yaml)?
- [ ] **III. Market Gate**: 4-level priority cascade intact (Panic VIX > 35 → Caution → Bear Light → Normal)? VIX evaluated before EMA200?
- [ ] **IV. Institutional Liquidity**: Cap > $2B, Dollar Vol > $5M (20d avg), Price > $5, NYSE/NASDAQ/AMEX only?
- [ ] **V. Quantitative Momentum**: 5 sub-criteria (6M perf with volatility-adjusted rank Daniel & Moskowitz 2016, 6M sector outperformance, 3M perf, Earnings Surprise with 90d linear decay, Analyst revision 3M)? Anti-extreme penalties (+25% / -20% on 1M)?
- [ ] **VI. Sector GICS Integrity**: sector=None → excluded (sector_missing log)? Sectors < 3 tickers → cross-universe fallback? MIN_UNIVERSE_SIZE=100 checked on the full post-eligibility universe (not the 30-ticker shortlist)?
- [ ] **VII. Signal Persistence**: first_seen_date never reset on reappearance? Top 10 exit by score only (not by calendar rotation)? Portfolio exit rules respected (exit_rank_threshold=15, exit_score_threshold=70)? Maturation cycle (ACHAT → MATURATION 3j → HOLD)?
- [ ] **Technical Standards**: SQLite WAL, APScheduler 4.x async, jitter 0.8–1.5s, FMP 2 retries max, html.escape(), 4096-char truncation?
- [ ] **Quality Gates**: VCR.py cassettes for all network tests? Freezegun for all time-sensitive logic?
- [ ] **IX. No Abbreviations**: Variable and function names fully descriptive? No cryptic abbreviations (sq, mv, tmp, val, res)? Standard financial acronyms (ROE, VIX, EMA, FMP, OHLCV) still permitted.
- [ ] **X. Trader Validation**: Any modification to scoring weights, exclusion gates, or sectoral exceptions has a documented trader validation in `.agents/roles/trader.md`?
- [ ] **XI. Anti-Regression**: yfinance price-only separation respected? shortlist_size=30 unchanged? Weights modified only via config.yaml? Feature branch (not main)?

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
# [REMOVE IF UNUSED] Option 1: Single project (DEFAULT)
src/
├── models/
├── services/
├── cli/
└── lib/

tests/
├── contract/
├── integration/
└── unit/

# [REMOVE IF UNUSED] Option 2: Web application (when "frontend" + "backend" detected)
backend/
├── src/
│   ├── models/
│   ├── services/
│   └── api/
└── tests/

frontend/
├── src/
│   ├── components/
│   ├── pages/
│   └── services/
└── tests/

# [REMOVE IF UNUSED] Option 3: Mobile + API (when "iOS/Android" detected)
api/
└── [same as backend above]

ios/ or android/
└── [platform-specific structure: feature modules, UI flows, platform tests]
```

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
