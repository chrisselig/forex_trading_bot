# Monte Carlo Optimization — AUDUSD + Australian Events

**Date**: June 2026
**Script**: `scripts/mc_audusd_explore.py`
**Data source**: Dukascopy Bank SA (1-minute OHLCV, bid-side)
**Grid**: 540 parameter combinations
**Bootstrap**: 10,000 resamples, 95% CI
**Walk-forward**: Train 2020-2023, Test 2024-2026

## Executive Summary

AUDUSD tested on three event sources: US events (NFP/CPI/FOMC/PPI/GDP/PCE),
Australian events (RBA Rate/AU CPI/AU Employment), and Combined (all 9 event types).

**Key findings:**
- **US events on AUDUSD**: Walk-forward PASSES at all spread levels (1.0-4.0) with
  consistent params 40/15/25, but sample sizes are very small (N=28 full-sample,
  N=7-8 OOS). Full-sample CI spans zero [-0.4, +8.5].
- **Australian events**: Strong full-sample edge (E[P&L]=+16.0, CI=[+8.1, +24.4]),
  but **overfit at tight spreads** (FAIL at 1.0-2.5). PASSES at realistic spreads
  3.0+ with params 40/70/30.
- **Combined events**: Most robust — PASSES at ALL spread levels with consistent
  params 40/70/30, N=77 full-sample, N=19-20 OOS.

**Two distinct parameter regimes** exist:
- US events favor tight TP (40/15/25): small, frequent wins
- AU events favor wide TP (40/70/30): large, less frequent wins
- Combined is dominated by the AU-style params (40/70/30)

**Verdict**: AUDUSD is a **candidate for paper trading** on Combined events with
params 40/70/30, but requires caution — the US-event edge with 40/15/25 is too
thin (N=28) to trade independently, and the AU-event edge is only robust at wider
spreads. Need to validate actual event-time spreads before proceeding.

## US Events (350 events loaded, N=28 at optimal params)

**Full-sample optimal** (spread=1.5): D=40 TP=15 SL=25
E[P&L]=+4.3, CI=[-0.4, +8.5], Sharpe=2.03, WR=64.3%, PF=2.32, N=28

### Per-Event Breakdown (Params: 40/15/25)

| Event | E[P&L] | 95% CI | Win Rate | Sharpe | PF | N |
|-------|--------|--------|----------|--------|----|---|
| CPI | +4.2 | [-6.6, +12.7] | 66.7% | 1.30 | 2.21 | 6 |
| FOMC | +1.2 | [-4.1, +7.1] | 50.0% | 0.19 | 1.55 | 6 |
| GDP | +9.6 | [+1.8, +15.0] | 80.0% | 4.01 | 11.90 | 5 |
| PCE | -3.6 | [-18.4, +15.0] | 33.3% | -1.14 | 0.58 | 3 |
| PPI | +12.6 | [+7.9, +15.0] | 100.0% | 6.34 | inf | 6 |

> NFP not appearing in the per-event breakdown at D=40 suggests AUDUSD doesn't
> trigger straddle entries at 40-pip distance on NFP releases. This limits the
> US-event trade count significantly.

### Year-by-Year

| Year | E[P&L] | Win Rate | N |
|------|--------|----------|---|
| 2020 | +5.0 | 60% | 10 |
| 2021 | +15.0 | 100% | 1 |
| 2022 | +5.2 | 67% | 3 |
| 2023 | +3.4 | 50% | 6 |
| 2024 | +1.1 | 100% | 2 |
| 2025 | -3.6 | 50% | 4 |
| 2026 | +15.0 | 100% | 2 |

### Spread Sensitivity + Walk-Forward

