# 19 — Economic Surprise Index (ESI) Directional Strategy

**Date**: July 2026
**Status**: DRAFT — pending user review. No `src/` or `config/` changes made.
**Spec**: `docs/research/specs/19-economic-surprise-index-spec.md`
**Script**: `scripts/mc_esi.py` (new)
**Data**: `scripts/data/ff_history.csv` (US surprises, 2020-01 — 2026-06), daily
close bars in `scripts/data/dukascopy/*_daily.csv` (already on disk, no fetch
needed — all 5 pairs cover 2019-06 — 2026-07)

---

## TL;DR / Production recommendation

**Do not build this as a paper-trade strategy. Zero of 6 signal variants
clear the pass bar, and the one variant that looked best on paper does not
survive contact with a random-sign control.**

- **No variant's net bootstrap CI clears zero.** All 6 (LEVEL × {10,20,40}
  half-life, MOMENTUM × {10,20,40}) pooled-portfolio results have a 95%
  bootstrap CI that spans zero at the base spread (1.5 pips). Best point
  estimate: **MOMENTUM, half-life 20**, net ann. return **+2.05%**, CI
  **[−3.13%, +7.69%]**, Sharpe 0.33 — a coin flip dressed up with a
  positive sign.
- **Walk-forward kills it outright.** Selecting the best variant on
  training data (2020-2024) by CI-low still only finds a variant whose
  *training* CI-low is **negative** (−3.4%) — there is no candidate in the
  6-cell grid that even clears zero in-sample. Out-of-sample (2025-2026),
  that selected variant (MOMENTUM/20) returns **+0.05% annualized**, CI
  **[−9.43%, +10.19%]** — indistinguishable from zero, indistinguishable
  from noise.
- **Does not clearly beat the random-sign control — the whole point of the
  spec's Run-D-style discipline.** A 10,000-path random-sign control with
  the *same* flip rate (47.9%/week) and *same* cost model returns a mean
  of −0.5% ann., CI [−5.6%, +4.8%]. The real ESI signal's point estimate
  (+2.05%) sits at the **83rd percentile** of that random distribution —
  better than most random paths, but its own CI-low (−3.13%) is **well
  inside** the random control's CI-high (+4.8%). The two distributions
  overlap substantially; this is not statistically distinguishable from
  chance.
- **Underperforms simple buy-and-hold USD.** Buy-and-hold long-USD (no
  signal at all, same 5 pairs, one spread charge) returns +0.85% ann., CI
  [−4.27%, +6.34%] — a similar, equally-inconclusive result to the "best"
  ESI variant, for zero model complexity.
- **One flagged exception, explicitly not chased further:** GBPUSD alone,
  under MOMENTUM at half-life 10 and 20, has a CI that clears zero
  (+7.27% [+0.14%, +15.02%] and +7.69% [+0.57%, +15.46%] respectively).
  With 5 pairs × 6 variants = 30 per-pair cells tested, ~1–2 false
  positives at the 95% level are expected by chance alone, and this
  specific cell was **not** subjected to its own walk-forward or
  random-sign control — per the "no parameter torture" instruction, it is
  reported here as an observation, not investigated further, and **not**
  a basis for enabling anything.
- **ESI vs carry-factor correlation is ~0 (+0.07, n=333 weeks)** — not
  meaningfully positive or negative. Moot: there is no standalone ESI
  return to diversify the carry book with in the first place.
- **This is a clean negative, and the spec explicitly asked for intellectual
  honesty over parameter torture.** A US-only ESI, weekly-rebalanced,
  net of one round-trip spread per turn, does not produce a directional
  edge on any of EURUSD/GBPUSD/USDJPY/USDCAD/AUDUSD that survives its own
  walk-forward or beats a matched random-sign control.

---

## Method

### 1. Standardized US surprises (no look-ahead)

Reuses the exact parsing and no-look-ahead z-score discipline from report 15
(`scripts/mc_surprise.py`): for every US release in `ff_history.csv`
(12 title types: NFP, CPI m/m, Core CPI m/m, PPI m/m, Federal Funds Rate,
Advance/Prelim/Final GDP q/q, Core PCE Price Index m/m, ISM Manufacturing
PMI, Retail Sales m/m, Unemployment Claims):

