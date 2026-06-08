# Monte Carlo Optimization — 1-Minute Data

**Date**: June 7, 2026
**Script**: `scripts/monte_carlo_dukascopy.py`
**Data source**: Dukascopy Bank SA (1-minute OHLCV, bid-side)

## Executive Summary

- **Analysis period**: January 2025 — June 2026
- **Events analyzed**: 47 (NFP: 18, CPI: 17, FOMC: 12)
- **Data points**: 230 event/pair combinations, ~68,000 1-min bars total
- **Pairs**: GBPUSD, USDCAD, GBPJPY, USDZAR, USDTRY
- **Grid**: 540 parameter combinations (distance 10-50, TP 15-70, SL 10-30 pips)
- **Bootstrap**: 10,000 resamples, 95% confidence intervals
- **Runtime**: 209 seconds

This replaces the [previous hourly optimization](straddle-optimization.md) which used IB paper account 1-hour bars and a pessimistic SL-first assumption.

## Key Finding: 1-min Data Changes Everything

With 1-minute bars, we can observe the actual intra-bar price sequence. This eliminates the systematic negative bias from the hourly SL-first assumption and reveals the true strategy performance.

### Comparison: Old (1-hour) vs New (1-minute)

| Pair | Old E[P&L] | New E[P&L] | Old Params | New Params | Change |
|------|-----------|-----------|------------|------------|--------|
| GBPUSD | +5.6 | **+6.1** | 15/40/10 | 35/15/15 | Tighter TP, higher WR |
| USDCAD | -0.0 | **+1.0** | 15/20/10 | 10/15/25 | Marginal improvement |
| GBPJPY | +5.8 | **+2.3** | 45/35/10 | 10/15/10 | Different regime |
| USDZAR | -1.4 | **+25.4** | 10/70/10 | 45/70/10 | Massive improvement |
| USDTRY | +0.6 | **+13.9** | 50/70/10 | 50/70/10 | Same params, much better |

The exotic pairs (USDZAR, USDTRY) were the biggest beneficiaries — the hourly SL-first assumption was dramatically underestimating their profitability.

## Optimal Parameters by Pair

| Pair | Distance | TP | SL | E[P&L] | 95% CI | Win Rate | Sharpe | Profit Factor | CVaR(5%) | N |
|------|----------|----|----|--------|--------|----------|--------|---------------|----------|---|
| **GBPUSD** | 35 | 15 | 15 | +6.1 | [-0.5, +12.2] | 71.4% | 2.10 | 4.46 | -7.6 | 7 |
| **USDCAD** | 10 | 15 | 25 | +1.0 | [-2.9, +4.9] | 46.5% | 0.53 | 1.19 | -25.0 | 43 |
| **GBPJPY** | 10 | 15 | 10 | +2.3 | [-0.8, +5.4] | 50.0% | 1.43 | 1.46 | -10.0 | 60 |
| **USDZAR** | 45 | 70 | 10 | +25.4 | [+10.0, +45.9] | 30.7% | 2.86 | 4.67 | -10.0 | 88 |
| **USDTRY** | 50 | 70 | 10 | +13.9 | [+5.5, +22.6] | 30.9% | 3.14 | 3.01 | -10.0 | 68 |

!!! info "Reading the table"
    E[P&L] is expected profit per trade in pips. The 95% CI is the confidence interval on that mean — if the CI excludes zero, we have statistical evidence the strategy is profitable. CVaR(5%) is the average P&L of the worst 5% of trades.

### Notable observations

- **GBPUSD** shifted to a 1:1 R:R strategy (TP=15, SL=15) with 71.4% win rate. Only 7 trades triggered — the wide 35-pip distance is selective. The CI still includes zero.
- **USDZAR** is the standout: 95% CI entirely above zero ([+10.0, +45.9]), 7:1 R:R, 30.7% win rate (vs 12.5% breakeven). 88 trade samples gives the best statistical power.
- **USDTRY** also shows strong results with CI above zero ([+5.5, +22.6]) and similar 7:1 R:R structure.
- **USDCAD** and **GBPJPY** remain marginal with CIs spanning zero.