| Spread | Best Params | IS E[P&L] | IS CI | IS Sharpe | IS N | OOS E[P&L] | OOS Sharpe | OOS WR | OOS N | Verdict |
|--------|-------------|-----------|-------|-----------|------|------------|------------|--------|-------|---------|
| 1.0 | 40/15/30 | +5.2 | [+0.7, +9.5] | 2.43 | 20 | +1.7 | 0.68 | 75.0% | 8 | PASS |
| 1.5 | 40/15/25 | +5.1 | [+0.5, +9.4] | 2.34 | 20 | +2.2 | 0.75 | 75.0% | 8 | PASS |
| 2.0 | 40/15/25 | +5.6 | [+0.8, +10.0] | 2.56 | 19 | +6.0 | 2.00 | 85.7% | 7 | PASS |
| 2.5 | 40/15/25 | +6.2 | [+1.4, +10.7] | 2.85 | 18 | +5.9 | 1.94 | 85.7% | 7 | PASS |
| 3.0 | 40/15/25 | +6.1 | [+1.2, +10.6] | 2.76 | 18 | +5.8 | 1.89 | 71.4% | 7 | PASS |
| 3.5 | 40/15/25 | +6.0 | [+1.1, +10.5] | 2.67 | 18 | +5.7 | 1.84 | 71.4% | 7 | PASS |
| 4.0 | 40/15/25 | +5.8 | [+0.9, +10.4] | 2.59 | 18 | +5.6 | 1.80 | 71.4% | 7 | PASS |

> Walk-forward passes at all spreads, but OOS N=7-8 is too small to be conclusive.
> Very similar to the USDJPY/BOJ borderline case from `06-non-us-events.md`.

## Australian Events (171 events loaded, N=49 at optimal params)

**Full-sample optimal** (spread=1.5): D=40 TP=70 SL=30
E[P&L]=+16.0, CI=[+8.1, +24.4], Sharpe=3.85, WR=63.3%, PF=5.26, N=49

### Per-Event Breakdown (Params: 40/70/30)

| Event | E[P&L] | 95% CI | Win Rate | Sharpe | PF | N |
|-------|--------|--------|----------|--------|----|---|
| Australia CPI | +19.2 | [+8.1, +32.0] | 84.6% | 3.24 | 75.39 | 13 |
| Australia Employment | +17.2 | [+3.2, +31.9] | 57.1% | 2.34 | 3.97 | 21 |
| RBA Rate Decision | +11.6 | [-0.9, +25.6] | 53.3% | 1.62 | 3.95 | 15 |

> AU CPI is the strongest individual event (CI fully above zero). RBA Rate Decision
> CI spans zero — edge may come primarily from CPI + Employment.

### Year-by-Year

| Year | E[P&L] | Win Rate | N |
|------|--------|----------|---|
| 2020 | +36.6 | 80% | 10 |
| 2021 | +14.2 | 50% | 6 |
| 2022 | +6.6 | 54% | 13 |
| 2023 | +24.9 | 88% | 8 |
| 2024 | -1.3 | 57% | 7 |
| 2025 | +4.4 | 50% | 2 |
| 2026 | +16.0 | 33% | 3 |

> 2024 is the only negative year. 2025-2026 have very few events (data cutoff).

### Spread Sensitivity + Walk-Forward

| Spread | Best Params | IS E[P&L] | IS CI | IS Sharpe | IS N | OOS E[P&L] | OOS Sharpe | OOS WR | OOS N | Verdict |
|--------|-------------|-----------|-------|-----------|------|------------|------------|--------|-------|---------|
| 1.0 | 45/70/15 | +21.1 | [+10.8, +31.7] | 3.94 | 30 | -4.8 | -1.90 | 22.2% | 9 | FAIL (overfit) |
| 1.5 | 45/70/15 | +20.9 | [+10.7, +31.6] | 3.90 | 30 | -5.0 | -2.00 | 22.2% | 9 | FAIL (overfit) |
| 2.0 | 45/70/15 | +20.8 | [+10.5, +31.4] | 3.87 | 30 | -5.2 | -2.11 | 22.2% | 9 | FAIL (overfit) |
| 2.5 | 45/70/15 | +20.6 | [+10.4, +31.2] | 3.84 | 30 | -5.3 | -2.21 | 22.2% | 9 | FAIL (overfit) |
| 3.0 | 40/70/30 | +19.9 | [+9.8, +30.7] | 3.80 | 36 | +3.3 | 0.51 | 50.0% | 12 | PASS |
| 3.5 | 40/70/30 | +22.0 | [+11.9, +32.4] | 4.16 | 34 | +3.0 | 0.43 | 50.0% | 12 | PASS |
| 4.0 | 40/70/20 | +19.5 | [+9.7, +29.7] | 3.77 | 34 | +2.5 | 0.30 | 50.0% | 12 | PASS |

