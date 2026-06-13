# Monte Carlo Optimization — Remaining US Events

**Date**: June 2026
**Script**: `scripts/mc_remaining_us.py`
**Data source**: Dukascopy Bank SA (1-minute OHLCV, bid-side)
**Grid**: 540 parameter combinations (distance × TP × SL)
**Bootstrap**: 10,000 resamples, 95% CI
**Walk-forward**: Train 2020-2023, Test 2024-2026

## Overview

Three previously-untested US event types analyzed on all active pairs:

| Event Type | Frequency | Release Time | Events (Jan 2020 — Jun 2026) |
|------------|-----------|-------------|------------------------------|
| Unemployment Claims | Weekly (Thursday) | 8:30 AM ET | ~337 |
| ISM Manufacturing PMI | Monthly (1st business day) | 10:00 AM ET | ~78 |
| Retail Sales m/m | Monthly (~15th) | 8:30 AM ET | ~77 |

## Results Summary

| Event Type | USDZAR | USDTRY | AUDUSD |
|------------|--------|--------|--------|
| Unemployment Claims | FAIL (no edge) | **PASS** (all spreads) | FAIL (CI spans zero) |
| ISM Manufacturing PMI | FAIL (no edge) | **PASS** (all spreads) | FAIL (N=3, insufficient) |
| Retail Sales | FAIL (no edge) | **PASS** (all spreads) | FAIL (no edge) |

**All three event types pass walk-forward on USDTRY only.** USDZAR shows deeply negative P&L across all events — the spread cost overwhelms any directional move. AUDUSD lacks sufficient volatility on these events.

---

## Unemployment Claims

### USDZAR — FAIL

**Full-sample optimal** (spread=50.0): D=50 TP=60 SL=10
E[P&L]=-7.3, CI=[-8.5, -6.1], Sharpe=-9.87, WR=3.8%, PF=0.24, N=497

Every parameter combination is negative. The weekly release doesn't generate enough ZAR volatility to overcome the 50-pip spread.

#### Spread Sensitivity + Walk-Forward

| Spread | Best Params | IS E[P&L] | IS CI | OOS E[P&L] | Verdict |
|--------|-------------|-----------|-------|------------|---------|
| 30 | 10/20/10 | -6.5 | [-7.5, -5.4] | -7.7 | FAIL (no edge) |
| 40 | 10/15/10 | -7.1 | [-7.9, -6.2] | -7.9 | FAIL (no edge) |
| 50 | 10/15/10 | -8.0 | [-8.7, -7.2] | -8.2 | FAIL (no edge) |
| 60 | 50/55/10 | -7.2 | [-8.5, -5.6] | -7.0 | FAIL (no edge) |
| 70 | 45/55/10 | -7.2 | [-8.5, -5.6] | -7.0 | FAIL (no edge) |
| 80 | 40/55/10 | -7.2 | [-8.5, -5.6] | -7.0 | FAIL (no edge) |

### USDTRY — PASS

**Full-sample optimal** (spread=50.0): D=50 TP=70 SL=10
E[P&L]=+11.9, CI=[+8.2, +15.7], Sharpe=6.15, WR=28.1%, PF=2.66, N=338

Same 50/70/10 parameters as existing US events. Strong upward trend in year-by-year performance.

#### Year-by-Year

| Year | E[P&L] | Win Rate | N |
|------|--------|----------|---|
| 2020 | +4.7 | 18% | 38 |
| 2021 | +3.0 | 18% | 44 |
| 2022 | -0.8 | 12% | 52 |
| 2023 | +10.4 | 27% | 56 |
| 2024 | +13.4 | 29% | 58 |
| 2025 | +25.9 | 45% | 58 |
| 2026 | +28.0 | 50% | 32 |

#### Spread Sensitivity + Walk-Forward

