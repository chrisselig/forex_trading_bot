# Straddle Parameter Optimization

## Executive Summary

- **Analysis period**: January 2025 — June 2026
- **Events analyzed**: 47 (NFP: 18, CPI: 17, FOMC: 12)
- **Data points cached**: 230 (event x pair combinations)
- **Pairs**: GBPUSD, USDCAD, GBPJPY, USDZAR, USDTRY
- **Monte Carlo iterations**: 10,000
- **Confidence level**: 95%

## Methodology

1. Collected 1-hour bars from IB for a 2-day window around each event
2. Simulated straddle mechanics (buy stop + sell stop, each with TP/SL) using hourly OHLC
3. Grid search over distance (10-50), TP (15-70), SL (5-30) — all in pips
4. Bootstrap resampled 10,000x to build confidence intervals
5. Scored on pessimistic metric: lower bound of 95% CI on mean P&L
6. Walk-forward validation: train on 2025, test on 2026
7. Spread modeled as fixed cost (conservative event-time estimates)

## Optimal Parameters by Pair

| Pair | Distance | TP | SL | E[P&L] | 95% CI | Win Rate | Sharpe | Profit Factor | CVaR(5%) | N |
|------|----------|----|----|--------|--------|----------|--------|---------------|----------|---|
| **GBPUSD** | 15 | 40 | 10 | +5.6 | [-1.2, +12.7] | 34.1% | 1.54 | 1.88 | -10.0 | 41 |
| **USDCAD** | 15 | 20 | 10 | -0.0 | [-4.5, +4.6] | 32.4% | -0.10 | 0.99 | -10.0 | 34 |
| **GBPJPY** | 45 | 35 | 10 | +5.8 | [-3.2, +14.7] | 35.0% | 1.13 | 1.88 | -10.0 | 20 |
| **USDZAR** | 10 | 70 | 10 | -1.4 | [-7.1, +5.7] | 10.7% | -0.67 | 0.84 | -10.0 | 56 |
| **USDTRY** | 50 | 70 | 10 | +0.6 | [-5.5, +8.1] | 13.2% | -0.03 | 1.07 | -10.0 | 53 |

!!! info "Reading the table"
    E[P&L] is expected profit per trade in pips. The 95% CI is the confidence interval on that mean — if the CI excludes zero, we have statistical evidence the strategy is profitable. CVaR(5%) is the average P&L of the worst 5% of trades (tail risk). Profit factor > 1.0 means gross profits exceed gross losses.

## Walk-Forward Validation

Walk-forward validation guards against **overfitting**. We optimize parameters on one time period (in-sample), then test those exact parameters on a later period the optimizer never saw (out-of-sample). If performance holds, the edge is likely real. If it collapses, the optimizer was curve-fitting noise. See the [Monte Carlo 1-min report](monte-carlo-1min.md#walk-forward-validation) for a fuller explanation.

Here: train on 2025, test on 2026.

| Pair | Params | In-Sample E[P&L] | In-Sample Sharpe | Out-of-Sample E[P&L] | Out-of-Sample Sharpe |
|------|--------|-------------------|------------------|----------------------|----------------------|
| **GBPUSD** | 15/40/10 | +5.8 | 1.40 | +5.0 | 0.34 |
| **USDCAD** | 15/20/10 | -0.8 | -0.39 | +2.3 | 0.30 |
| **GBPJPY** | 50/70/10 | +14.4 | 1.47 | -10.0 | -10.00 |
| **USDZAR** | 10/70/10 | -0.0 | -0.26 | -5.0 | -3.84 |
| **USDTRY** | 10/30/10 | -5.9 | -3.57 | -2.5 | -1.09 |

!!! warning "Out-of-sample degradation"
    GBPJPY shows severe out-of-sample degradation — the in-sample Sharpe of 1.47 collapses completely. This suggests the in-sample result was noise. GBPUSD is the most robust, with consistent positive performance across both periods.

## Risk Analysis at Optimal Parameters

### GBPUSD (Best Performer)

- **Reward:Risk ratio**: 4.0:1 (TP=40 / SL=10)
- **Breakeven win rate**: 20.0% (actual: 34.1%)
- **Edge**: +14.1 percentage points above breakeven
- **Median max drawdown**: 70 pips
- **95th percentile max drawdown**: 140 pips

### USDCAD (Marginal)

- **Reward:Risk ratio**: 2.0:1 (TP=20 / SL=10)
- **Breakeven win rate**: 33.3% (actual: 32.4%)
- **Edge**: -1.0 percentage points — essentially breakeven

### GBPJPY (Overfit Risk)

- **Reward:Risk ratio**: 3.5:1 (TP=35 / SL=10)
- **Breakeven win rate**: 22.2% (actual: 35.0%)
- **Edge**: +12.8 in-sample, but out-of-sample collapse invalidates this

### USDZAR / USDTRY (Negative Edge)

Both exotic pairs show negative or marginal expected value. The wider spreads and lower liquidity during events eat into the straddle's profitability.

## Recommended Settings

Based on the full-sample optimization and walk-forward validation:

```yaml
strategy:
  straddle_distance_pips: 15
  straddle_tp_pips: 40
  straddle_sl_pips: 10
```

### Per-Pair Overrides

| Pair | Distance | TP | SL |
|------|----------|----|----|
| GBPUSD | 15 | 40 | 10 |
| USDCAD | 15 | 20 | 10 |
| GBPJPY | 45 | 35 | 10 |
| USDZAR | 10 | 70 | 10 |
| USDTRY | 50 | 70 | 10 |

## Caveats

1. **Hourly bar resolution** — IB paper accounts only provide 1-hour bars. Intra-hour paths cannot be observed. When both TP and SL could be hit in the same bar, SL is assumed first (pessimistic). **Update:** 1-minute data is now available via [Dukascopy](dukascopy-data.md) — a re-run with granular data is planned.

2. **Small sample size** — ~48 events over 18 months. Bootstrap CIs account for sampling uncertainty, but structural regime changes are not captured.

3. **Spread approximation** — Event-time spreads are modeled as fixed estimates. Actual spreads vary. Exotic pair spreads can exceed 50 pips during NFP.

4. **Slippage not modeled** — Stop orders can gap through during fast markets. Actual fills may be worse than simulated.

5. **No OCA modeling** — Both straddle legs can trigger independently. Whipsaw (both legs trigger and stop out) is modeled accurately in CVaR.

6. **Multiple testing** — Grid search over ~500 parameter combinations inflates spurious results. Walk-forward validation is the primary guard.

7. **FOMC has different dynamics** — Rate decisions move markets differently from data releases. Consider splitting analysis by event type.
