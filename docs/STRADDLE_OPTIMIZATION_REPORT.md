# Straddle Parameter Optimization Report

## Executive Summary

- **Analysis period**: January 2025 — June 2026
- **Events analyzed**: 47 (NFP: 18, CPI: 17, FOMC: 12)
- **Data points cached**: 230 (event × pair combinations)
- **Pairs**: GBPUSD, USDCAD, GBPJPY, USDZAR, USDTRY
- **Monte Carlo iterations**: 10,000
- **Confidence level**: 95%

### Methodology

1. Collected 1-hour bars from IB for a 2-day window around each event
2. Simulated straddle mechanics (buy stop + sell stop, each with TP/SL) using hourly OHLC
3. Grid search over distance (10-50), TP (15-70), SL (5-30) — all in pips
4. Bootstrap resampled 10,000x to build confidence intervals
5. Scored on pessimistic metric: lower bound of 95% CI on mean P&L
6. Walk-forward validation: train on 2025, test on 2026
7. Spread modeled as fixed cost (conservative event-time estimates)

---

## Optimal Parameters by Pair

| Pair | Distance | TP | SL | E[P&L] | 95% CI | Win Rate | Sharpe | Profit Factor | CVaR(5%) | N |
|------|----------|----|----|--------|--------|----------|--------|---------------|----------|---|
| **GBPUSD** | 15 | 40 | 10 | +5.6 | [-1.2, +12.7] | 34.1% | 1.54 | 1.88 | -10.0 | 41 |
| **USDCAD** | 15 | 20 | 10 | -0.0 | [-4.5, +4.6] | 32.4% | -0.10 | 0.99 | -10.0 | 34 |
| **GBPJPY** | 45 | 35 | 10 | +5.8 | [-3.2, +14.7] | 35.0% | 1.13 | 1.88 | -10.0 | 20 |
| **USDZAR** | 10 | 70 | 10 | -1.4 | [-7.1, +5.7] | 10.7% | -0.67 | 0.84 | -10.0 | 56 |
| **USDTRY** | 50 | 70 | 10 | +0.6 | [-5.5, +8.1] | 13.2% | -0.03 | 1.07 | -10.0 | 53 |

> **Reading the table**: E[P&L] is the expected profit per trade in pips.
> The 95% CI is the confidence interval on that mean — if the CI excludes zero,
> we have statistical evidence the strategy is profitable. CVaR(5%) is the
> average P&L of the worst 5% of trades (tail risk). Profit factor > 1.0 means
> gross profits exceed gross losses.

---

## Walk-Forward Validation

Train on 2025 data, test on 2026 data. This detects overfitting — if in-sample
performance is strong but out-of-sample collapses, the parameters are overfit.

| Pair | Params | In-Sample (2025) | | Out-of-Sample (2026) | |
|------|--------|-----|------|------|------|
| | D / TP / SL | E[P&L] | Sharpe | E[P&L] | Sharpe |
| **GBPUSD** | 15 / 40 / 10 | +5.8 | 1.40 | +5.0 | 0.34 |
| **USDCAD** | 15 / 20 / 10 | -0.8 | -0.39 | +2.3 | 0.30 |
| **GBPJPY** | 50 / 70 / 10 | +14.4 | 1.47 | -10.0 | -10.00 |
| **USDZAR** | 10 / 70 / 10 | -0.0 | -0.26 | -5.0 | -3.84 |
| **USDTRY** | 10 / 30 / 10 | -5.9 | -3.57 | -2.5 | -1.09 |

> **What to look for**: Out-of-sample Sharpe should be at least 50% of in-sample.
> If it collapses to near-zero or negative, the in-sample result was likely noise.

---

## Risk Analysis at Optimal Parameters

### GBPUSD

