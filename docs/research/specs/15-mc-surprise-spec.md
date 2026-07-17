# Spec 15 — MC Validation of the Post-News Surprise Strategy

**Status**: Phase 2 (backtest + validation). **Branch**: `feat/mc-surprise-validation`.
**Deliverable report**: `docs/research/15-mc-surprise.md` (13=momentum, 14=value are taken).

## Objective

`src/forex_bot/strategy/surprise.py` trades the direction of a data surprise
after a release (market entry, TP/SL bracket) but has never been validated.
Determine whether it has an edge; recommend keep-with-params / fix / delete.

## Phase 2a — Historical forecast/actual acquisition

**Script**: `scripts/download_ff_history.py`

- Target events (US, 2020-01-01 → 2026-06-30), titles/aliases per
  `config/events.yaml`: NFP, CPI (m/m headline + core if available), FOMC
  rate decision, PPI, Advance GDP, Core PCE, Unemployment Claims, ISM
  Manufacturing PMI, Retail Sales.
- Primary source: Forex Factory historical calendar (HTML week pages,
  `forexfactory.com/calendar?week=...`). The live JSON feed
  (nfs.faireconomy.media) is current-week only — do NOT use it for history.
  Respect a >=2s request delay (see `scraper.py` throttling pattern).
  FF timestamps are Eastern — convert with `zoneinfo.ZoneInfo("America/New_York")`
  exactly as `parser.py` does.
- Fallback if FF blocks scraping: Investing.com economic calendar history.
  Document whichever source is used in the report.
- Output: `scripts/data/ff_history.csv` with columns
  `title,country,scheduled_utc,forecast,actual,previous` (raw strings as
  published, e.g. "200K", "3.4%").
- **Data integrity (NON-NEGOTIABLE)**: spot-check >=5 events against known
  published values (e.g. NFP 2020-06-05 actual +2,509K vs forecast ~-8,000K;
  CPI releases 2022; FOMC 2022-2023 hikes) and >=95% coverage of the event
  dates already listed in `scripts/monte_carlo_dukascopy.py`. If either
  check fails, STOP and report — do not proceed to 2b on bad data.
- Cache aggressively (resume-safe): write partial CSV as you go; skip
  already-fetched weeks on re-run.

## Phase 2b — Backtest + Monte Carlo

**Script**: `scripts/mc_surprise.py` (pattern on `scripts/monte_carlo_dukascopy.py`
for bar loading, bootstrap, walk-forward, and report structure).

- Bars: existing `scripts/data/dukascopy/{PAIR}_1min.csv`.
- Pairs: USDZAR, USDTRY, AUDUSD, USDJPY (tradeable set) + GBPUSD, EURUSD,
  USDCAD (information only — flagged disabled pairs stay disabled).
- Surprise definition (primary): replicate `EconomicEvent.surprise_pct`
  EXACTLY (percent deviation from forecast, K/M/B/% parsing), including the
  unemployment-indicator sign inversion in `surprise.py`
  (`unemployment|jobless|claims` in title → invert). We are validating the
  module as built.
- Surprise definition (secondary): z-score vs trailing surprise history per
  event type (standardized surprise), same trade logic. Report both; the
  z-score variant informs a possible fix, not the primary verdict.
- Entry: at the open of the 1-min bar N minutes after release,
  N ∈ {1, 2, 5}, in surprise direction, only when |surprise| >= threshold.
  Threshold grid: {0, 5, 10, 20, 50}% for primary; {0.5, 1.0, 1.5}σ for
  z-score variant. Note production config: threshold 10%, entry ~5s.
- Exit: TP/SL grid — TP ∈ {15, 25, 40, 70} pips, SL ∈ {10, 15, 25} pips,
  time-stop at {30, 60} min (exit at bar close) if neither hit. Production
  is TP 25 / SL 15. Intra-bar TP-vs-SL ambiguity: resolve pessimistically
  (SL first), same as the straddle MC.
- Costs: same per-pair spread model as prior MC reports; sweep spread
  multiplier 1.0-4.0x to test robustness (exotics: event-time spreads are
  routinely 25-60 pips).
- Monte Carlo: bootstrap event outcomes 10,000x → E[P&L] in pips, 95% CI,
  Sharpe. Walk-forward: train 2020-2024, test 2025-2026.
- **Pass criteria** (same bar as prior reports): at optimal params, 95% CI
  excludes zero AND walk-forward OOS P&L positive AND result survives
  spread >= 2x. Report per pair and per event type.

## Report

`docs/research/15-mc-surprise.md`, structured like `12-mc-remaining-us.md`:
methodology, data source + integrity checks, per-pair/per-event tables,
walk-forward, spread sensitivity, explicit verdict per pair, and a
"Production recommendation" section (keep/fix/delete `surprise.py`; if
keep — exact params; if delete — say so plainly).

## Constraints

- Do NOT modify `src/forex_bot/` or `config/settings.yaml` in Phase 2.
- `from __future__ import annotations`, type hints, loguru — repo style.
- Use `~/anaconda3/envs/forex-bot/bin/python` for all runs.
- All timestamps stored UTC; FF input is ET.