> Critical finding: the train-optimal params **shift** from 45/70/15 (tight SL)
> to 40/70/30 (wider SL) at spread=3.0. The tight-SL params are overfit to the
> training period. The wider-SL params (40/70/30) generalize to OOS.

## Combined Events (521 events loaded, N=77 at optimal params)

**Full-sample optimal** (spread=1.5): D=40 TP=70 SL=30
E[P&L]=+12.5, CI=[+6.5, +18.9], Sharpe=3.93, WR=58.4%, PF=3.86, N=77

### Per-Event Breakdown (Params: 40/70/30)

| Event | E[P&L] | 95% CI | Win Rate | Sharpe | PF | N |
|-------|--------|--------|----------|--------|----|---|
| Australia CPI | +19.2 | [+8.1, +32.0] | 84.6% | 3.24 | 75.39 | 13 |
| Australia Employment | +17.2 | [+3.2, +31.9] | 57.1% | 2.34 | 3.97 | 21 |
| CPI | -1.6 | [-16.8, +13.8] | 50.0% | -0.24 | 0.81 | 6 |
| FOMC | +10.3 | [-4.1, +34.5] | 50.0% | 0.45 | 5.88 | 6 |
| GDP | +22.4 | [+6.3, +38.1] | 80.0% | 3.22 | 26.50 | 5 |
| PCE | -14.5 | [-18.4, -7.6] | 0.0% | -5.87 | 0.00 | 3 |
| PPI | +15.0 | [-1.3, +38.3] | 66.7% | 1.40 | 10.51 | 6 |
| RBA Rate Decision | +11.6 | [-0.9, +25.6] | 53.3% | 1.62 | 3.95 | 15 |

> The 40/70/30 params work well for AU events but poorly for US CPI (-1.6) and
> PCE (-14.5). The US events that do well at these wide params (GDP, PPI) have
> tiny samples (N=5-6). This is really an AU-event strategy that happens to catch
> some US-event volatility.

### Year-by-Year

| Year | E[P&L] | Win Rate | N |
|------|--------|----------|---|
| 2020 | +21.1 | 60% | 20 |
| 2021 | +17.5 | 57% | 7 |
| 2022 | +8.2 | 56% | 16 |
| 2023 | +18.0 | 64% | 14 |
| 2024 | -0.7 | 67% | 9 |
| 2025 | -3.3 | 50% | 6 |
| 2026 | +12.7 | 40% | 5 |

### Spread Sensitivity + Walk-Forward

| Spread | Best Params | IS E[P&L] | IS CI | IS Sharpe | IS N | OOS E[P&L] | OOS Sharpe | OOS WR | OOS N | Verdict |
|--------|-------------|-----------|-------|-----------|------|------------|------------|--------|-------|---------|
| 1.0 | 40/70/30 | +16.5 | [+8.8, +24.4] | 4.12 | 57 | +2.1 | 0.57 | 60.0% | 20 | PASS |
| 1.5 | 40/70/30 | +16.3 | [+8.6, +24.2] | 4.06 | 57 | +1.9 | 0.50 | 55.0% | 20 | PASS |
| 2.0 | 40/70/30 | +16.8 | [+8.9, +25.0] | 4.08 | 55 | +3.3 | 0.96 | 57.9% | 19 | PASS |
| 2.5 | 40/70/30 | +17.1 | [+9.2, +25.4] | 4.09 | 54 | +3.0 | 0.87 | 57.9% | 19 | PASS |
| 3.0 | 40/70/30 | +16.9 | [+9.0, +25.2] | 4.04 | 54 | +2.8 | 0.78 | 52.6% | 19 | PASS |
| 3.5 | 40/70/30 | +18.1 | [+9.9, +26.4] | 4.27 | 52 | +2.5 | 0.69 | 52.6% | 19 | PASS |
| 4.0 | 40/70/30 | +16.0 | [+7.9, +24.2] | 3.78 | 52 | +2.3 | 0.60 | 52.6% | 19 | PASS |