- **Reward:Risk ratio**: 4.0:1 (TP=40 / SL=10)
- **Breakeven win rate**: 20.0% (actual: 34.1%)
- **Edge**: +14.1 percentage points above breakeven
- **Median max drawdown**: 70 pips
- **95th percentile max drawdown**: 140 pips
- **Worst 5% average trade**: -10.0 pips

### USDCAD

- **Reward:Risk ratio**: 2.0:1 (TP=20 / SL=10)
- **Breakeven win rate**: 33.3% (actual: 32.4%)
- **Edge**: -1.0 percentage points above breakeven
- **Median max drawdown**: 80 pips
- **95th percentile max drawdown**: 160 pips
- **Worst 5% average trade**: -10.0 pips

### GBPJPY

- **Reward:Risk ratio**: 3.5:1 (TP=35 / SL=10)
- **Breakeven win rate**: 22.2% (actual: 35.0%)
- **Edge**: +12.8 percentage points above breakeven
- **Median max drawdown**: 50 pips
- **95th percentile max drawdown**: 100 pips
- **Worst 5% average trade**: -10.0 pips

### USDZAR

- **Reward:Risk ratio**: 7.0:1 (TP=70 / SL=10)
- **Breakeven win rate**: 12.5% (actual: 10.7%)
- **Edge**: -1.8 percentage points above breakeven
- **Median max drawdown**: 230 pips
- **95th percentile max drawdown**: 400 pips
- **Worst 5% average trade**: -10.0 pips

### USDTRY

- **Reward:Risk ratio**: 7.0:1 (TP=70 / SL=10)
- **Breakeven win rate**: 12.5% (actual: 13.2%)
- **Edge**: +0.7 percentage points above breakeven
- **Median max drawdown**: 180 pips
- **95th percentile max drawdown**: 340 pips
- **Worst 5% average trade**: -10.0 pips

---

## Recommended Settings

Based on the full-sample optimization and walk-forward validation,
the recommended `settings.yaml` straddle parameters are:

```yaml
strategy:
  straddle_distance_pips: 15
  straddle_tp_pips: 40
  straddle_sl_pips: 10
```

### Per-pair overrides (if implementing pair-specific params):

| Pair | Distance | TP | SL |
|------|----------|----|----|
| GBPUSD | 15 | 40 | 10 |
| USDCAD | 15 | 20 | 10 |
| GBPJPY | 45 | 35 | 10 |
| USDZAR | 10 | 70 | 10 |
| USDTRY | 50 | 70 | 10 |

---

## Caveats and Limitations

1. **Hourly bar resolution**: IB paper accounts only provide 1-hour bars for
   historical forex data. Intra-hour price paths cannot be observed. When both
   TP and SL could be hit in the same bar, SL is assumed first (pessimistic).
   Results may improve with finer granularity (live account with 1-min data).

2. **Small sample size**: ~48 events over 18 months. Bootstrap CIs account for
   sampling uncertainty, but structural regime changes (e.g., shift from
   tightening to easing) are not captured.

3. **Spread approximation**: Event-time spreads are modeled as fixed estimates.
   Actual spreads vary by broker, time, and event magnitude. Exotic pairs
   (USDZAR, USDTRY) spreads can exceed 50 pips during NFP.

4. **Slippage not modeled**: Stop orders can gap through during fast markets.
   Actual fills may be worse than simulated, especially for the straddle entry.

5. **No OCA modeling**: Both straddle legs can trigger independently. In the
   worst case (whipsaw), both legs trigger and both stop out. This is modeled
   accurately — it contributes to the tail risk in CVaR.

6. **Multiple testing**: Grid search over ~500 parameter combinations inflates
   the chance of finding spuriously good parameters. Walk-forward validation
   is the primary guard against this, but with only ~6 months of test data,
   out-of-sample results have wide confidence intervals.

7. **FOMC has different dynamics**: Rate decisions move markets differently from
   data releases (NFP/CPI). The optimal straddle parameters may differ for FOMC.
   Consider splitting the analysis by event type for production use.