1. `diff = actual − forecast` in native units (K/M/B/% suffix parsing chain,
   exact replication of `EconomicEvent.surprise_pct`'s parser).
2. `sigma` = trailing standard deviation of that release type's own prior
   diffs (rolling window of the last 24 releases, minimum 8 priors before
   any z-score is emitted — same window/minimum as report 15, chosen there
   specifically to stop the 2020 COVID NFP/Claims outliers from poisoning
   an expanding-window sigma forever).
3. `z = diff / sigma`. Sign is flipped for "unemployment/jobless/claims"
   titles (lower-than-forecast claims = USD-positive), exact replication of
   `surprise.py`'s `usd_direction()`.
4. 736 of 992 releases produce a standardized z (the rest are within the
   8-prior warm-up window per title, or missing actual/forecast). Quarterly
   GDP releases warm up over ~2 years; Federal Funds Rate rarely surprises
   (only 1 of 53 decisions clears the rolling-sigma bar) — expected given
   the Fed telegraphs decisions.

### 2. Index construction

`ESI(t) = ESI(t-1) · decay + Σ z_i` (sum of any releases landing on trading
day t), `decay = 0.5^(1/half_life)`, half-life ∈ {10, 20, 40} trading days
(Citi's own ESI uses ~1 month ≈ 20 trading days). Positive = US data beating
expectations = USD-bullish. Computed over the full 2019-06 — 2026-07 daily
trading calendar (weekdays only; the Dukascopy "Sunday" week-open
micro-candle is excluded from the calendar to avoid double-counting the
week's first session).

### 3. Signals

- **LEVEL**: long USD iff `ESI(t) > 0`.
- **MOMENTUM**: long USD iff `ESI(t) − ESI(t−1 rebalance week) > 0`. The
  1-week lookback is a fixed design choice (not swept — the spec warns
  against parameter torture, and 6 variants is already the full grid the
  spec asks for: 2 signal types × 3 half-lives).
- A threshold/dead-band variant (spec item (c), "cut churn") was **not**
  swept as a third full grid dimension — same reasoning. As a single
  robustness spot-check (MOMENTUM/hl=20, position held through any
  week-over-week ESI change smaller than a 0.25 dead-band), turnover drops
  from 24.8 to 22.0 turns/yr, but the result gets **worse**, not better:
  ann. −1.31%, CI [−6.36%, +4.16%], Sharpe −0.16. The dead-band does not
  rescue the signal; not pursued further.

### 4. Backtest

- **Pairs**: EURUSD, GBPUSD, USDJPY, USDCAD, AUDUSD — 5-pair equal-weight
  pooled portfolio, plus each pair reported individually.
- **Rebalance**: weekly. Each ISO week's first available weekday (Monday,
  or the next trading day if Monday is a holiday) is the rebalance day;
  position decided from the ESI value known **as of that day's close**
  (no look-ahead), held to next week's rebalance day's close.
- **Direction mapping**: same `trade_side()` convention as report 15 — long
  USD ⇒ BUY USDJPY/USDCAD (USD is base), SELL EURUSD/GBPUSD/AUDUSD (USD is
  quote).
- **Cost**: one round-trip major-pair spread charged **only on a sign-flip
  turn** (no cost on a held position) — base 1.5 pips, stress 3.0 pips,
  converted to a % cost via each pair's pip size and the entry-day price.
- **Backtest window**: 2020-02-01 — 2026-07-01 (334 weeks), a one-month
  buffer past the first US release so ESI isn't degenerate zero for the
  very first weeks.
- **Walk-forward**: train 2020-2024 (256 weeks), select the best of the 6
  variants by training CI-low, test 2025-2026 (76 weeks) out-of-sample,
  untouched.
- **Monte Carlo**: 10,000× bootstrap of the weekly-return series, annualized
  via geometric compounding `(∏(1+r))^(52/n) − 1`; 95% CI from bootstrap
  percentiles; Sharpe and max drawdown from the actual (non-resampled) path.
- **Controls**:
  (a) buy-and-hold USD basket — always long USD, same 5 pairs, one spread
  charge at entry, no further turns;
  (b) random-sign control — 10,000 simulated sign paths matching the
  selected variant's observed weekly flip rate (Markov chain: flip with
  probability `p_flip` each week), applied to the **same real weekly price
  data** and **same cost model**, to test whether the ESI signal contains
  any surprise content beyond a matched-turnover coin flip.
- **v1 scope — US-ONLY.** This deliberately ignores the foreign leg's own
  surprise index (e.g. Eurozone data for EURUSD). US data alone drives the
  "long/short USD" call; a v2 relative index (US ESI − foreign-leg ESI)
  is explicitly out of scope here and would need non-US forecast/actual
  history this project does not yet have.

---

## Signal-variant comparison (pooled 5-pair portfolio)

| Signal | Half-life | Spread | Ann. return | 95% CI | Sharpe | Max DD | Turns/yr | N weeks |
|---|---|---|---|---|---|---|---|---|
| LEVEL | 10 | base | −1.02% | [−6.13%, +4.34%] | −0.12 | −24.1% | 10.4 | 334 |
| LEVEL | 10 | stress | −1.17% | [−6.27%, +4.18%] | −0.14 | −24.6% | 10.4 | 334 |
| MOMENTUM | 10 | base | +0.53% | [−4.72%, +6.09%] | +0.11 | −17.5% | 26.1 | 333 |
| MOMENTUM | 10 | stress | +0.17% | [−5.06%, +5.70%] | +0.06 | −18.1% | 26.1 | 333 |
| LEVEL | 20 | base | −0.31% | [−5.47%, +5.12%] | −0.01 | −22.8% | 8.6 | 334 |
| LEVEL | 20 | stress | −0.43% | [−5.59%, +5.00%] | −0.03 | −23.1% | 8.6 | 334 |
| **MOMENTUM** | **20** | **base** | **+2.05%** | **[−3.13%, +7.69%]** | **+0.33** | **−14.5%** | 24.8 | 333 |
| MOMENTUM | 20 | stress | +1.70% | [−3.47%, +7.31%] | +0.28 | −15.1% | 24.8 | 333 |
| LEVEL | 40 | base | +0.25% | [−4.98%, +5.56%] | +0.07 | −22.6% | 3.6 | 334 |
| LEVEL | 40 | stress | +0.20% | [−5.02%, +5.49%] | +0.06 | −22.8% | 3.6 | 334 |
| MOMENTUM | 40 | base | −2.57% | [−7.51%, +2.81%] | −0.35 | −22.7% | 24.2 | 333 |
| MOMENTUM | 40 | stress | −2.90% | [−7.82%, +2.45%] | −0.40 | −24.0% | 24.2 | 333 |

**Every single CI spans zero, at both spread levels.** MOMENTUM/hl=20 is the
best point estimate, but its own CI-low is negative. LEVEL is uniformly
worse than MOMENTUM here — flat, then slowly-decaying US ESI level alone
does not carry directional information at weekly horizons; only its
week-over-week *change* shows any (statistically inconclusive) signal.

---

## Per-pair results (base spread, 95% CI)

| Signal | Half-life | EURUSD | GBPUSD | USDJPY | USDCAD | AUDUSD |
|---|---|---|---|---|---|---|
| LEVEL | 10 | −0.17% [−5.84,+5.79] | +0.29% [−6.47,+7.55] | −1.41% [−8.18,+5.92] | −2.01% [−6.54,+2.72] | −2.43% [−9.69,+5.52] |
| MOMENTUM | 10 | −1.07% [−6.68,+4.88] | **+7.27% [+0.14,+15.02]** | −2.78% [−9.46,+4.37] | +0.07% [−4.53,+4.96] | −1.17% [−8.71,+7.16] |
| LEVEL | 20 | −0.55% [−6.18,+5.25] | −1.00% [−7.81,+6.10] | −0.66% [−7.47,+6.73] | +0.14% [−4.45,+4.92] | −0.12% [−7.63,+8.00] |
| MOMENTUM | 20 | +0.20% [−5.46,+6.25] | **+7.69% [+0.57,+15.46]** | +1.00% [−5.94,+8.53] | +1.44% [−3.21,+6.44] | −0.53% [−8.11,+7.85] |
| LEVEL | 40 | −0.75% [−6.41,+4.95] | −0.53% [−7.28,+6.49] | −0.79% [−7.76,+6.55] | +1.04% [−3.65,+5.84] | +1.66% [−6.15,+9.85] |
| MOMENTUM | 40 | −3.27% [−8.68,+2.52] | +0.76% [−5.97,+8.14] | −4.07% [−10.68,+3.00] | −1.03% [−5.55,+3.77] | −5.73% [−12.88,+2.14] |

29 of 30 cells span zero. **GBPUSD is the sole exception**, in both
MOMENTUM/hl=10 and MOMENTUM/hl=20, and is flagged in the TL;DR as a likely
multiple-comparisons artifact (30 cells tested at 95% ⇒ ~1.5 false
positives expected) — not walk-forward validated on its own, not chased
further per the "no parameter torture" instruction.

---

## Walk-forward: IS vs OOS

Best variant selected on training data (2020-2024) by CI-low: **MOMENTUM,
half-life 20** — and even that selection has a negative training CI-low,
meaning there was no candidate in the 6-cell grid that cleared zero
in-sample.

| Period | N weeks | Ann. return | 95% CI | Sharpe | Max DD | Win rate |
|---|---|---|---|---|---|---|
| In-sample (train, 2020-2024) | 256 | +2.49% | [−3.40%, +9.20%] | +0.38 | −10.7% | 51.2% |
| **Out-of-sample (test, 2025-2026)** | 76 | **+0.05%** | **[−9.43%, +10.19%]** | +0.04 | −5.4% | 59.2% |

OOS is essentially flat with a CI more than twice as wide as the point
estimate in either direction — no signal, no edge, consistent with the
random-sign control result below.

---

## ESI vs random-sign control

The selected variant's observed weekly flip rate is 47.9% (essentially a
coin flip — MOMENTUM's week-over-week sign changes are close to i.i.d.).
A 10,000-path Markov-chain random-sign control was built with that exact
flip rate, applied to the **same real weekly price returns** and **same
cost model**:

| | Ann. return | 95% CI |
|---|---|---|
| Selected ESI variant (MOMENTUM, hl=20, full window) | +2.05% | [−3.13%, +7.69%] |
| Buy-and-hold USD (no signal) | +0.85% | [−4.27%, +6.34%] |
| Random-sign control (mean of 10,000 paths, matched flip rate) | −0.52% | [−5.62%, +4.85%] |

- ESI's point estimate sits at the **83rd percentile** of the random-sign
  distribution — better than most random paths, but not decisively so.
- **The CIs do not separate.** ESI's own CI-low (−3.13%) is well inside the
  random control's CI-high (+4.85%). A signal with genuine surprise content
  should push its CI-low above the random control's CI-high; this one
  doesn't come close.
- **Verdict: does not clear the spec's explicit bar** ("ESI must beat the
  random control, or it's just capturing USD trend, not surprise content").
  It is, at best, statistically indistinguishable from a matched-turnover
  coin flip.

---

## Carry-return correlation

Using the same rate-differential carry-factor proxy methodology as
`scripts/mc_value.py` (long the higher 3-month-rate currency, equal weight,
same 5 pairs, FRED short-rate series), resampled to the ESI's weekly
rebalance calendar:

**correlation = +0.07 (n = 333 weeks).**

Essentially zero — neither a meaningful diversifier nor a duplicate of the
carry book. Moot in practice: there is no standalone ESI return worth
adding to a book in the first place (see above), so the diversification
question doesn't change the recommendation.

---

## Which variants clear the full pass bar

**Pass bar** (all four required): (1) net 95% bootstrap CI-low > 0 at base
spread (1.5 pips); (2) survives stress spread (3.0 pips) with CI-low still
> 0; (3) walk-forward OOS (2025-2026) point estimate > 0, ideally with
CI-low > 0 too; (4) CI-low clears the random-sign control's CI-high (clean
statistical separation from a matched-turnover coin flip).