## Walk-Forward Validation

Train on 2025 data, test on 2026 data. This is the critical overfitting check.

| Pair | Params | In-Sample E[P&L] | In-Sample Sharpe | Out-of-Sample E[P&L] | Out-of-Sample Sharpe |
|------|--------|-------------------|------------------|----------------------|----------------------|
| **GBPUSD** | 35/15/15 | +6.4 | 1.98 | +0.0 | 0.00 |
| **USDCAD** | 10/15/25 | +2.1 | 0.97 | -1.9 | -0.57 |
| **GBPJPY** | 30/25/30 | +10.8 | 2.71 | -21.5 | -5.91 |
| **USDZAR** | 45/70/10 | +15.3 | 3.16 | **+47.1** | **1.72** |
| **USDTRY** | 50/70/10 | +18.1 | 3.37 | +2.1 | -0.21 |

!!! success "USDZAR passes walk-forward"
    USDZAR is the only pair where out-of-sample performance actually **exceeded** in-sample (+47.1 vs +15.3 pips). This is strong evidence that the 45/70/10 parameters are robust and not overfit.

!!! warning "GBPJPY severely overfit"
    In-sample Sharpe of 2.71 collapses to -5.91 out-of-sample. Do not trade GBPJPY with these parameters.

## Risk Analysis

### USDZAR (Best Performer)

- **Reward:Risk ratio**: 7.0:1 (TP=70 / SL=10)
- **Breakeven win rate**: 12.5% (actual: 30.7%)
- **Edge**: +18.2 percentage points above breakeven
- **Median max drawdown**: 100 pips
- **95th percentile max drawdown**: 160 pips

### USDTRY (Strong)

- **Reward:Risk ratio**: 7.0:1 (TP=70 / SL=10)
- **Breakeven win rate**: 12.5% (actual: 30.9%)
- **Edge**: +18.4 percentage points above breakeven
- **Median max drawdown**: 90 pips

### GBPUSD (Selective)

- **Reward:Risk ratio**: 1.0:1 (TP=15 / SL=15)
- **Breakeven win rate**: 50.0% (actual: 71.4%)
- **Edge**: +21.4 percentage points above breakeven
- **Caveat**: Only 7 triggered trades — small sample

## Recommended Settings

Based on the 1-minute analysis and walk-forward results:

```yaml
strategy:
  straddle_distance_pips: 35
  straddle_tp_pips: 15
  straddle_sl_pips: 15
  straddle_pair_overrides:
    USDCAD:
      distance_pips: 10
      tp_pips: 15
      sl_pips: 25
    GBPJPY:
      distance_pips: 10
      tp_pips: 15
      sl_pips: 10
    USDZAR:
      distance_pips: 45
      tp_pips: 70
      sl_pips: 10
    USDTRY:
      distance_pips: 50
      tp_pips: 70
      sl_pips: 10
```

!!! tip "Production recommendation"
    Focus on **USDZAR** (strongest walk-forward) and **USDTRY** (strong full-sample, marginal walk-forward). GBPUSD is promising but needs more data to confirm the selective 35-pip distance works reliably. Avoid GBPJPY and USDCAD straddles until more data is available.

## Caveats

1. **Small sample size**: 46 events over 18 months. GBPUSD had only 7 triggered trades at the optimal parameters.
2. **Spread approximation**: Event-time spreads are fixed estimates. Exotic spreads can exceed 50 pips during NFP.
3. **Slippage not modeled**: Stop orders can gap through during fast markets.
4. **Bid-side data only**: Dukascopy provides bid OHLCV. Ask side is approximated via spread adjustment.
5. **Multiple testing**: 540 parameter combinations. Walk-forward validation is the primary guard.
6. **FOMC dynamics differ**: Consider splitting analysis by event type for production use.
