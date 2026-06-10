# Monte Carlo — EURUSD & AUDUSD on US Events (Jan 2020 — Jun 2026)

!!! failure "Result: Neither pair is tradeable"
    Both EURUSD and AUDUSD fail the straddle strategy on US news events. EURUSD CI spans zero and walk-forward collapses (OOS = -2.0). AUDUSD has too few triggered trades (N=19) at optimal params to draw conclusions. **Do not enable either pair for production.**

**Date**: June 10, 2026
**Script**: `scripts/monte_carlo_dukascopy.py --pairs EURUSD AUDUSD`
**Data source**: Dukascopy Bank SA (1-minute OHLCV, bid-side)

## Executive Summary

- **Analysis period**: January 2020 — June 2026
- **Events analyzed**: 207 (NFP: 78, CPI: 77, FOMC: 52)
- **Data points loaded**: 408 (event x pair combinations)
- **Pairs**: EURUSD, AUDUSD
- **Data source**: Dukascopy Bank SA (1-minute OHLCV bars)
- **Monte Carlo iterations**: 10,000
- **Confidence level**: 95%

### Methodology

1. Loaded 1-minute bars from Dukascopy for a 6-hour window around each event (-2h / +4h)
2. Simulated straddle mechanics (buy stop + sell stop, each with TP/SL) using 1-min OHLC
3. Grid search over distance (10-50), TP (15-70), SL (10-30) — all in pips
4. Bootstrap resampled 10,000x to build confidence intervals
5. Scored on pessimistic metric: lower bound of 95% CI on mean P&L
6. Bonferroni correction applied: CIs widened for the number of pairs tested simultaneously
7. Walk-forward validation: train on 2020-2024, test on 2025-2026
8. Spread modeled as fixed cost (conservative event-time estimates)

### Improvement over hourly data

The previous optimization used 1-hour bars from IB paper accounts. When both TP
and SL could be hit within the same hourly bar, SL was assumed first (pessimistic).
With 1-minute bars, we can observe the actual price sequence and determine which
level was hit first. This removes the systematic negative bias in the old results.

---

## Optimal Parameters by Pair

| Pair | Distance | TP | SL | E[P&L] | 95% CI | Bonferroni CI | Win Rate | Sharpe | PF | N |
|------|----------|----|----|--------|--------|---------------|----------|--------|----|---|
| **EURUSD** | 10 | 20 | 10 | +0.4 | [-1.3, +2.1] | [-1.5, +2.4] | 41.1% | 0.45 | 1.08 | 185 |
| **AUDUSD** | 40 | 15 | 20 | +4.8 | [-0.4, +9.5] | [-1.1, +10.1] | 68.4% | 2.13 | 2.86 | 19 |

---

## Walk-Forward Validation

Train on 2020-2024 data (5 years), test on 2025-2026 data (18 months).

| Pair | Params | In-Sample E[P&L] | In-Sample Sharpe | Out-of-Sample E[P&L] | Out-of-Sample Sharpe |
|------|--------|-------------------|------------------|----------------------|----------------------|
| **EURUSD** | 10/20/10 | +1.0 | 1.05 | -2.0 | -1.18 |
| **AUDUSD** | 40/15/20 | +5.5 | 2.45 | +1.3 | 1.51 |

---

## Risk Analysis at Optimal Parameters

### EURUSD

- **Reward:Risk ratio**: 2.0:1 (TP=20 / SL=10)
- **Breakeven win rate**: 33.3% (actual: 41.1%)
- **Edge**: +7.7 percentage points above breakeven
- **Median max drawdown**: 143 pips
- **95th percentile max drawdown**: 290 pips
- **Worst 5% average trade**: -10.0 pips

### AUDUSD

- **Reward:Risk ratio**: 0.8:1 (TP=15 / SL=20)
- **Breakeven win rate**: 57.1% (actual: 68.4%)
- **Edge**: +11.3 percentage points above breakeven
- **Median max drawdown**: 22 pips
- **95th percentile max drawdown**: 55 pips
- **Worst 5% average trade**: -20.0 pips

---

## Recommended Settings

```yaml
strategy:
  straddle_distance_pips: 10
  straddle_tp_pips: 20
  straddle_sl_pips: 10
```

### Per-pair overrides:

| Pair | Distance | TP | SL |
|------|----------|----|----|
| EURUSD | 10 | 20 | 10 |
| AUDUSD | 40 | 15 | 20 |

---

## Caveats

1. **Regime changes**: 6.5 years spans COVID (2020), rate hikes (2022-2023),
   and normalization (2024-2026). Parameters optimized across all regimes may
   not be optimal for any single regime.

2. **Spread approximation**: Event-time spreads are fixed estimates. Exotic
   pairs (USDZAR, USDTRY) can exceed 50 pips during NFP.

3. **Slippage not modeled**: Stop orders can gap through during fast markets.

4. **Bid-side data only**: Dukascopy data is bid OHLCV. The ask side is
   approximated via the spread adjustment.

5. **Multiple testing**: Grid search over ~540 combos across N pairs inflates false
   positives. Bonferroni correction adjusts CIs by the number of pairs tested.
   Walk-forward validation provides an additional out-of-sample guard.

6. **FOMC dynamics differ**: Rate decisions move differently from data releases.