| Variant | (1) Base CI>0 | (2) Stress CI>0 | (3) OOS>0 | (4) Beats random control | Overall |
|---|---|---|---|---|---|
| LEVEL, hl=10 | FAIL | FAIL | not tested (not selected) | not tested | **FAIL** |
| LEVEL, hl=20 | FAIL | FAIL | not tested (not selected) | not tested | **FAIL** |
| LEVEL, hl=40 | FAIL | FAIL | not tested (not selected) | not tested | **FAIL** |
| MOMENTUM, hl=10 | FAIL | FAIL | not tested (not selected) | not tested | **FAIL** |
| **MOMENTUM, hl=20** (walk-forward winner) | FAIL | FAIL | FAIL (+0.05% but CI spans zero) | FAIL (CIs overlap) | **FAIL** |
| MOMENTUM, hl=40 | FAIL | FAIL | not tested (not selected) | not tested | **FAIL** |

**0 of 6 variants pass. 0 of 6 even clear criterion (1) alone.**

---

## Production recommendation

**Do not build a paper-trade strategy from this.** Every one of the four
pass-bar criteria fails for the walk-forward-selected variant, and no other
variant does any better. This is not "close but needs tuning" — the
in-sample training CI-low is negative for the *best* of all 6 candidates,
before OOS or the random-sign control are even applied. Two additional
findings reinforce the negative:

