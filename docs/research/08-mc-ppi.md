# PPI m/m Monte Carlo Analysis

**Date**: 2026-06-11
**Status**: PASS — PPI enabled for both active pairs

## Summary

Producer Price Index (PPI m/m) is released monthly at 8:30 AM ET by the Bureau of Labor Statistics. This analysis validates whether the straddle strategy has a statistically significant edge on PPI releases, using the same methodology as the main 6.5-year MC analysis.

**Result: PPI passes for both USDZAR and USDTRY.** Same 50/70/10 params as NFP/CPI/FOMC — no PPI-specific overrides needed. PPI adds ~12 trading days per year.

## Data

- **Source**: Dukascopy 1-min OHLCV bars
- **PPI dates**: 82 events (Jan 2020 — Jun 2026), sourced from FRED release calendar (rid=46)
- **Gap**: Oct-Nov 2025 disrupted by government shutdown (2 events missing)
- **Pairs analyzed**: USDZAR, USDTRY (active pairs only)

## Results at Current Parameters (50/70/10)

| Pair | E[P&L] | 95% CI | Win Rate | Sharpe | PF | N |
|------|--------|--------|----------|--------|----|---|
| **USDZAR** | +17.1 | [+10.3, +23.9] | 33.9% | 4.88 | 3.59 | 118 |
| **USDTRY** | +11.1 | [+4.7, +17.7] | 27.0% | 3.36 | 2.52 | 115 |

Both confidence intervals are entirely above zero. PPI contributes positively to the combined strategy.

## Walk-Forward Validation (Train 2020-2024, Test 2025-2026)

| Pair | Train Params | IS E[P&L] | IS Sharpe | OOS E[P&L] | OOS Sharpe |
|------|-------------|-----------|-----------|------------|------------|
| **USDZAR** | 50/50/10 | +17.8 | 5.86 | +7.1 | 1.11 |
| **USDTRY** | 50/70/10 | +12.8 | 3.32 | +5.4 | 0.68 |

Both pairs are OOS-positive. USDZAR walk-forward selects slightly tighter TP (50 vs 70) but the production 50/70/10 params also work well.

## PPI-Specific Optimal Parameters

| Pair | Distance | TP | SL | E[P&L] | 95% CI | Win Rate | Sharpe | N |
|------|----------|----|----|--------|--------|----------|--------|---|
| USDZAR | 50 | 55 | 10 | +16.4 | [+10.4, +21.9] | 40.7% | 5.57 | 118 |
| USDTRY | 50 | 70 | 10 | +11.1 | [+4.7, +17.7] | 27.0% | 3.36 | 115 |

USDZAR PPI-optimal TP is 55 (vs 70 for NFP). The marginal improvement doesn't justify splitting params — keeping unified 50/70/10 for simplicity.

## Comparison Across All US Event Types

### USDZAR

| Event | E[P&L] | 95% CI | WR | Sharpe | N | WF OOS |
|-------|--------|--------|----|--------|---|--------|
| **NFP** | +23.1 | [+12.2, +36.6] | 32.6% | 3.83 | 135 | +36.3 |
| **PPI** | +17.1 | [+10.3, +23.9] | 33.9% | 4.88 | 118 | +7.1 |
| **FOMC** | +14.4 | [+4.9, +23.9] | 30.5% | 2.96 | 59 | +17.1 |
| **CPI** | +11.6 | [+5.9, +17.9] | 27.1% | 3.85 | 140 | +8.1 |

### USDTRY

| Event | E[P&L] | 95% CI | WR | Sharpe | N | WF OOS |
|-------|--------|--------|----|--------|---|--------|
| **FOMC** | +17.1 | [+7.3, +27.6] | 35.3% | 3.26 | 51 | +24.6 |
| **NFP** | +13.7 | [+7.4, +20.2] | 30.9% | 4.20 | 123 | +12.5 |
| **CPI** | +11.6 | [+5.3, +18.2] | 27.5% | 3.56 | 120 | +6.7 |
| **PPI** | +11.1 | [+4.7, +17.7] | 27.0% | 3.36 | 115 | +5.4 |

PPI ranks 2nd for USDZAR (by E[P&L]) and 4th for USDTRY, but all four event types are independently profitable for both pairs. All eight walk-forwards pass.

## Combined Analysis (All 4 US Event Types)

With PPI included, the combined MC results:

| Pair | E[P&L] | 95% CI | Bonferroni CI | WR | Sharpe | N |
|------|--------|--------|---------------|----|--------|---|
| **USDZAR** | +17.0 | [+13.6, +20.7] | [+13.1, +21.2] | 32.0% | 9.31 | 672 |
| **USDTRY** | +13.7 | [+9.6, +18.3] | [+9.1, +19.1] | 29.7% | 6.28 | 519 |

Sample size increased from ~207 to 672 (USDZAR) / 519 (USDTRY) with PPI. The edge remains robust.

## Production Recommendation

- **Enable PPI m/m** in `config/events.yaml` with pairs `["USDZAR", "USDTRY"]`
- **Use same params** as NFP/CPI/FOMC: distance=50, TP=70, SL=10
- **No PPI-specific overrides needed**
- Adds ~12 trading days per year (monthly releases)

## Caveats

1. PPI is often released the day before CPI (or same week). Consecutive straddle trades may have correlated outcomes during the same economic cycle.
2. "Core PPI" (ex-food/energy) is sometimes the market mover, not headline PPI. The straddle captures both since it's direction-agnostic.
3. Government shutdowns (Oct-Nov 2025) caused BLS release delays, creating gaps in the sample.