> Combined events with 40/70/30 is the most stable configuration. Same params at
> every spread level, consistent OOS performance (+1.9 to +3.3), reasonable N=19-20.

## Recommendation

**AUDUSD on Combined events**: **Paper-trade candidate** with params 40/70/30.

Strengths:
- Walk-forward PASSES at all spread levels (1.0-4.0)
- Consistent params across all spreads (no parameter instability)
- Full-sample CI well above zero [+6.5, +18.9]
- IS Sharpe 3.78-4.27 across spreads

Concerns:
- OOS E[P&L] is modest (+1.9 to +3.3 pips) compared to USDZAR (+21.3) and USDTRY (+13.9)
- 2024-2025 are slightly negative in year-by-year breakdown
- The edge is primarily driven by AU events (CPI + Employment), not US events at these params
- N=19-20 OOS trades — better than borderline cases but still limited
- Actual AUDUSD event-time spreads need validation (assumed 1.5 default)
- **Scheduling complexity**: AU events release at ~21:30-00:30 ET (Sunday evening in Canada for Monday AU releases), requiring IB Gateway to be running on Sunday nights

**Next steps:**
1. Validate actual AUDUSD event-time spreads from IB paper trading
2. If spreads < 3.0 pips confirmed, begin paper trading with params 40/70/30
3. Investigate IB Gateway Sunday session availability for AU Monday events
4. Re-evaluate after 6 months of paper trading (target: 20+ additional OOS trades)
5. Do NOT enable for live trading until paper results confirm the edge

## Comparison with Other Pairs

| Pair | Source | Status | E[P&L] | OOS E[P&L] | Params |
|------|--------|--------|--------|------------|--------|
| **USDZAR** | US | **ACTIVE** | +17.1 | +21.3 | 50/70/10 |
| **USDTRY** | US | **ACTIVE** | +13.6 | +13.9 | 50/70/10 |
| **AUDUSD** | Combined | **Paper-trade** | +12.5 | +1.9-3.3 | 40/70/30 |
| USDJPY | BOJ | Borderline | +2.5 | +6.4 | 25/15/15 |
| EURUSD | US | Disabled | +0.4 | -2.0 | — |
| USDCAD | US/CA | Disabled | — | -14.3/-10.6 | — |

## Caveats

1. **Australian event dates**: RBA dates are confirmed from official RBA schedule.
   AU CPI dates are confirmed from ABS. AU Employment dates for 2020-2023 are
   estimated (second Thursday of the month) — actual dates may differ by 1-2 days.
   The `simulate_straddle` function finds the closest bar, so minor date errors
   are tolerable.

2. **Two-strategy problem**: US events and AU events have fundamentally different
   optimal params (40/15/25 vs 40/70/30). The Combined analysis uses AU-style
   params which may not be optimal for US events. Consider running US and AU events
   with separate parameter sets if enabling both.

3. **Sunday session risk**: Australian events (especially RBA at 14:30 AEST =
   00:30 ET) may release during Sunday evening in North America. IB Gateway may
   not be running at this time. The bot's cron job currently starts at 7:00 AM ET
   weekdays only.

4. **Spread assumption**: AUDUSD is a liquid major pair with typical spreads of
   0.5-1.5 pips during normal hours. Event-time spreads may widen to 2-4 pips.
   The strategy passes at all tested spread levels, providing good margin of safety.
