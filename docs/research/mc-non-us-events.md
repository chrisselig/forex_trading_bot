# Monte Carlo Optimization — Non-US Events (Canada & Japan)

**Date**: June 10, 2026
**Script**: `scripts/mc_non_us.py`
**Data source**: Dukascopy Bank SA (1-minute OHLCV, bid-side)

## Executive Summary

- **Analysis period**: January 2020 — June 2026 (6.5 years)
- **Total events analyzed**: 321
- **USDCAD**: 203 events (BOC Rate Decision: 48, Canada CPI: 77, Canada Employment: 78)
- **USDJPY**: 118 events (BOJ Rate Decision: 41, Japan CPI: 77)
- **Grid**: 540 parameter combinations (distance 10-50, TP 15-70, SL 10-30 pips)
- **Bootstrap**: 10,000 resamples, 95% confidence intervals
- **Walk-forward**: Train 2020-2024 (5 years), test 2025-2026 (18 months)
- **Runtime**: 508 seconds (~8.5 minutes)

This is the first analysis of non-US economic events. The question: can the straddle strategy profit on a pair's *own country's* events, even if that pair failed walk-forward on US events?

### Bottom Line

Neither pair passes the full validation criteria (CI above zero **and** positive walk-forward). **USDJPY on BOJ events is the most promising new candidate** — it passes walk-forward convincingly but the confidence interval barely touches zero. USDCAD fails on Canadian events just as it did on US events.

## Optimal Parameters by Pair

| Pair | Distance | TP | SL | E[P&L] | 95% CI | Win Rate | Sharpe | Profit Factor | CVaR(5%) | N |
|------|----------|----|----|--------|--------|----------|--------|---------------|----------|---|
| **USDCAD** | 20 | 50 | 10 | +1.0 | [-2.0, +4.3] | 36.5% | 0.57 | 1.17 | -10.0 | 104 |
| **USDJPY** | 25 | 15 | 15 | +2.5 | [-0.3, +5.3] | 59.6% | 1.79 | 1.44 | -15.0 | 99 |

!!! info "Reading the table"
    See the [Glossary](../trading/glossary.md) for definitions of all metrics. E[P&L] is expected profit per trade in pips. The 95% CI is the confidence interval — if it excludes zero, we have statistical evidence the strategy is profitable.

## Performance by Event Type

### USDCAD — Params: 20/50/10

| Event | E[P&L] | 95% CI | Win Rate | Sharpe | Profit Factor | N |
|-------|--------|--------|----------|--------|---------------|---|
| BOC Rate Decision | -0.1 | [-4.4, +4.6] | 36.0% | -0.11 | 0.99 | 25 |
| Canada CPI | +0.2 | [-5.1, +6.3] | 29.3% | -0.10 | 1.03 | 41 |
| Canada Employment | +2.5 | [-2.0, +7.8] | 44.7% | 0.96 | 1.53 | 38 |

!!! warning "All three Canadian event types are flat"
    No individual event type shows a statistically significant edge. Canada Employment is the most promising (+2.5 pips) but the CI spans zero. BOC Rate Decision and Canada CPI are essentially break-even after spreads.

### USDJPY — Params: 25/15/15

| Event | E[P&L] | 95% CI | Win Rate | Sharpe | Profit Factor | N |
|-------|--------|--------|----------|--------|---------------|---|
| BOJ Rate Decision | +3.4 | [-0.7, +7.4] | 62.2% | 1.68 | 1.64 | 45 |
| Japan CPI | +1.8 | [-2.1, +5.6] | 57.4% | 0.94 | 1.29 | 54 |

!!! info "BOJ Rate is the stronger event"
    BOJ Rate decisions produce E[P&L] = +3.4 with a 62% win rate — the highest per-event win rate in the entire analysis. Japan CPI is weaker (+1.8) and adds noise. The edge, if real, is driven by BOJ decisions.

## Walk-Forward Validation

Train on 2020-2024 (5 years), test on 2025-2026 (18 months).

| Pair | Params | IS E[P&L] | IS Sharpe | IS N | OOS E[P&L] | OOS Sharpe | OOS N |
|------|--------|-----------|-----------|------|------------|------------|-------|
| **USDCAD** | 40/30/30 | +6.5 | 1.94 | 24 | -10.6 | -2.87 | 6 |
| **USDJPY** | 25/15/15 | +1.4 | 0.89 | 77 | **+6.4** | **2.45** | 22 |

