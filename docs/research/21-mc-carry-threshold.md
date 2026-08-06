# Monte Carlo — Carry Strategy Differential Threshold

**Analysis date:** 2026-08-05
**Strategy:** `src/forex_bot/strategy/carry.py` — `min_differential_pct` entry gate
**Data:** Dukascopy daily close (price) + FRED OECD policy-rate series (differential,
lagged 60d to avoid look-ahead)
**Walk-forward:** train < 2025-01, test >= 2025-01 (out-of-sample)
**Threshold grid:** 0.5%, 1.0%, 1.5%, 2.0%, 2.5%, 3.0%, 3.5%, 4.0%

## Why this exists

`min_differential_pct: 2.0` has never been backtested. It was set as a launch
default when the carry strategy was first built and never revisited with data —
unlike the straddle strategy, whose every parameter traces back to an MC/walk-
forward report in this directory. This closes that gap and, along the way,
answers two live questions: whether USDMXN should be pushed into the basket
despite sitting below 2.0% today, and whether the current 5-pair basket is
actually diversified.

## Per-pair: is 2.0% actually the right threshold?

| Pair | IS-optimal threshold | IS Sharpe | OOS Sharpe @optimal | OOS ann. @optimal | OOS Sharpe @2.0% | OOS ann. @2.0% | MC 5th %ile¹ | P(losing OOS)¹ | Verdict (judged @2.0%, the deployed gate) |
|------|----------------------|-----------|----------------------|--------------------|--------------------|-----------------|-------------|----------------|---------|
| USDZAR | 0.5% | -0.15 | +0.98 | +10.7% | +0.98 | +10.7% | -6.7% | 13% | **PASS** |
| USDTRY | 4.0% | -0.47 | +2.55 | +9.6% | +2.34 | +8.9% | +6.0% | 1% | **PASS** (strongest pair) |
| USDMXN | 3.5% | 0.19 | +0.01 | +0.1% | +1.41 | +10.7% | -9.4% | 49% | **PASS when open** (not currently open — see below) |
| AUDJPY | 3.5% | 0.40 | -0.04 | -0.3% | +1.15 | +12.4% | -17.4% | 53% | **PASS but redundant** (see diversification below) |
| NZDJPY | 2.5% | 0.31 | +0.18 | +1.4% | +0.36 | +3.0% | -13.7% | 43% | **WEAK** (weakest of the six at the deployed gate) |
| GBPJPY *(candidate)* | 2.5% | 0.80 | +1.44 | +9.7% | +1.44 | +9.7% | +0.6% | 4% | **PASS** (best risk-adjusted candidate) |

¹ MC 5th %ile / P(losing OOS) are computed at each pair's own **IS-optimal**
threshold column, not at 2.0% — for USDMXN and AUDJPY those thresholds differ
from 2.0% and (per the finding below) shouldn't be trusted, so treat those two
MC figures as not representative of the pair's actual 2.0%-gate performance.
USDZAR and GBPJPY's optimal happens to equal or nearly equal 2.0%, so their MC
figures are directly usable.

**The "IS-optimal" column is mostly noise, not signal.** USDZAR and USDTRY have
*negative* in-sample Sharpe even at their best grid point (-0.15, -0.47) — there
is no real in-sample edge to select a threshold against for these two, so the
grid search is picking the least-bad noise, not finding a parameter. USDMXN's
best is barely positive (0.19). Even where in-sample Sharpe looked more
respectable — AUDJPY at 0.40 — the selected threshold (3.5%) still **failed to
transfer OOS** (Sharpe collapses to -0.04, P(losing) 53%), while the same pair
at the **current, un-optimized 2.0%** performs well OOS (Sharpe +1.15). Same
story for USDMXN: "optimal" 3.5% gives OOS Sharpe ≈0 (P(losing) 49%) vs. +1.41
at 2.0%. **The honest reading: grid-searching this threshold against in-sample
Sharpe does not reliably produce a threshold that holds up out-of-sample for
this basket** — only GBPJPY (IS Sharpe 0.80, the strongest of the six) shows a
threshold pick (2.5%) that both looks real in-sample and transfers OOS, and even
there it lands close to 2.0% anyway.

Net effect: **2.0% survives this test better than a naive optimizer would**,
precisely because the naive optimizer has nothing reliable to grab onto for most
of this basket. That's a point in favor of leaving it as a conservative
round-number gate rather than "optimizing" it further on this same data — doing
so would mostly be fitting noise.

## Diversification: is the current basket actually 5 independent bets?

Weekly OOS (2025-2026) return correlation across the live basket, each pair run
at its own carry direction (so this is the correlation of realized carry P&L,
not raw FX returns):

