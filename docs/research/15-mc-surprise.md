# Monte Carlo Validation — Post-News Surprise Strategy

**Date**: July 2026
**Scripts**: `scripts/download_ff_history.py` (data), `scripts/mc_surprise.py` (backtest)
**Data sources**: Forex Factory historical calendar (via Hugging Face mirror + Wayback Machine archives); Dukascopy Bank SA 1-minute OHLCV (bid), freshly fetched
**Grid**: 360 parameter combinations per cell (threshold × entry delay × TP × SL × time-stop), 2 surprise definitions
**Bootstrap**: 10,000 resamples, 95% CI
**Walk-forward**: Train 2020-2024, Test 2025-2026

## Verdict up front

**The surprise strategy has no edge. Every one of the 36 (event type × pair ×
surprise definition) cells FAILS the pass criteria** (95% CI excluding zero AND
positive walk-forward OOS AND survival at 2x spread). Most cells are not even
close: the majority lose double-digit pips per trade at baseline spreads, and
**not a single cell has positive out-of-sample P&L**. FOMC is untradeable by
this strategy outright — only 2 of 53 rate decisions in 6.5 years produced a
nonzero surprise.

**Production recommendation: remove `surprise.py` from production** (see final
section).

---

## What was tested

`src/forex_bot/strategy/surprise.py` trades in the direction of a data
surprise immediately after a release: market entry, TP/SL bracket, only when
|surprise| ≥ threshold (production: threshold 10%, TP 25 / SL 15, entry ~5 s
after actual arrives). It had never been validated. This analysis replicates
its logic exactly and sweeps the parameter space around it.

### Surprise definitions

1. **Primary** — exact replication of `EconomicEvent.surprise_pct`
   (`src/forex_bot/models/events.py`): `((actual − forecast) / |forecast|) × 100`
   on the raw published strings with the `K`→e3 / `M`→e6 / `B`→e9 / `%`-strip
   parsing chain, plus the production sign inversion for unemployment-type
   indicators (title containing "unemployment" / "jobless" / "claims" →
   direction flipped, from `surprise.py`). USD-positive surprise → BUY
   USD-base pairs (USDZAR, USDTRY), SELL AUDUSD — exactly as production.
2. **Z-score** — standardized surprise: (actual − forecast) in native units
   divided by the trailing σ of that difference over the last 24 releases of
   the same event type (min 8 priors, no look-ahead). Thresholds in σ units.
   (An expanding-window σ was rejected: COVID-2020 outliers — NFP misses of
   ±10,000K — poison σ forever and the variant never trades again.)

### Grid (per spec 15)

- Entry: open of the 1-min bar N minutes after release, N ∈ {1, 2, 5}
- Threshold: {0, 5, 10, 20, 50}% primary; {0.5, 1.0, 1.5}σ z-score
- Exit: TP ∈ {15, 25, 40, 70} × SL ∈ {10, 15, 25} pips; time-stop {30, 60} min
  (exit at bar close); intra-bar TP-vs-SL ambiguity resolved pessimistically
  (SL first)
- Costs: same per-pair event-time spread model as prior MC reports
  (USDZAR 25, USDTRY 30, AUDUSD 2.0 pips), charged as one full spread per
  round trip, swept at 1.0x / 1.5x / 2.0x / 3.0x / 4.0x
- Selection metric: bootstrap CI-low (pessimistic), as in prior reports
- Pairs per event type follow `config/events.yaml` (PCE: USDTRY+AUDUSD;
  Claims/ISM/Retail: USDTRY only; others: USDZAR+USDTRY+AUDUSD)

---

## Data source and integrity checks

### Forecast/actual history (`scripts/data/ff_history.csv`, 991 rows)

Forex Factory and Investing.com both return HTTP 403 (Cloudflare) to every
request from this environment, so neither of the spec's two named sources was
directly scrapable. Two Forex-Factory-derived sources were used instead
(documented per spec):

1. **Primary (2020-01-01 → 2025-04-03)**: the `Ehsanrs2/Forex_Factory_Calendar`
   dataset on Hugging Face — a third-party historical scrape of
   forexfactory.com with actual/forecast/previous columns. Timestamps carry an
   Asia/Tehran offset with midnight placeholders; only the calendar date is
   trusted, combined with each event's standard ET release time (8:30 ET for
   BLS/BEA/Census releases, 10:00 ET for ISM, 14:00 ET for FOMC), converted
   ET→UTC via `zoneinfo.ZoneInfo("America/New_York")` exactly as `parser.py`.