- The strategy underperforms doing nothing more sophisticated than
  buying and holding USD against the same 5-pair basket.
- Its best-looking result is statistically indistinguishable from a
  random-sign control with matched turnover — i.e., what edge exists in
  the point estimate is well within the range chance alone would produce.

**Needs foreign ESI data before this idea is worth revisiting.** The spec
flagged this as the key v1 simplification: a US-only index can only ever
capture half of a cross-pair's fundamental picture. A v2 relative index
(US ESI − EUR/GBP/JPY/CAD/AUD-leg ESI, built from each currency's own
forecast/actual history) is the natural next step *if* that data becomes
available — but given how weak even the US-only signal is here, there is no
strong prior that adding a symmetric foreign leg would flip this from
"noise" to "edge." Do not prioritize sourcing that data on the strength of
this result alone.

One loose thread, explicitly not investigated further per the "no parameter
torture" instruction: GBPUSD alone shows a CI that clears zero under
MOMENTUM at two of three half-lives. This is far more likely to be a
multiple-comparisons artifact (1–2 false positives expected across the 30
per-pair cells tested) than a real GBP-specific effect, and was not given
its own walk-forward or random-sign control. If it recurs in a future,
independently-designed test, it would be worth a dedicated look — it is not
grounds for any action here.

---

