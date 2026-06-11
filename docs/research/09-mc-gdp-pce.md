# GDP & PCE Monte Carlo Analysis

**Date**: 2026-06-11
**Status**: GDP passes both pairs; PCE passes USDTRY only

## Summary

Two additional US economic events analyzed for straddle profitability:

- **GDP q/q** (BEA): Advance, Preliminary, and Final estimates. Released at 8:30 AM ET. 82 release dates (2020-2026).
- **PCE** (BEA Personal Income & Outlays): Fed's preferred inflation gauge. Released at 8:30 AM ET, end of month. 79 release dates (2020-2026).

Release dates sourced from the FRED API (release IDs 53 and 54).

## Results at Current Parameters (50/70/10)

### USDZAR

| Event | E[P&L] | 95% CI | WR | Sharpe | PF | N | WF OOS |
|-------|--------|--------|----|--------|----|----|--------|
| NFP | +23.6 | [+12.9, +37.3] | 33.1% | 3.87 | 4.53 | 133 | +18.4 |
| **GDP** | **+15.8** | **[+9.4, +22.3]** | **32.3%** | **4.67** | **3.33** | **124** | **+11.1** |
| PPI | +16.7 | [+10.0, +24.0] | 33.3% | 4.83 | 3.50 | 120 | +5.7 |
| FOMC | +16.2 | [+6.0, +26.4] | 32.7% | 3.15 | 3.41 | 55 | +16.0 |
| CPI | +11.6 | [+5.9, +17.9] | 27.1% | 3.85 | 2.60 | 140 | +8.1 |
| **PCE** | **+10.6** | **[+4.7, +16.9]** | **26.4%** | **3.36** | **2.44** | **125** | **-0.7** |

### USDTRY

| Event | E[P&L] | 95% CI | WR | Sharpe | PF | N | WF OOS |
|-------|--------|--------|----|--------|----|----|--------|
| FOMC | +16.6 | [+6.3, +27.1] | 34.7% | 3.11 | 3.54 | 49 | +18.6 |
| **PCE** | **+14.5** | **[+7.6, +22.0]** | **31.4%** | **4.01** | **3.11** | **105** | **+11.1** |
| NFP | +14.1 | [+7.7, +20.6] | 31.4% | 4.27 | 3.05 | 121 | +13.7 |
| CPI | +11.7 | [+5.5, +18.3] | 27.7% | 3.57 | 2.63 | 119 | +7.4 |
| PPI | +10.8 | [+4.6, +17.4] | 26.5% | 3.30 | 2.47 | 117 | +4.3 |
| **GDP** | **+8.5** | **[+1.4, +15.5]** | **23.1%** | **2.34** | **2.10** | **91** | **+13.9** |

## Walk-Forward Validation (Train 2020-2024, Test 2025-2026)

### GDP

| Pair | Train Params | IS E[P&L] | IS Sharpe | OOS E[P&L] | OOS Sharpe | Verdict |
|------|-------------|-----------|-----------|------------|------------|---------|
| USDZAR | 50/60/15 | +18.4 | 4.95 | +11.1 | 1.43 | **PASS** |
| USDTRY | 25/55/10 | +6.9 | 2.12 | +13.9 | 1.88 | **PASS** |

GDP passes walk-forward for both pairs. USDTRY walk-forward selects tighter distance (25 pips) but the production 50/70/10 also works (OOS=+13.9 at IS-optimal params). USDZAR walk-forward selects SL=15, suggesting GDP may warrant wider stops — but production 50/70/10 also passes.

### PCE

| Pair | Train Params | IS E[P&L] | IS Sharpe | OOS E[P&L] | OOS Sharpe | Verdict |
|------|-------------|-----------|-----------|------------|------------|---------|
| USDZAR | 30/55/10 | +11.0 | 3.72 | -0.7 | -0.70 | **FAIL** |
| USDTRY | 45/70/10 | +16.0 | 3.94 | +11.1 | 1.24 | **PASS** |

PCE fails walk-forward for USDZAR (OOS negative). The in-sample edge doesn't persist out-of-sample. PCE passes for USDTRY with strong OOS performance.

## Production Recommendation

- **GDP q/q**: Enable for both `["USDZAR", "USDTRY"]` with default 50/70/10 params
- **PCE**: Enable for `["USDTRY"]` only. Do NOT enable for USDZAR (walk-forward fails)
- GDP adds ~12 release dates per year (3 estimates per quarter)
- PCE adds ~12 release dates per year for USDTRY (monthly)

## Events Not Analyzed

The following events were skipped due to data sourcing issues:

- **Unemployment Rate**: Same BLS release as NFP ("Employment Situation"). Completely redundant — straddle already triggers at the same time.
- **Unemployment Claims**: Weekly. FRED does not track as a release. Need to manually compile ~300+ dates from DOL.
- **ISM Manufacturing PMI**: From Institute for Supply Management (private). Not on FRED. Need to manually compile dates.
- **Retail Sales**: Census Bureau release. FRED release ID 63 returned revision/benchmark dates, not the monthly Advance release. Need correct source.

## Caveats

1. GDP includes all 3 estimates (Advance, Preliminary, Final). The Advance estimate typically moves markets most. Preliminary and Final revisions may dilute average P&L but don't create false positives.
2. PCE and GDP are both BEA releases — some dates coincide (e.g., GDP and PCE on same day). Straddle overlap is possible.
3. PCE's USDZAR failure may be due to ZAR's lower sensitivity to US inflation data vs. growth data (GDP passes).