2. **Gap-fill (2025-04-04 → 2026-06-30)**: Wayback Machine archives of
   forexfactory.com — per-indicator "History" tables plus the JSON event
   payloads embedded in ~700 archived `/calendar` week/month/day pages
   (matched by stable `ebaseId`, timestamps from the Unix `dateline` field).
   All requests throttled ≥2 s, disk-cached, resume-safe.

### Spot-checks (all pass)

| Event | Date (UTC) | CSV actual | CSV forecast | Known published value |
|---|---|---|---|---|
| NFP | 2020-06-05 12:30 | +2509K | −7750K | May-2020 shocker: +2.509M vs ~−7.75M consensus ✓ |
| CPI m/m | 2022-11-10 13:30 | 0.4% | 0.6% | Oct-2022 downside miss ✓ |
| Federal Funds Rate | 2022-06-15 18:00 | 1.75% | 1.50% | 75 bp surprise hike ✓ |
| Unemployment Claims | 2020-03-26 12:30 | 3283K | 1648K | COVID claims explosion ✓ |
| Advance GDP q/q | 2020-07-30 12:30 | −32.9% | −34.5% | Q2-2020 advance print ✓ |
| Retail Sales m/m | 2020-05-15 12:30 | −16.4% | −12.0% | April-2020 record drop ✓ |
| Core PCE m/m | 2023-02-24 13:30 | 0.6% | 0.4% | Hot Jan-2023 PCE ✓ |
| ISM Mfg PMI | 2024-01-03 15:00 | 47.4 | 47.2 | Dec-2023 ISM ✓ |

Parsing checks: NFP 2020-06-05 `surprise_pct` = +132.4% (K-suffix and
negative-forecast `abs()` handling correct); Claims 2020-03-26 surprise +99.2%
→ inversion → USD-negative ✓ (production logic replicated).

ET→UTC conversion verified in both DST regimes (12:30 UTC summer, 13:30 UTC
winter for 8:30 ET releases; 18:00 UTC for 14:00 ET FOMC).

### Coverage vs. reference event lists

Strict = same calendar date present; ±3d = a release of that event type
within 3 days (see note below).

| Event type | Reference dates | Strict | ±3 days |
|---|---|---|---|
| NFP | 78 | 93.6% | 93.6% |
| CPI | 78 | 89.7% | 93.6% |
| FOMC | 52 | 94.2% | 96.2% |
| PPI | 76 | 93.4% | 96.1% |
| GDP (all vintages) | 76 | 85.5% | 85.5% |
| PCE | 73 | 98.6% | 98.6% |
| Unemployment Claims | 338 | 95.0% | 96.4% |
| ISM Mfg PMI | 78 | 91.0% | 100.0% |
| Retail Sales | 78 | 76.9% | 92.3% |
| **Total** | **927** | **91.9%** | **95.2%** |

The ±3d figure is the honest completeness measure, because a material share
of strict misses are **errors in the reference lists, not missing data**:

- The `monte_carlo_dukascopy.py` / `download_dukascopy.py` date lists (built
  from FRED release calendars) are wrong for every February PPI 2020-2024
  (e.g. list says 2020-02-14; BLS/FF released 2020-02-19), most January ISMs
  (list 2022-01-03 vs actual 2022-01-04), and **all Retail Sales from
  2024-08 onward** (list 2024-08-13 vs Census/FF 2024-08-15, and so on).
- The GDP reference list includes FRED annual-revision entries
  (2020-09-16, 2020-11-03, 2021-08-06, …) that are not FF-scheduled
  Advance/Prelim/Final releases — no forecast/actual exists for them anywhere.
- Most genuinely-missing rows sit in Oct–Dec 2025, when the 43-day US
  government shutdown suspended BLS/Census releases (several were canceled
  outright), plus a handful of thin Wayback coverage months in 2026.

**Integrity verdict: PASS** (spot-checks all correct; ±3d coverage 95.2% ≥ 95%).

### Bar data — and a critical bug found in the existing Dukascopy CSVs

The existing `scripts/data/dukascopy/*_1min.csv` files **could not be used**,
and this matters well beyond this report:

> **The stored event windows do not contain the news releases.**
> `download_dukascopy.py` passes timezone-naive UTC datetimes to
> `dukascopy_python.fetch()`, which interprets them as local
> (America/Edmonton) time. Every stored "event window" therefore actually
> covers ≈ [release+4h → release+8.5h] (+4h during DST, +5h in winter).
> Verified directly: the 2023-02-03 NFP burst (1,573-pip 1-min range bar at
> 13:30 UTC, confirmed by a fresh tz-aware fetch) is absent from the stored
> window (18:30–22:00 UTC). The stored windows are real UTC bars — of the
> wrong hours.

