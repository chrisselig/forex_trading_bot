# COT Crash-Risk Filter on Carry

**Status:** implemented, live. Not a Monte Carlo–validated edge — this is a
defensive risk overlay, not a return driver. See [Design](#design) for why it
isn't backtested the same way the strategy MC reports are.

## Problem

Carry trades earn a small, steady interest differential every day they're
held, and periodically give several months of that income back in a single
violent move when the trade unwinds — the Aug 2024 JPY carry unwind is the
canonical example. The common thread across historical carry blowups isn't
the rate differential itself; it's *crowding*. When speculative money is
already leaning heavily one way, there's no one left to absorb the other
side of a shock, and the unwind becomes disorderly (stop cascades, forced
deleveraging) instead of an orderly repricing.

The CFTC's weekly Commitments of Traders (COT) report is the standard public
proxy for how crowded a currency future's speculative positioning is. This
filter uses it to block *new* carry entries that would add to an
already-crowded position — it does not touch existing positions.

## Data source

CFTC Traders in Financial Futures (TFF) — Futures Only report, published
weekly (Fridays, for the prior Tuesday's positions), available via the
CFTC's public Socrata API:

```
https://publicreporting.cftc.gov/resource/gpe5-46if.json
```

No API key required at this request volume (carry rebalances weekly and
queries at most a handful of currencies). Implementation:
`src/forex_bot/calendar/cot_client.py`.

We use the **leveraged funds** category (`lev_money_positions_long` /
`lev_money_positions_short`) — the TFF report's closest equivalent to the
legacy report's "non-commercial" speculators, and the standard proxy for
hot-money/leveraged positioning in crowding analysis.

### Currency coverage

Verified directly against the live dataset (2026-08-01) by contract code —
**not every carry-universe currency has a CME-listed future**:

| Currency | CFTC contract code | Covered? |
|---|---|---|
| JPY | 097741 | Yes |
| AUD | 232741 | Yes |
| ZAR | 122741 | Yes |
| MXN | 095741 | Yes |
| TRY | — | **No** |
| NZD | — | **No** |

TRY and NZD have no listed future in this report at all (too illiquid /
not CME-listed) — not a data gap, a structural absence. This matters
because **USDTRY, the largest single active carry pair, gets zero coverage
from this filter.** It fails open for USDTRY unconditionally; the filter
only ever gates USDZAR, USDMXN, AUDJPY, NZDJPY (on the JPY leg only), and
any future JPY/AUD/ZAR/MXN-legged pair.

## Methodology

For a currency with a listed future:

1. Pull the trailing `cot_lookback_weeks` (default 156 ≈ 3 years) of weekly
   reports for that contract, most recent first.
2. Compute net leveraged-fund position as a percentage of open interest for
   each week: `(long - short) / open_interest`. Normalizing by open interest
   (rather than using raw contract counts) keeps the metric comparable
   across regimes where total open interest has grown or shrunk.
3. Standardize the latest week's value against the trailing window's own
   mean and population stdev — a z-score. Positive = leveraged funds net
   long relative to their own history; negative = net short.
4. Require at least 52 usable weeks of history before trusting the z-score;
   fewer than that returns "no signal" rather than a noisy estimate.

## Directional logic

A pair's carry direction implies a long/short exposure on each leg. For
`AUDJPY` `BUY` (long AUD, short JPY):

- Check the **AUD** future: if leveraged funds are already crowded **long**
  (z ≥ threshold), adding a long-AUD carry position deepens that crowd →
  blocked.
- Check the **JPY** future: if leveraged funds are already crowded **short**
  (z ≤ −threshold) — the textbook JPY-carry-unwind setup — adding a
  short-JPY carry position deepens *that* crowd → blocked.

The rule is symmetric: it blocks whenever our exposure direction on a leg
matches an extreme in the same direction, regardless of whether that leg is
the "long" or "short" side of the pair. A leg with no CFTC-listed future
(or a failed/insufficient fetch) is skipped, not blocked.

Default threshold: `|z| >= 2.0` (roughly the 97.7th percentile of a normal
distribution — a real environment isn't normal, but 2.0 is a conventional,
conservative starting point for "this is stretched").

## Design

**Fails open on missing data, by choice.** If the CFTC API is unreachable,
a currency has no listed future, or there isn't enough history yet, the
filter treats that leg as "no signal" and lets the trade through. The
alternative — blocking whenever data is unavailable — would leave carry
dark for extended stretches during any CFTC reporting delay (the CFTC has
suspended COT publication during US government shutdowns before, including
in 2025) and would permanently block the TRY leg, which is structurally
uncovered. COT is a supplementary risk signal here, not a mandatory gate
like the stop-loss invariant.

**Blocks new entries only — does not close existing positions.** This
mirrors the existing `min_differential_pct` gate: both decide what
`CarryManager.rebalance()` is willing to *open*, not what it force-*closes*.
Auto-liquidating an existing position on a crowding signal is a materially
bigger behavior change (turns a risk filter into an exit strategy) and
wasn't asked for. If crowding readings prove predictive of subsequent carry
drawdowns in practice, revisit whether existing positions should also be
gated on the same signal — worth tracking in `docs/research/todo.md`.

**Not Monte Carlo–validated like the strategy reports.** The other numbered
docs in this directory backtest whether a *strategy* has positive expected
value. This is different: it's a filter that should, if it works, show up
as *fewer / smaller drawdown events*, not higher average P&L — it may even
slightly lower E[P&L] by skipping some trades that would have worked out.
Evaluating it properly needs enough historical carry drawdown events to see
whether COT crowding preceded them, which the 6.5-year Dukascopy dataset
used elsewhere doesn't cleanly support (COT history is available further
back, but our carry trade history is not). Recommended follow-up: track
`z_score` at every carry entry going forward (already logged) and revisit
after enough live/paper history accumulates to compare blocked-vs-not
outcomes.

## Configuration

`config/settings.yaml`, under `carry:`

```yaml
cot_crowding_enabled: true
cot_zscore_threshold: 2.0
cot_lookback_weeks: 156
```

## Where it runs

`CarryManager._filter_cot_crowding()`, called from `rebalance()` right after
`_calculate_scores()` and before positions are entered. Blocked entries are
logged and surfaced in the weekly Telegram rebalance summary under
*Blocked (COT crowding)*.
