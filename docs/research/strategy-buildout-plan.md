# Strategy Buildout Plan — Research Candidates

**Created**: 2026-07-17. Governs the build-and-test pipeline for the six
strategy candidates in [todo.md](todo.md).

## Ground rule

**No strategy is enabled without passing MC walk-forward validation**
(per CLAUDE.md Analysis-Driven Configuration). Each candidate runs a
validation gate BEFORE any live-trading code is written. A candidate that
fails the gate gets its research report merged and its todo item closed as
resolved-negative — no module is built.

## Model assignments

| Role | Model |
|---|---|
| Backtest scripts & strategy modules | Sonnet 4.5 (cheap, well-specified implementation) |
| Unit tests | Haiku 4.5 (cheapest; mechanical against a written spec) |
| Specs, validation verdicts, code review | Fable (judgment: MC interpretation, risk invariants) |

## Per-strategy pipeline (each on its own branch)

1. **Spec (Fable)** — implementation spec in `docs/research/specs/`:
   data sources, entry/exit logic, parameter grid, walk-forward split
   (train 2020-2024, test 2025-2026), pass/fail criteria matching the
   existing MC reports.
2. **Backtest + MC validation (Sonnet)** — analysis script patterned on
   `scripts/monte_carlo_dukascopy.py`, run it, draft research report.
   **Gate: Fable reviews the numbers and issues the verdict.**
   Fail → merge report only, close branch.
3. **Strategy module (Sonnet, only if Pass)** — under
   `src/forex_bot/strategy/`, wired through the mandatory
   `Signal -> RiskManager -> CircuitBreaker -> ExecutionEngine` path,
   config in `settings.yaml`, **disabled by default**.
4. **Tests (Haiku)** — unit tests with mocked IB, edge cases from the spec.
5. **Review (Fable)** — full diff review against the spec: risk invariants
   (mandatory SL, no pipeline bypass), timezone handling, async
   correctness, margin-cap interaction. Then the standard validation loop
   (ruff + pytest) and PR.

## Approval protocol

PRs are the approval surface (reviewable from GitHub mobile). Research
scripts, reports, tests, and disabled-by-default modules may be merged by
the pipeline once the Fable review passes. **Anything that enables a
strategy or changes live risk/config parameters requires explicit user
confirmation** — parked in the PR with a comment until approved.

## Execution order

| # | Branch | Scope | Status |
|---|---|---|---|
| 1 | `feat/mc-surprise-validation` | Validate existing `surprise.py` (spec: [15-mc-surprise-spec.md](specs/15-mc-surprise-spec.md)) | **FAIL — report 15 merged; remove surprise.py** |
| 1.5 | `fix/dukascopy-timezone` | **URGENT (found during #1)**: `download_dukascopy.py` naive-datetime bug shifted all event windows ~+6h — re-download + re-validate MC reports 04-12 | in progress |
| 2 | `feat/economic-surprise-index` | ESI construction + weekly tilt backtest | pending |
| 3 | `feat/fix-flow-strategy` | Month-end/London-fix drift backtest | pending |
| 4 | `feat/commodity-tot-signal` | Commodity momentum → AUD/CAD/ZAR tilt | pending |
| 5 | `feat/cot-carry-filter` | COT extremes as carry-book crash filter | pending |
| 6 | `docs/vrp-research-memo` | Research memo only (no build) | pending |

Sequential, not parallel: each strategy is one branch → one PR before the
next starts. The review gate serializes anyway, later strategies reuse
earlier scaffolding (ESI reuses the surprise-history data), and spend is
capped — the pipeline can stop after any PR.

## Known data constraints (discovered 2026-07-17)

- The live events DB has forecast+actual for only 18 events (Jun-Jul 2026).
  Strategies 1-2 require ~6 years of historical forecast/actual values —
  acquired via the Forex Factory historical calendar (primary) with
  Investing.com as fallback; per the Data Integrity rule, scraped values
  must be spot-checked against published releases before use.
- The faireconomy JSON feed used by the live scraper serves the current
  week only — historical acquisition is a separate script.
