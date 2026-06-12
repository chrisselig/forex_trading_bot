# Monte Carlo Optimization — CAD Pair Exploration

**Date**: June 2026
**Script**: `scripts/mc_cad_explore.py`
**Data source**: Dukascopy Bank SA (1-minute OHLCV, bid-side)

## Executive Summary

Testing alternative CAD-denominated pairs as replacements for USDCAD, which
fails walk-forward on both US events (OOS=-14.3) and Canadian events (OOS=-10.6).

- **Pairs tested**: CADJPY, EURCAD, GBPCAD
- **Event sources**: US (NFP/CPI/FOMC/PPI/GDP/PCE), Canada (BOC/CPI/Employment), Japan (BOJ/CPI, CADJPY only)
- **Grid**: 540 parameter combinations
- **Bootstrap**: 10,000 resamples, 95% confidence intervals
- **Walk-forward**: Train 2020-2024, test 2025-2026

## CADJPY

### Optimal Parameters by Event Source

| Source | Distance | TP | SL | E[P&L] | 95% CI | Win Rate | Sharpe | PF | CVaR(5%) | N |
|--------|----------|----|----|--------|--------|----------|--------|----|----------|---|
| **Canada** | 45 | 20 | 15 | +6.0 | [-1.0, +12.7] | 66.7% | 1.80 | 2.56 | -15.0 | 15 |
| **Japan** | 50 | 50 | 10 | +10.4 | [+2.2, +18.8] | 42.1% | 2.37 | 2.94 | -10.0 | 38 |
| **US** | 50 | 15 | 30 | +4.5 | [-0.6, +9.2] | 63.9% | 1.99 | 1.96 | -30.0 | 36 |

### CADJPY — Canada Events (Params: 45/20/15)

| Event | E[P&L] | 95% CI | Win Rate | Sharpe | PF | N |
|-------|--------|--------|----------|--------|----|---|
| BOC Rate Decision | +1.3 | [-4.4, +6.5] | 60.0% | 1.00 | 1.50 | 5 |
| Canada CPI | +8.3 | [-3.3, +20.0] | 66.7% | 1.89 | 2.67 | 6 |
| Canada Employment | +8.5 | [-6.3, +20.0] | 75.0% | 2.35 | 3.26 | 4 |

### CADJPY — Japan Events (Params: 50/50/10)

| Event | E[P&L] | 95% CI | Win Rate | Sharpe | PF | N |
|-------|--------|--------|----------|--------|----|---|
| BOJ Rate Decision | +8.7 | [-1.5, +20.0] | 37.5% | 1.51 | 2.39 | 24 |
| Japan CPI | +13.2 | [+0.7, +26.9] | 50.0% | 1.92 | 4.48 | 14 |

### CADJPY — US Events (Params: 50/15/30)

| Event | E[P&L] | 95% CI | Win Rate | Sharpe | PF | N |
|-------|--------|--------|----------|--------|----|---|
| CPI | +4.3 | [-4.0, +11.7] | 55.6% | 1.38 | 2.23 | 9 |
| FOMC | +1.7 | [-11.6, +15.0] | 66.7% | 0.64 | 1.20 | 9 |
| GDP | +8.5 | [+2.0, +14.4] | 66.7% | 3.09 | 10.50 | 6 |
| PCE | -9.0 | [-24.2, +7.6] | 25.0% | -1.60 | 0.29 | 4 |
| PPI | +11.9 | [+5.6, +15.0] | 85.7% | 5.43 | 13.04 | 7 |

### CADJPY — Walk-Forward Validation

| Source | Params | IS E[P&L] | IS Sharpe | IS N | OOS E[P&L] | OOS Sharpe | OOS N | Verdict |
|--------|--------|-----------|-----------|------|------------|------------|-------|---------|
| **Canada** | 15/15/10 | +1.1 | 1.01 | 92 | -0.9 | -0.56 | 37 | FAIL (no edge) |
| **Japan** | 45/55/10 | +6.7 | 1.63 | 39 | +17.9 | 1.26 | 7 | FAIL (no edge) |
| **US** | 35/30/15 | +5.0 | 2.12 | 62 | -3.3 | -1.12 | 14 | FAIL (overfit) |

> **Note on CADJPY/Japan**: The full-sample optimal has CI above zero [+2.2, +18.8]
> and OOS E[P&L]=+17.9, but the train-period IS CI_low didn't clear zero after
> Bonferroni correction (3 pairs tested). With only N=7 OOS trades, this is
> statistically unreliable — similar to the borderline USDJPY/BOJ finding in
> `06-non-us-events.md`. Not actionable without more data.

## EURCAD

### Optimal Parameters by Event Source

| Source | Distance | TP | SL | E[P&L] | 95% CI | Win Rate | Sharpe | PF | CVaR(5%) | N |
|--------|----------|----|----|--------|--------|----------|--------|----|----------|---|
| **Canada** | 25 | 15 | 15 | -0.7 | [-3.8, +2.4] | 46.9% | -0.45 | 0.89 | -15.0 | 64 |
| **US** | 10 | 15 | 20 | -0.8 | [-2.2, +0.6] | 48.9% | -1.10 | 0.89 | -20.0 | 411 |

### EURCAD — Canada Events (Params: 25/15/15)

| Event | E[P&L] | 95% CI | Win Rate | Sharpe | PF | N |
|-------|--------|--------|----------|--------|----|---|
| BOC Rate Decision | +0.9 | [-6.5, +7.9] | 45.5% | 0.24 | 1.18 | 11 |
| Canada CPI | -3.2 | [-7.6, +1.4] | 40.6% | -1.45 | 0.59 | 32 |
| Canada Employment | +2.3 | [-2.8, +7.4] | 57.1% | 0.95 | 1.55 | 21 |