This backtest therefore fetched its own 1-min windows
([release−10 min, release+130 min], explicitly tz-aware UTC) for all 1,478
event/pair combinations, cached under `scripts/data/_cache/mc_surprise_bars/`.
Zero windows came back empty; every simulated event has real bars around the
actual release. **Follow-up strongly recommended**: prior straddle MC reports
(04, 05, 06, 08, 09, 10, 11, 12) were computed on the shifted windows and
need re-validation on corrected data — that is outside this report's scope.

---

## Results summary

Best cell per (event type × pair × definition), full sample, baseline spread.
"% grid +" = share of all 360/216 grid cells with positive mean P&L (an
overfitting smell when the "best" cell sits nearly alone).

| Event | Pair | Def | Best params (thr/N/TP/SL/ts) | E[P&L] | 95% CI | Sharpe | WR | N | % grid + | WF OOS | 2x spread | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NFP | USDZAR | primary | 5/1/70/10/30 | −16.6 | [−24.2, −9.1] | −4.36 | 23% | 74 | 0.0% | −16.2 | −41.6 | FAIL |
| NFP | USDZAR | z | 0.5/2/15/10/30 | −31.7 | [−35.0, −28.5] | −10.0 | 0% | 23 | 0.0% | −31.0 | −56.7 | FAIL |
| NFP | USDTRY | primary | 50/2/70/25/30 | −13.5 | [−27.8, +1.6] | −1.83 | 34% | 29 | 0.0% | −27.7 | −43.5 | FAIL |
| NFP | USDTRY | z | 1.0/2/70/25/30 | −5.9 | [−29.7, +18.3] | −0.56 | 40% | 10 | 0.0% | −36.5 | −35.9 | FAIL |
| NFP | AUDUSD | primary | 20/1/15/25/30 | +1.4 | [−2.7, +5.2] | +0.77 | 59% | 51 | 12.8% | −4.5 | −0.6 | FAIL |
| NFP | AUDUSD | z | 1.0/2/15/25/30 | +6.8 | [−2.2, +13.0] | +3.12 | 80% | 10 | 61.1% | −5.1 | +4.8 | FAIL |
| CPI | USDZAR | primary | 50/2/70/10/30 | −7.0 | [−23.0, +9.0] | −0.90 | 35% | 20 | 0.0% | −35.0 | −32.0 | FAIL |
| CPI | USDZAR | z | 1.5/2/70/10/30 | −0.7 | [−23.6, +33.6] | −0.22 | 43% | 7 | 0.0% | −35.0 | −25.7 | FAIL |
| CPI | USDTRY | primary | 20/2/70/25/60 | −10.1 | [−23.4, +3.5] | −1.45 | 44% | 41 | 0.0% | −25.5 | −40.1 | FAIL |
| CPI | USDTRY | z | 0.5/2/70/25/60 | −7.8 | [−21.2, +5.6] | −1.15 | 47% | 43 | 0.0% | −25.5 | −37.8 | FAIL |
| CPI | AUDUSD | primary | 20/1/15/10/30 | +2.5 | [−1.0, +6.1] | +1.47 | 59% | 41 | 22.2% | −6.0 | +0.5 | FAIL |
| CPI | AUDUSD | z | 0.5/1/15/10/30 | +2.2 | [−1.3, +5.8] | +1.29 | 58% | 43 | 15.7% | −10.2 | +0.2 | FAIL |
| FOMC | all 3 | both | — | — | — | — | — | — | — | — | — | NO TRADES |
| PPI | USDZAR | primary | 0/5/70/10/30 | −20.7 | [−27.8, −13.5] | −5.72 | 18% | 67 | 0.0% | −19.0 | −45.7 | FAIL |
| PPI | USDZAR | z | 0.5/2/70/10/30 | −21.7 | [−29.3, −12.1] | −5.00 | 17% | 42 | 0.0% | −16.5 | −46.7 | FAIL |
| PPI | USDTRY | primary | 50/2/70/25/60 | −15.9 | [−26.8, −4.9] | −2.86 | 35% | 52 | 0.0% | −24.9 | −45.9 | FAIL |
| PPI | USDTRY | z | 1.0/2/70/25/30 | −11.9 | [−25.2, +2.3] | −1.84 | 29% | 21 | 0.0% | −27.1 | −41.9 | FAIL |
| PPI | AUDUSD | primary | 50/5/15/25/60 | −1.6 | [−5.1, +1.7] | −0.89 | 48% | 52 | 0.0% | −5.4 | −3.6 | FAIL |
| PPI | AUDUSD | z | 1.5/5/15/25/60 | +5.4 | [−0.7, +10.6] | +2.26 | 67% | 9 | 10.6% | −3.1 | +3.4 | FAIL |
| GDP | USDZAR | primary | 10/1/70/10/30 | −9.3 | [−23.6, +5.0] | −1.41 | 32% | 28 | 0.0% | −25.0 | −34.3 | FAIL |
| GDP | USDZAR | z | 0.5/1/70/10/30 | −16.8 | [−27.7, −2.3] | −2.61 | 23% | 22 | 0.0% | −27.9 | −41.8 | FAIL |
| GDP | USDTRY | primary | 50/1/25/15/30 | −15.2 | [−26.2, −5.0] | −3.24 | 0% | 6 | 0.0% | −33.2 | −45.2 | FAIL |
| GDP | USDTRY | z | 1.5/1/15/25/60 | −24.1 | [−34.1, −16.7] | −5.74 | 0% | 8 | 0.0% | −36.3 | −54.1 | FAIL |
| GDP | AUDUSD | primary | 0/2/70/10/60 | −1.0 | [−4.3, +2.6] | −0.66 | 39% | 61 | 0.0% | −2.0 | −3.0 | FAIL |
| GDP | AUDUSD | z | 0.5/1/15/25/30 | −3.0 | [−7.3, +1.3] | −1.41 | 36% | 22 | 0.0% | −0.8 | −5.0 | FAIL |
| PCE | USDTRY | primary | 0/5/70/25/30 | −12.0 | [−26.8, +3.1] | −1.60 | 39% | 31 | 0.0% | −32.2 | −42.0 | FAIL |
| PCE | USDTRY | z | 0.5/2/70/25/30 | −9.4 | [−24.9, +7.0] | −1.17 | 41% | 27 | 0.0% | −29.2 | −39.4 | FAIL |
| PCE | AUDUSD | primary | 50/5/40/10/60 | +3.0 | [−4.7, +11.4] | +0.66 | 50% | 12 | 3.9% | −0.6 | +1.0 | FAIL |
| PCE | AUDUSD | z | 0.5/2/15/25/60 | +0.3 | [−4.7, +4.9] | +0.19 | 56% | 27 | 6.9% | −5.4 | −1.7 | FAIL |
| Claims | USDTRY | primary | 5/2/70/15/60 | −23.0 | [−29.2, −16.6] | −7.19 | 25% | 123 | 0.0% | −29.7 | −53.0 | FAIL |
| Claims | USDTRY | z | 0.5/2/70/15/60 | −22.8 | [−28.1, −17.5] | −8.28 | 25% | 166 | 0.0% | −23.4 | −52.8 | FAIL |
| ISM | USDTRY | primary | 0/5/70/25/30 | −20.5 | [−29.5, −11.3] | −4.47 | 29% | 78 | 0.0% | −28.9 | −50.5 | FAIL |
| ISM | USDTRY | z | 1.0/2/25/10/30 | −19.4 | [−27.6, −11.2] | −4.64 | 0% | 17 | 0.0% | −40.0 | −49.4 | FAIL |
| Retail | USDTRY | primary | 50/2/70/15/60 | −18.3 | [−28.1, −7.7] | −3.54 | 28% | 47 | 0.0% | −26.5 | −48.3 | FAIL |
| Retail | USDTRY | z | 1.0/1/15/25/30 | −19.8 | [−25.5, −15.0] | −7.90 | 0% | 11 | 0.0% | −35.8 | −49.8 | FAIL |