| Spread | Best Params | IS E[P&L] | IS CI | IS Sharpe | OOS E[P&L] | OOS Sharpe | OOS WR | Verdict |
|--------|-------------|-----------|-------|-----------|------------|------------|--------|---------|
| 30 | 45/70/10 | +4.8 | [+0.6, +9.1] | 2.16 | +16.9 | 5.52 | 34.0% | PASS |
| 40 | 40/70/10 | +4.8 | [+0.6, +9.1] | 2.16 | +16.9 | 5.52 | 34.0% | PASS |
| 50 | 35/70/10 | +4.8 | [+0.6, +9.1] | 2.16 | +16.9 | 5.52 | 34.0% | PASS |
| 60 | 30/70/10 | +4.8 | [+0.6, +9.1] | 2.16 | +16.9 | 5.52 | 34.0% | PASS |
| 70 | 50/65/10 | +6.0 | [+1.5, +10.6] | 2.61 | +21.7 | 6.96 | 42.3% | PASS |
| 80 | 50/70/10 | +8.3 | [+3.5, +13.3] | 3.23 | +22.7 | 6.85 | 40.8% | PASS |

### AUDUSD — FAIL

**Full-sample optimal** (spread=1.5): D=25 TP=25 SL=30
E[P&L]=+2.8, CI=[-0.9, +6.5], Sharpe=1.49, WR=54.5%, PF=1.84, N=44

CI spans zero. Insufficient volatility on a weekly US release for a non-USD-denominated pair.

---

## ISM Manufacturing PMI

### USDZAR — FAIL

**Full-sample optimal** (spread=50.0): D=25 TP=15 SL=10
E[P&L]=-7.4, CI=[-8.7, -5.8], Sharpe=-9.35, WR=10.5%, PF=0.18, N=114

Deeply negative at all spread levels. No edge.

### USDTRY — PASS

**Full-sample optimal** (spread=50.0): D=10 TP=70 SL=10
E[P&L]=+10.4, CI=[+3.9, +17.8], Sharpe=2.91, WR=25.5%, PF=2.40, N=98

Note: The optimal full-sample params use D=10 (very tight distance), but walk-forward selects D=40-50 with TP=55 — more conservative and consistent with other events.

#### Year-by-Year

| Year | E[P&L] | Win Rate | N |
|------|--------|----------|---|
| 2020 | +14.0 | 30% | 10 |
| 2021 | +19.1 | 36% | 11 |
| 2022 | +3.3 | 17% | 18 |
| 2023 | +4.1 | 18% | 17 |
| 2024 | +15.0 | 31% | 16 |
| 2025 | +8.8 | 24% | 17 |
| 2026 | +16.7 | 33% | 9 |

#### Spread Sensitivity + Walk-Forward

| Spread | Best Params | IS E[P&L] | IS CI | IS Sharpe | OOS E[P&L] | OOS Sharpe | OOS WR | Verdict |
|--------|-------------|-----------|-------|-----------|------------|------------|--------|---------|
| 30 | 40/55/10 | +8.7 | [+1.2, +17.5] | 2.09 | +7.1 | 1.45 | 26.3% | PASS |
| 40 | 50/55/10 | +10.4 | [+2.7, +18.0] | 2.42 | +6.3 | 1.25 | 25.0% | PASS |
| 50 | 45/55/10 | +10.4 | [+2.7, +18.0] | 2.42 | +6.3 | 1.25 | 25.0% | PASS |
| 60 | 40/55/10 | +10.4 | [+2.7, +18.0] | 2.42 | +6.3 | 1.25 | 25.0% | PASS |
| 70 | 35/55/10 | +10.4 | [+2.7, +18.0] | 2.42 | +6.3 | 1.25 | 25.0% | PASS |
| 80 | 30/55/10 | +10.4 | [+2.7, +18.0] | 2.42 | +6.3 | 1.25 | 25.0% | PASS |

### AUDUSD — FAIL

**Full-sample optimal** (spread=1.5): D=35 TP=15 SL=30
E[P&L]=+10.8, CI=[+2.4, +15.0], Sharpe=4.59, WR=100.0%, N=3

Only 3 trades triggered at optimal params — far too few for statistical significance.

---

## Retail Sales

### USDZAR — FAIL

**Full-sample optimal** (spread=50.0): D=30 TP=55 SL=10
E[P&L]=-5.9, CI=[-8.6, -2.5], Sharpe=-4.06, WR=6.3%, PF=0.37, N=95