| |USDZAR|USDTRY|USDMXN|AUDJPY|NZDJPY|
|---|---|---|---|---|---|
| **USDZAR** |+1.00|+0.11|+0.54|+0.47|+0.41|
| **USDTRY** |+0.11|+1.00|+0.31|-0.00|-0.05|
| **USDMXN** |+0.54|+0.31|+1.00|+0.37|+0.47|
| **AUDJPY** |+0.47|-0.00|+0.37|+1.00|+0.83|
| **NZDJPY** |+0.41|-0.05|+0.47|+0.83|+1.00|


- **USD-quoted group** (USDZAR/USDTRY/USDMXN) average pairwise correlation: **+0.32** —
  driven almost entirely by USDZAR-USDMXN (+0.54); USDTRY barely correlates
  with either (+0.11, +0.31). USDTRY's lira-crisis dynamics are idiosyncratic
  enough to actually diversify the book — it's the two majors-adjacent EM
  legs, ZAR and MXN, that move together.
- **JPY-funded group** (AUDJPY/NZDJPY) average pairwise correlation: **+0.83** —
  this is not diversification, this is **the same bet held twice**. AUD and NZD
  are both high-beta commodity/Antipodean currencies funded off the same JPY
  leg; a correlation this high means the "5-pair basket" is functionally a
  4-bet book with one bet double-weighted.
- **Cross-group** (EM-vs-Antipodean, e.g. USDZAR-AUDJPY +0.47, USDZAR-NZDJPY
  +0.41, USDMXN-AUDJPY +0.37): moderate positive correlation even across
  supposedly unrelated legs — consistent with a shared global risk-sentiment
  factor (carry unwinds during risk-off hit high-yield EM and high-beta G10
  simultaneously). USDTRY is the one pair that stays largely uncorrelated with
  everything, cross-group included.

The concern raised — that sharing a funding currency isn't real diversification —
is confirmed, but the strongest version of it is **AUDJPY/NZDJPY (+0.83), not**
**the USD-quoted trio.** The USD-quoted group is correlated too (+0.32 average),
but that's really "USDZAR and USDMXN move together" (+0.54) plus "USDTRY mostly
doesn't move with anything" (+0.11 to +0.31) — TRY's own crisis dynamics
dominate over the shared-USD component at weekly granularity. AUD and NZD have
no equivalent idiosyncratic anchor pulling them apart — same funding currency,
same "risk-on commodity bloc" macro driver, so they move almost as one position.
There's also a broader risk-sentiment factor tying the EM legs to the Antipodean
legs (+0.37 to +0.47 cross-group) that a naive "5 different pairs" view misses
entirely — carry unwinds hit the whole basket at once in a risk-off shock, not
one pair at a time.

## USDMXN specifically

USDMXN is currently **not open** live — its FRED differential sits at ~1.56% as
of the last live pull (2026-08-05), below the 2.0% gate. Per the finding above,
its walk-forward "optimal" threshold (3.5%) is **not trustworthy** — it's fit to
weak in-sample noise (IS Sharpe 0.19) and collapses OOS (Sharpe ≈0). The more
credible number is OOS performance **at the current 2.0% gate**: Sharpe +1.41,
+10.7%/yr annualized, when the differential does clear it. That's a real
historical edge — it just isn't clearing the bar *today* because Banxico has
been cutting. Nothing here argues for lowering the threshold to force USDMXN in
now; it argues for leaving the gate where it is and letting USDMXN re-enter
naturally if/when the differential widens back past 2.0%.

## Candidate: GBPJPY

Flagged separately (`docs/research/todo.md`, live differential ~2.89% as of
2026-08-05) as the one non-exotic pair currently clearing the gate. See its row
above for walk-forward verdict before adding it to `carry.instruments` — per
CLAUDE.md's Analysis-Driven Configuration rule, it should not be added without
this kind of validation, and the user should confirm explicitly even if it passes.

## Caveats

- Swap accrual is modeled as `|differential| / 365` per day held — an
  approximation of the true broker roll/swap point, which also embeds a
  broker-specific spread on top of the raw rate differential. Real accrued
  interest (tracked live via `InterestJournal` / IB Flex reports) may differ.
- FRED policy rates are lagged 60 days to avoid look-ahead, but IB's
  actual swap points reprice continuously off overnight funding markets, not
  monthly OECD releases — this is a proxy, not a live-accurate cost.
- Stop-loss is checked once per day (EOD close), not intrabar — live execution
  with `place_order_with_stop` reacts faster (or slower, on gaps) than this.
- Single train/test split, same limitation noted in the other MC reports here.
- Costs modeled on turnover only; exotic (ZAR/TRY/MXN) slippage at weekly
  rebalance is uncertain, same caveat as `13-mc-momentum.md`.
- Re-run with `/trade-review` once enough live carry paper data accumulates to
  cross-check the swap-accrual approximation against real `InterestJournal` data.
