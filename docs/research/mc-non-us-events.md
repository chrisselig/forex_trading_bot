# Monte Carlo Optimization — Non-US Events

**Date**: June 10, 2026
**Script**: `scripts/mc_non_us.py`
**Data source**: Dukascopy Bank SA (1-minute OHLCV, bid-side)

## Executive Summary

- **Analysis period**: January 2020 — June 2026 (6.5 years)
- **Total events analyzed**: 510
- **USDCAD**: 203 events (BOC Rate Decision: 48, Canada CPI: 77, Canada Employment: 78)
- **USDJPY**: 118 events (BOJ Rate Decision: 41, Japan CPI: 77)
- **USDZAR**: 117 events (SARB Rate Decision: 40, South Africa CPI: 77)
- **USDTRY**: 72 events (TCMB Rate Decision: 72)
- **Grid**: 540 parameter combinations (distance 10-50, TP 15-70, SL 10-30 pips)
- **Bootstrap**: 10,000 resamples, 95% confidence intervals
- **Walk-forward**: Train 2020-2024 (5 years), test 2025-2026 (18 months)

This analysis tests whether the straddle strategy profits on a pair's *own country's* events, even if that pair failed walk-forward on US events.

### Bottom Line

**USDZAR and USDTRY pass on their domestic events** — both with CI entirely above zero and positive walk-forward. These pairs can now trade on domestic events in addition to US events, adding ~22-26 trading days per year. **USDJPY on BOJ events is promising but borderline.** USDCAD fails on Canadian events just as it did on US events.

## Optimal Parameters by Pair

| Pair | Distance | TP | SL | E[P&L] | 95% CI | Win Rate | Sharpe | Profit Factor | CVaR(5%) | N |
|------|----------|----|----|--------|--------|----------|--------|---------------|----------|---|
| **USDZAR** | 50 | 70 | 10 | +17.3 | [+12.5, +22.4] | 34.1% | 6.75 | 3.62 | -10.0 | 220 |
| **USDTRY** | 20 | 60 | 10 | +10.5 | [+5.2, +16.2] | 29.5% | 3.63 | 2.49 | -10.0 | 122 |
| **USDJPY** | 25 | 15 | 15 | +2.5 | [-0.3, +5.3] | 59.6% | 1.79 | 1.44 | -15.0 | 99 |
| **USDCAD** | 20 | 50 | 10 | +1.0 | [-2.0, +4.3] | 36.5% | 0.57 | 1.17 | -10.0 | 104 |

!!! info "Reading the table"
    See the [Glossary](../trading/glossary.md) for definitions of all metrics. E[P&L] is expected profit per trade in pips. The 95% CI is the confidence interval — if it excludes zero, we have statistical evidence the strategy is profitable.

## Performance by Event Type

### USDZAR — Params: 50/70/10

| Event | E[P&L] | 95% CI | Win Rate | Sharpe | Profit Factor | N |
|-------|--------|--------|----------|--------|---------------|---|
| SARB Rate Decision | +16.3 | [+7.9, +24.7] | 32.9% | 3.76 | 3.43 | 76 |
| South Africa CPI | +17.8 | [+11.7, +23.9] | 34.7% | 5.59 | 3.72 | 144 |

!!! success "Both South African event types are independently profitable"
    SARB Rate and SA CPI both have CIs entirely above zero. SA CPI is slightly stronger (+17.8 vs +16.3) with a higher Sharpe (5.59 vs 3.76). These are comparable to USDZAR's US event performance (+17.1).

### USDTRY — Params: 20/60/10

| Event | E[P&L] | 95% CI | Win Rate | Sharpe | Profit Factor | N |
|-------|--------|--------|----------|--------|---------------|---|
| TCMB Rate Decision | +10.5 | [+5.2, +16.2] | 29.5% | 3.63 | 2.49 | 122 |

!!! success "TCMB passes with different optimal params"
    TCMB's optimal params (20/60/10) differ from USDTRY's US event params (50/70/10) — tighter distance (20 vs 50) and lower TP (60 vs 70). This suggests TCMB events produce quicker, more contained moves than US events on USDTRY. **Per-event-source parameter overrides** will be needed in `config/settings.yaml`.

### USDJPY — Params: 25/15/15

| Event | E[P&L] | 95% CI | Win Rate | Sharpe | Profit Factor | N |
|-------|--------|--------|----------|--------|---------------|---|
| BOJ Rate Decision | +3.4 | [-0.7, +7.4] | 62.2% | 1.68 | 1.64 | 45 |
| Japan CPI | +1.8 | [-2.1, +5.6] | 57.4% | 0.94 | 1.29 | 54 |