### EURCAD — US Events (Params: 10/15/20)

| Event | E[P&L] | 95% CI | Win Rate | Sharpe | PF | N |
|-------|--------|--------|----------|--------|----|---|
| CPI | -2.5 | [-5.5, +0.4] | 41.6% | -1.65 | 0.68 | 89 |
| FOMC | -3.5 | [-7.4, +0.5] | 42.1% | -1.75 | 0.52 | 38 |
| GDP | -2.0 | [-5.2, +1.3] | 48.8% | -1.20 | 0.74 | 80 |
| NFP | +3.0 | [-1.4, +7.2] | 59.5% | 1.42 | 1.63 | 37 |
| PCE | +2.3 | [-0.8, +5.4] | 58.8% | 1.51 | 1.43 | 80 |
| PPI | -1.2 | [-4.3, +1.8] | 46.0% | -0.78 | 0.83 | 87 |

### EURCAD — Walk-Forward Validation

| Source | Params | IS E[P&L] | IS Sharpe | IS N | OOS E[P&L] | OOS Sharpe | OOS N | Verdict |
|--------|--------|-----------|-----------|------|------------|------------|-------|---------|
| **Canada** | 50/15/15 | +8.4 | 3.09 | 7 | -7.4 | -3.06 | 3 | FAIL (no edge) |
| **US** | 10/15/20 | -0.7 | -0.83 | 326 | -1.3 | -0.78 | 85 | FAIL (no edge) |

## GBPCAD

### Optimal Parameters by Event Source

| Source | Distance | TP | SL | E[P&L] | 95% CI | Win Rate | Sharpe | PF | CVaR(5%) | N |
|--------|----------|----|----|--------|--------|----------|--------|----|----------|---|
| **Canada** | 10 | 15 | 10 | -2.1 | [-3.5, -0.6] | 31.9% | -2.90 | 0.68 | -10.0 | 235 |
| **US** | 15 | 15 | 10 | -1.2 | [-2.3, +0.0] | 35.3% | -1.90 | 0.81 | -10.0 | 354 |

### GBPCAD — Canada Events (Params: 10/15/10)

| Event | E[P&L] | 95% CI | Win Rate | Sharpe | PF | N |
|-------|--------|--------|----------|--------|----|---|
| BOC Rate Decision | -3.4 | [-6.4, -0.2] | 25.0% | -2.32 | 0.52 | 48 |
| Canada CPI | -1.9 | [-4.1, +0.4] | 32.7% | -1.70 | 0.72 | 104 |
| Canada Employment | -1.6 | [-4.0, +0.8] | 34.9% | -1.38 | 0.74 | 83 |

### GBPCAD — US Events (Params: 15/15/10)

| Event | E[P&L] | 95% CI | Win Rate | Sharpe | PF | N |
|-------|--------|--------|----------|--------|----|---|
| CPI | -3.4 | [-5.6, -1.0] | 25.6% | -2.95 | 0.52 | 82 |
| FOMC | +1.5 | [-2.9, +6.0] | 47.8% | 0.64 | 1.36 | 23 |
| GDP | -1.5 | [-4.2, +1.4] | 32.9% | -1.12 | 0.77 | 70 |
| NFP | -2.4 | [-5.7, +1.1] | 27.8% | -1.53 | 0.61 | 36 |
| PCE | +0.6 | [-2.2, +3.5] | 43.1% | 0.42 | 1.11 | 72 |
| PPI | -0.3 | [-3.0, +2.5] | 40.8% | -0.23 | 0.96 | 71 |

### GBPCAD — Walk-Forward Validation

| Source | Params | IS E[P&L] | IS Sharpe | IS N | OOS E[P&L] | OOS Sharpe | OOS N | Verdict |
|--------|--------|-----------|-----------|------|------------|------------|-------|---------|
| **Canada** | 15/15/10 | -1.4 | -1.39 | 127 | -3.7 | -2.44 | 44 | FAIL (no edge) |
| **US** | 10/15/10 | -1.4 | -2.42 | 378 | -2.1 | -1.71 | 82 | FAIL (no edge) |

## Recommendation

**CADJPY**: **Not recommended.** No event source passes walk-forward validation.
CADJPY/Japan is borderline-interesting (positive OOS) but N=7 OOS trades is
insufficient. Revisit with more data in late 2027.

**EURCAD**: **Not recommended.** Negative expected P&L even at optimal parameters
on both US and Canadian events. No edge exists.

**GBPCAD**: **Not recommended.** Consistently negative expected P&L across all
event sources and parameter combinations. Definitively no edge.

**Conclusion**: No viable CAD pair replacement for USDCAD exists in the straddle
strategy. The straddle edge remains concentrated in emerging market pairs (USDZAR,
USDTRY) where event-driven volatility is large relative to spreads.

## Caveats

1. **Cross pairs have wider spreads**: CADJPY, EURCAD, GBPCAD typically have wider
event-time spreads than majors. The spread estimates used here are conservative but
should be validated with live data.

2. **Indirect exposure on US events**: These pairs don't contain USD directly. US events
affect them through cross-rate dynamics (e.g., NFP moves USD, which moves USDCAD and
USDJPY, which affects CADJPY). The signal may be weaker or delayed.

3. **Canadian event sample**: ~208 Canadian events over 6.5 years. Per-event-type
breakdown (BOC: ~52, CPI: ~78, Employment: ~78) is directional, not definitive.

4. **Home currency benefit**: Even if edge is marginal, trading a CAD pair avoids
the currency sweep cost (converting exotic trade P&L back to CAD). This is a small
but real operational advantage — but insufficient to overcome negative expectancy.