!!! failure "USDCAD fails walk-forward"
    The optimizer chose aggressive params (40/30/30) that worked in-sample but collapsed out-of-sample. Only 6 OOS trades with E[P&L] = -10.6. Classic overfitting signature — same story as US events.

!!! success "USDJPY passes walk-forward"
    **Same 25/15/15 parameters** in-sample and full-sample. OOS E[P&L] = +6.4 with Sharpe 2.45 across 22 trades. This is the most convincing walk-forward result for any new pair — the edge actually *improves* out-of-sample.

    However, the full-sample CI [-0.3, +5.3] barely touches zero, so we cannot confirm this edge at the 95% confidence level. At ~90% confidence, it would pass.

## Risk Analysis

### USDCAD

- **Reward:Risk ratio**: 5.0:1 (TP=50 / SL=10)
- **Breakeven win rate**: 16.7% (actual: 36.5%)
- **Edge**: +19.9 percentage points above breakeven
- **Median max drawdown**: 130 pips
- **95th percentile max drawdown**: 257 pips
- **Walk-forward**: FAILS (OOS E[P&L] = -10.6)
- **Verdict**: Do not trade. The high R:R and above-breakeven win rate look attractive, but the CI spans zero and walk-forward collapses. USDCAD doesn't straddle well on any events.

### USDJPY

- **Reward:Risk ratio**: 1.0:1 (TP=15 / SL=15)
- **Breakeven win rate**: 50.0% (actual: 59.6%)
- **Edge**: +9.6 percentage points above breakeven
- **Median max drawdown**: 90 pips
- **95th percentile max drawdown**: 170 pips
- **Walk-forward**: PASSES (OOS E[P&L] = +6.4, Sharpe 2.45)
- **Verdict**: **Monitor on paper trading.** The walk-forward is strong but the CI barely touches zero. If the edge persists through 2026 H2, it would cross the significance threshold.

## Comparison with US Event Analysis

| Pair | US Events Result | Non-US Events Result |
|------|-----------------|---------------------|
| **USDZAR** | **Best pair** — E[P&L]=+17.1, Sharpe 6.40, WF passes | Not tested (SARB/SA CPI analysis pending) |
| **USDTRY** | **Most consistent** — E[P&L]=+13.6, Sharpe 6.51, WF passes | Not tested (TCMB analysis pending) |
| **USDCAD** | Fails (CI spans zero, WF OOS=-14.3) | **Fails again** (CI spans zero, WF OOS=-10.6) |
| **USDJPY** | Not tested on US events | **Promising** — WF passes but CI borderline |
| **GBPUSD** | Below breakeven, WF fails | Not tested |

The exotic pairs on US events remain far superior. USDJPY on BOJ events is the best new-pair candidate but not yet production-ready.

## What's Next

1. **Paper-trade USDJPY**: Run the straddle with 25/15/15 params on BOJ Rate decisions. Accumulate live data through 2026 H2.
2. **SARB/TCMB analysis**: Download South Africa and Turkey event data and run the same analysis. These pairs are already profitable on US events — domestic events could add 14-20 more trading days per year.
3. **Re-evaluate in 6 months**: By end of 2026, USDJPY will have ~10 more BOJ events. If the edge holds, the CI should clear zero.

## Caveats

1. **Different volatility dynamics**: Canadian and Japanese events move their respective pairs differently than US events. BOC decisions can produce sharp but short-lived moves; BOJ decisions since 2022 (YCC changes) have been extremely volatile.

2. **Timing differences**: BOJ announces ~12 PM JST (overnight for North America). Liquidity is lower during Asian hours. Canada events are during normal NA hours.

3. **Spread approximation**: Event-time spreads are fixed estimates. BOJ surprises can blow out USDJPY spreads to 10+ pips. The 2-pip estimate used here may be optimistic for BOJ events.

4. **1:1 R:R structure**: USDJPY's optimal 25/15/15 (1:1 R:R) is fundamentally different from the exotic pairs' 50/70/10 (7:1 R:R). The 1:1 structure depends on a high win rate (>50%), making it more sensitive to spread and slippage.

5. **BOJ announcement timing is imprecise**: Unlike NFP/CPI (exactly 8:30 AM ET), BOJ announcements come "after the meeting concludes" — anywhere from 11:30 AM to 1:00 PM JST. The straddle's 30-minute pre-event window may not align perfectly.