!!! info "BOJ Rate is the stronger event"
    BOJ Rate decisions produce E[P&L] = +3.4 with a 62% win rate — the highest per-event win rate in the entire analysis. Japan CPI is weaker (+1.8) and adds noise. The edge, if real, is driven by BOJ decisions.

### USDCAD — Params: 20/50/10

| Event | E[P&L] | 95% CI | Win Rate | Sharpe | Profit Factor | N |
|-------|--------|--------|----------|--------|---------------|---|
| BOC Rate Decision | -0.1 | [-4.4, +4.6] | 36.0% | -0.11 | 0.99 | 25 |
| Canada CPI | +0.2 | [-5.1, +6.3] | 29.3% | -0.10 | 1.03 | 41 |
| Canada Employment | +2.5 | [-2.0, +7.8] | 44.7% | 0.96 | 1.53 | 38 |

!!! warning "All three Canadian event types are flat"
    No individual event type shows a statistically significant edge. Canada Employment is the most promising (+2.5 pips) but the CI spans zero. BOC Rate Decision and Canada CPI are essentially break-even after spreads.

## Walk-Forward Validation

Train on 2020-2024 (5 years), test on 2025-2026 (18 months).

| Pair | Params | IS E[P&L] | IS Sharpe | IS N | OOS E[P&L] | OOS Sharpe | OOS N |
|------|--------|-----------|-----------|------|------------|------------|-------|
| **USDZAR** | 50/70/10 | +19.8 | 6.69 | 172 | **+8.3** | **1.64** | 48 |
| **USDTRY** | 20/60/10 | +9.7 | 3.10 | 103 | **+14.8** | **1.91** | 19 |
| **USDJPY** | 25/15/15 | +1.4 | 0.89 | 77 | **+6.4** | **2.45** | 22 |
| **USDCAD** | 40/30/30 | +6.5 | 1.94 | 24 | -10.6 | -2.87 | 6 |

!!! success "USDZAR passes walk-forward on domestic events"
    Same 50/70/10 params as US events. OOS E[P&L] = +8.3 with Sharpe 1.64 across 48 trades. The strategy works on SARB and SA CPI events just as well as on US events — **no parameter changes needed**.

!!! success "USDTRY passes walk-forward on TCMB events"
    OOS E[P&L] = +14.8 with Sharpe 1.91 across 19 trades — OOS actually *improves* over in-sample. Note the different optimal params (20/60/10 vs 50/70/10 for US events), requiring per-event-source overrides.

!!! success "USDJPY passes walk-forward"
    **Same 25/15/15 parameters** in-sample and full-sample. OOS E[P&L] = +6.4 with Sharpe 2.45 across 22 trades. This is the most convincing walk-forward result for any new pair — the edge actually *improves* out-of-sample.

    However, the full-sample CI [-0.3, +5.3] barely touches zero, so we cannot confirm this edge at the 95% confidence level. At ~90% confidence, it would pass.

!!! failure "USDCAD fails walk-forward"
    The optimizer chose aggressive params (40/30/30) that worked in-sample but collapsed out-of-sample. Only 6 OOS trades with E[P&L] = -10.6. Classic overfitting signature — same story as US events.

## Risk Analysis

### USDZAR

- **Reward:Risk ratio**: 7.0:1 (TP=70 / SL=10)
- **Breakeven win rate**: 12.5% (actual: 34.1%)
- **Edge**: +21.6 percentage points above breakeven
- **Median max drawdown**: 110 pips
- **95th percentile max drawdown**: 170 pips
- **Walk-forward**: PASSES (OOS E[P&L] = +8.3, Sharpe 1.64)
- **Verdict**: **Recommended for production.** Same params as US events (50/70/10). CI entirely above zero. Add SARB Rate and SA CPI to the event calendar — adds ~14 trading days/year.

### USDTRY

- **Reward:Risk ratio**: 6.0:1 (TP=60 / SL=10)
- **Breakeven win rate**: 14.3% (actual: 29.5%)
- **Edge**: +15.2 percentage points above breakeven
- **Median max drawdown**: 110 pips
- **95th percentile max drawdown**: 190 pips
- **Walk-forward**: PASSES (OOS E[P&L] = +14.8, Sharpe 1.91)
- **Verdict**: **Recommended for production.** Different params from US events (20/60/10 vs 50/70/10) — requires per-event-source overrides. CI entirely above zero. Add TCMB Rate to the event calendar — adds ~8-12 trading days/year.