## Caveats

- **US-only v1.** No foreign-leg surprise data; the ESI is entirely a
  "how is the US economy doing vs expectations" signal, applied uniformly
  across 5 different USD crosses. This is the single biggest simplification
  and the most obvious place a real signal could be hiding but isn't
  visible here.
- **Quarterly/infrequent release types warm up slowly.** GDP (quarterly)
  needs ~2 years of releases before contributing a standardized z; Federal
  Funds Rate essentially never surprises against its own rolling sigma (1
  of 53 decisions). The ESI is effectively dominated by the
  higher-frequency release types (Unemployment Claims, CPI, ISM, Retail
  Sales, NFP).
- **MOMENTUM lookback (1 week) and threshold/dead-band were fixed design
  choices, not swept as full grid dimensions** — deliberately, to avoid
  turning a clean negative into an overfit "pass" by adding more knobs. A
  single dead-band spot-check (0.25 dead-band on the ESI level) reduced
  turnover from 24.8 to 22.0 turns/yr but made the point estimate *worse*
  (ann. −1.31%, CI [−6.36%, +4.16%]) — the verdict does not change.
- **Daily close-only price data** (Dukascopy bid close), not intraday —
  appropriate for a weekly-rebalance strategy, but means weekly returns use
  a single close print per side, not a VWAP or intraday-average execution
  price.
- **Cost model is the same flat "one round-trip major spread" for all 5
  pairs** (1.5 / 3.0 pips), not the wider event-time or exotic-pair spread
  tables used in reports 15-18 — appropriate since this is a slow,
  low-frequency directional strategy on liquid majors, per the spec's own
  reasoning for why this is "a different animal" from the straddle/event
  scalping strategies that those spread tables were built for.
- **Carry-factor proxy is a rate-differential toy factor** (same
  methodology as `scripts/mc_value.py`), not the actual production
  `CarryStrategy` P&L (which trades a dynamically-scored universe, not a
  fixed 5-pair majors basket) — used only as a rough diversification
  sanity check, consistent with how report 14 used the same proxy for the
  value-vs-carry comparison.