(params = threshold/entry-delay-min/TP/SL/time-stop-min; z thresholds in σ;
WF OOS = mean P&L 2025-2026 with params selected on 2020-2024; 2x spread =
full-sample E[P&L] at doubled spread.)

### Reading the table honestly

- **Exotics (USDZAR, USDTRY): unambiguous losers.** On 24 of 26 exotic cells
  the best cell in the entire grid is negative, and on 26 of 26 the
  walk-forward OOS is negative. The event-time spread (25-30 pips baseline,
  realistically 2-4x that) plus entering *after* the initial move is a cost
  the post-release drift never recovers. The grid-positive column is 0.0%
  almost everywhere — this is not a near-miss, it is a structurally losing
  trade.
- **AUDUSD: flat-to-noise.** A few cells eke out small positive full-sample
  means (+0.3 to +6.8 pips) with CIs spanning zero — and **every single one
  flips negative out-of-sample**. The two seemingly-attractive cells are
  textbook overfitting smells and are flagged below.
- **FOMC: the strategy cannot trade it at all.** In 53 decisions
  (2020-2026), the actual differed from the FF consensus exactly twice
  (2022-06-15: 1.75% vs 1.50% forecast; 2024-09-18: 5.00% vs 5.25%). With
  <5 possible trades no statistics are computable. `surprise_pct` on a rate
  *level* is also semantically wrong (a 25 bp deviation registers as ±5-17%
  depending on the level). The production strategy, listening to FOMC with a
  10% threshold, would have traded ~1 time in 6.5 years.