### USDJPY

- **Reward:Risk ratio**: 1.0:1 (TP=15 / SL=15)
- **Breakeven win rate**: 50.0% (actual: 59.6%)
- **Edge**: +9.6 percentage points above breakeven
- **Median max drawdown**: 90 pips
- **95th percentile max drawdown**: 170 pips
- **Walk-forward**: PASSES (OOS E[P&L] = +6.4, Sharpe 2.45)
- **Verdict**: **Monitor on paper trading.** The walk-forward is strong but the CI barely touches zero. If the edge persists through 2026 H2, it would cross the significance threshold.

### USDCAD

- **Reward:Risk ratio**: 5.0:1 (TP=50 / SL=10)
- **Breakeven win rate**: 16.7% (actual: 36.5%)
- **Edge**: +19.9 percentage points above breakeven
- **Median max drawdown**: 130 pips
- **95th percentile max drawdown**: 257 pips
- **Walk-forward**: FAILS (OOS E[P&L] = -10.6)
- **Verdict**: Do not trade. The high R:R and above-breakeven win rate look attractive, but the CI spans zero and walk-forward collapses. USDCAD doesn't straddle well on any events.

## Comparison with US Event Analysis

| Pair | US Events Result | Non-US Events Result |
|------|-----------------|---------------------|
| **USDZAR** | **Best pair** — E[P&L]=+17.1, Sharpe 6.40, WF passes | **PASSES** — E[P&L]=+17.3, Sharpe 6.75, same 50/70/10 params |
| **USDTRY** | **Most consistent** — E[P&L]=+13.6, Sharpe 6.51, WF passes | **PASSES** — E[P&L]=+10.5, Sharpe 3.63, different params (20/60/10) |
| **USDCAD** | Fails (CI spans zero, WF OOS=-14.3) | **Fails again** (CI spans zero, WF OOS=-10.6) |
| **USDJPY** | Not tested on US events | **Promising** — WF passes but CI borderline |
| **GBPUSD** | Below breakeven, WF fails | Not tested |

The exotic pairs are profitable on both US and domestic events. USDZAR uses the same params for both; USDTRY needs different params for TCMB events.

## What's Next

1. **Enable SARB/SA CPI events**: Add to `config/settings.yaml` and event calendar for USDZAR. Same 50/70/10 params — no config changes needed beyond adding event dates.
2. **Enable TCMB events**: Add to `config/settings.yaml` for USDTRY with per-event-source overrides (20/60/10 for TCMB vs 50/70/10 for US events).
3. **Paper-trade USDJPY**: Run the straddle with 25/15/15 params on BOJ Rate decisions. Accumulate live data through 2026 H2.
4. **Re-evaluate USDJPY in 6 months**: By end of 2026, USDJPY will have ~10 more BOJ events. If the edge holds, the CI should clear zero.

## Caveats

1. **Different volatility dynamics**: Canadian and Japanese events move their respective pairs differently than US events. BOC decisions can produce sharp but short-lived moves; BOJ decisions since 2022 (YCC changes) have been extremely volatile.

2. **Timing differences**: BOJ announces ~12 PM JST (overnight for North America). Liquidity is lower during Asian hours. SARB announces ~3 PM SAST (9 AM ET). Canada events are during normal NA hours.

3. **Spread approximation**: Event-time spreads are fixed estimates. BOJ surprises can blow out USDJPY spreads to 10+ pips. The 2-pip estimate used here may be optimistic for BOJ events. USDZAR and USDTRY spreads (25 and 30 pips) may widen further during domestic events.

4. **USDTRY parameter divergence**: TCMB optimal params (20/60/10) differ from US event params (50/70/10). This means USDTRY needs per-event-source configuration. The tighter distance (20 vs 50) suggests TCMB moves are faster and more contained.

5. **1:1 R:R structure for USDJPY**: USDJPY's optimal 25/15/15 (1:1 R:R) is fundamentally different from the exotic pairs' 7:1 R:R. The 1:1 structure depends on a high win rate (>50%), making it more sensitive to spread and slippage.

6. **BOJ announcement timing is imprecise**: Unlike NFP/CPI (exactly 8:30 AM ET), BOJ announcements come "after the meeting concludes" — anywhere from 11:30 AM to 1:00 PM JST. The straddle's 30-minute pre-event window may not align perfectly.
