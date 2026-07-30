# Spec 19 — Economic Surprise Index (ESI) Directional Strategy

**Status**: Pipeline #2. **Branch**: `feat/economic-surprise-index`.
**Deliverable report**: `docs/research/19-mc-esi.md`.

## Idea

Citi-ESI-style: aggregate standardized economic surprises (actual vs
forecast, normalized by each release's own historical surprise dispersion)
into a per-currency index that measures whether data is, on balance, beating
or missing expectations. A rising index ⇒ the economy is outperforming
expectations ⇒ its currency tends to strengthen over the following
days-to-weeks (documented FX predictability; e.g. Citi ESI literature).

**Why this is a different animal from the straddle (and why it's worth
testing despite reports 15-18):** this is a low-frequency DIRECTIONAL macro
tilt held days-to-weeks, not a spread-scalping bracket. A single round-trip
spread is amortized over a multi-tens-of-pips move, so the spread problem
that killed the ambient/event straddle (report 17/18) is minor here. The
edge, if any, is macro momentum, not volatility harvesting.

## Data (already on disk — no scraping unless gaps)

- **US surprises**: `scripts/data/ff_history.csv` (report 15; integrity-checked,
  2020-2026, ~9 US release types with forecast/actual/previous).
- **Prices**: daily bars in `scripts/data/dukascopy/*_daily.csv`. If a traded
  pair's daily history is missing/short, fetch with the FIXED tz-aware
  fetcher (`download_dukascopy.py` — never pass naive datetimes).
- **v1 scope is a US-ONLY ESI** tested against USD pairs. This is a deliberate
  simplification: US data dominates USD-cross direction, and we only have rich
  US forecast/actual. State plainly in the report that a v2 relative index
  (US ESI minus the foreign leg's ESI) is the natural extension and needs
  foreign forecast/actual we don't yet have.

## Signal construction

1. **Standardized surprise per release**: `z = (actual − forecast) / σ`,
   where σ is the trailing std of `(actual − forecast)` over PRIOR releases of
   that same series (expanding window, min 8 priors, NO look-ahead). Use
   native units, not percent (percent distorts rate levels — the FOMC problem
   from report 15). Reuse report 15's K/M/B/% parsing.
2. **Index**: at each date t, `ESI(t) = Σ decay^(t − t_i) · z_i` over all US
   releases i on/before t, EWMA half-life a grid parameter
   {10, 20, 40 trading days} (Citi uses ~1 month). Sign: positive = US data
   beating expectations = USD-bullish.
3. **Signals to test** (report all): (a) LEVEL — long USD when ESI>0; (b)
   MOMENTUM — long USD when ESI rising (ESI(t) > ESI(t−k)); (c) threshold
   band to cut churn.

## Strategy & backtest

- **Pairs**: liquid majors where US data dominates and spreads are tight:
  EURUSD, GBPUSD, USDJPY, USDCAD, AUDUSD. (These aren't currently traded —
  ESI would define its own universe. Note capacity is not a constraint at
  this account size.)
- **Rebalance**: weekly (e.g. Monday close→next Monday). Position per pair =
  sign(signal) applied to USD (long USD ⇒ short EURUSD/GBPUSD/AUDUSD, long
  USDJPY/USDCAD), equal-weight or ESI-proportional (test both). Hold to next
  rebalance.
- **Cost (net from the start — non-negotiable per reports 17/18)**: deduct one
  round-trip major-pair spread per rebalance turn. Base 1.5 pips, stress 3.0
  pips. Only turns that flip sign pay the spread (no-change = no cost).
- **Controls (prove the signal has content, per report 16 Run D discipline)**:
  compare ESI strategy vs (a) buy-and-hold USD basket, (b) RANDOM-sign control
  (same turn frequency, shuffled signs, bootstrapped) — the ESI must beat the
  random control, or it's just capturing a USD trend, not surprise content.
- **Diversification check**: correlation of ESI weekly returns with the carry
  book's returns — it must be low to justify adding it.

## Validation & pass bar

Walk-forward train 2020-2024, test 2025-2026; 10,000× bootstrap for CIs;
report E[return]/turn and /year, Sharpe, max drawdown, hit rate, turns/year.
**Pass bar**: net-of-cost annualized return CI > 0 at base spread AND
walk-forward OOS positive AND beats the random-sign control (non-overlapping
CIs) AND weekly-return correlation with carry < 0.3. Report per-pair and
pooled. If it fails, say so plainly — a clean negative is a good outcome.

## Report

`docs/research/19-mc-esi.md`, structured like the prior MC reports: data +
method, signal-variant comparison table, per-pair/pooled net results,
walk-forward, random-control comparison, carry correlation, explicit
**Production recommendation** (build as a paper-trade strategy / don't /
needs foreign ESI data first). Add it to the mkdocs Analysis nav (CI now
enforces this — `scripts/check_docs_nav.py`).

## Constraints

- FOREGROUND execution only — no background processes, no watchers (five
  prior pipeline stalls came from this). Bounded chunks, explicit timeouts,
  verify output, loop.
- `~/anaconda3/envs/forex-bot/bin/python` only; repo style; ruff-clean
  (ruff pinned 0.15.17). No commits/pushes. No `src/` or `config/` changes.
  Do not touch the running bot or TWS.