### Overfitting flags (cells that look good but are not)

- **NFP/AUDUSD/z (E=+6.8, 61% of grid positive)**: only 10 trades, an 80%
  win rate driven by tight-TP cells, and OOS = −5.1. The high grid-positive
  share here reflects that only ~10 events pass the 1σ threshold at all —
  the "grid" is 216 re-slices of the same 10 outcomes.
- **PPI/AUDUSD/z (E=+5.4)**: 9 trades, CI [−0.7, +10.6] spans zero, train-set
  selection lands on different params (0.5σ) which lose OOS (−3.1). A lone
  positive island (10.6% grid-positive) in a sea of losses.
- **CPI/AUDUSD both definitions**: the most "stable" positive cells
  (+2.2/+2.5, N>40), but CIs span zero, edges vanish by 2x spread
  (+0.2/+0.5), and OOS is −6 to −10. Not tradeable.

### Spread sensitivity

No cell survives spread stress. Exotic cells lose an additional ~13-15 pips
per 0.5x spread increment (USDTRY baseline spread is 30 pips; event-time
spreads of 60-120 pips are routine per the production
`max_spread_overrides`), taking typical cells from −10/−20 at 1x to −40/−55
at 2x and beyond −100 at 4x. The three marginally-positive AUDUSD cells decay
to ≈0 by 2x and negative by 3-4x. In the straddle reports the pass bar was
"survives ≥2x spread"; here nothing survives even 1x convincingly.

### Why there is no edge (mechanics, not narrative)

1. **The strategy pays the full event spread to enter after the move.** By
   1-5 minutes post-release, the initial repricing (which is where the
   surprise information lives) is largely done; the entry chases it and the
   round-trip cost (25-30+ pips on exotics) exceeds the median residual
   drift.
2. **Surprise direction ≠ post-release drift direction at these horizons.**
   Win rates at the best cells sit at 17-48% on exotics — frequently *below*
   coin-flip even before costs, i.e. fading the surprise would also fail
   after costs.
3. **USDTRY is a managed float** — outside the 2021 crisis and step
   devaluations it barely reacts to US data; the straddle's (claimed) edge
   there came from volatility capture, not direction. Direction picking adds
   nothing.
4. **`surprise_pct` is scale-unstable**: percent-of-forecast explodes when
   forecasts are near zero (m/m prints of 0.1%) and compresses genuinely
   large misses when forecasts are large — the threshold therefore does not
   rank events by market impact. The z-score variant fixes the scaling and
   *still* fails, which is the stronger negative result.

---

## Production recommendation

**Delete (or permanently disable) `surprise.py`. Do not spend further effort
tuning it.**

- No (event type, pair, definition, parameter) combination passes — or comes
  within its confidence interval of passing — the standard pass criteria used
  by every prior report in this series.
- All 30 walk-forward OOS results are negative. This is not a "needs better
  parameters" situation; both surprise definitions fail across a 360-cell
  grid that brackets the production settings (10% / TP 25 / SL 15) from every
  side. The production cell itself (thr 10, N≈1-2, TP 25, SL 15) is negative
  everywhere it has enough trades to measure.
- Keeping the strategy registered but never scheduling it is acceptable as an
  interim; removing the dead code path is cleaner. Either way it must not be
  wired to any event in `config/settings.yaml`.
- The one reusable asset from this work is the data pipeline:
  `scripts/data/ff_history.csv` (991 verified forecast/actual rows,
  2020-2026) and the corrected-timezone bar fetcher in `mc_surprise.py`.

### Required follow-up (outside this report's scope)

**Re-validate the straddle strategy on corrected bar windows.** The timezone
bug in `download_dukascopy.py` (naive datetimes → `dukascopy_python` treats
them as local Edmonton time) means every prior 1-min MC report simulated
windows starting ~4-5 hours *after* the releases. The live bot's actual
trading window and the backtested window are not the same market regime. The
currently-enabled pairs/params (USDZAR, USDTRY 50/70/10, AUDUSD overrides)
rest on those backtests. Until re-validated on release-centered bars, treat
the MC-derived expectancies in reports 04-12 as unverified.