Negative at all spread levels. No edge.

### USDTRY — PASS

**Full-sample optimal** (spread=50.0): D=50 TP=65 SL=10
E[P&L]=+14.7, CI=[+7.5, +22.2], Sharpe=3.91, WR=34.0%, PF=2.97, N=97

Strong results consistent with other US events. Params in the 50/60-70/10 family.

#### Year-by-Year

| Year | E[P&L] | Win Rate | N |
|------|--------|----------|---|
| 2020 | +15.9 | 36% | 11 |
| 2021 | +7.3 | 23% | 13 |
| 2022 | +15.0 | 33% | 18 |
| 2023 | +13.1 | 31% | 13 |
| 2024 | +14.1 | 37% | 19 |
| 2025 | +18.1 | 38% | 16 |
| 2026 | +22.1 | 43% | 7 |

#### Spread Sensitivity + Walk-Forward

| Spread | Best Params | IS E[P&L] | IS CI | IS Sharpe | OOS E[P&L] | OOS Sharpe | OOS WR | Verdict |
|--------|-------------|-----------|-------|-----------|------------|------------|--------|---------|
| 30 | 50/70/10 | +9.6 | [+1.0, +18.1] | 2.04 | +9.6 | 1.61 | 26.2% | PASS |
| 40 | 50/65/10 | +11.6 | [+3.1, +21.2] | 2.48 | +15.3 | 2.57 | 35.7% | PASS |
| 50 | 50/65/10 | +12.9 | [+3.6, +22.5] | 2.70 | +17.0 | 2.80 | 38.1% | PASS |
| 60 | 50/60/10 | +14.4 | [+5.4, +23.7] | 3.10 | +14.4 | 2.47 | 37.5% | PASS |
| 70 | 45/60/10 | +14.4 | [+5.4, +23.7] | 3.10 | +14.4 | 2.47 | 37.5% | PASS |
| 80 | 40/60/10 | +14.4 | [+5.4, +23.7] | 3.10 | +14.4 | 2.47 | 37.5% | PASS |

### AUDUSD — FAIL

**Full-sample optimal** (spread=1.5): D=10 TP=15 SL=10
E[P&L]=-0.5, CI=[-3.1, +2.1], Sharpe=-0.41, WR=41.8%, PF=0.89, N=55

No edge at any spread level.

---

## Recommendation

### Enable on USDTRY (all three events)

All three event types pass walk-forward at every spread level on USDTRY. The results are remarkably consistent:

| Event | Full-Sample E[P&L] | WF OOS E[P&L] | Optimal Params | Compatible with 50/70/10? |
|-------|-------------------|----------------|----------------|--------------------------|
| Unemployment Claims | +11.9 | +16.9 to +22.7 | 50/70/10 | Yes (exact match) |
| ISM Manufacturing PMI | +10.4 | +6.3 to +7.1 | ~45/55/10 | Close (TP differs) |
| Retail Sales | +14.7 | +9.6 to +17.0 | 50/65/10 | Close (TP differs) |

**Unemployment Claims** uses the exact same 50/70/10 parameters as existing events — can be enabled immediately with no parameter changes. Adds ~50 trading days/year (weekly).

**ISM Manufacturing PMI** and **Retail Sales** walk-forward with slightly different TP values (55 and 65 vs 70), but these are within the stable parameter region. The existing 50/70/10 should work — the full-sample results at those params are positive. Adds ~12 + ~12 = 24 trading days/year.

**Combined impact**: +74 additional USDTRY trading days/year.

### Do not enable on USDZAR or AUDUSD

These events do not generate sufficient price movement to overcome the spread on USDZAR, and AUDUSD shows no edge on any US secondary event.

### Capacity note

Unemployment Claims releases every Thursday at 8:30 AM ET — the same time as NFP (first Friday), CPI (~13th), and Retail Sales (~15th). On days when Unemployment Claims coincides with a higher-impact event (NFP, CPI, PPI, Retail Sales), the bot should already be trading that event. The existing `max_concurrent_positions` limit will prevent doubling up.
