# Monte Carlo — Currency Momentum Strategy

**Analysis date:** 2026-07-05
**Strategy:** `src/forex_bot/strategy/momentum.py` — time-series (absolute) momentum
**Data:** Dukascopy continuous daily close, resampled weekly
**Basket:** EURUSD, GBPUSD, AUDUSD, USDJPY, USDCAD, USDZAR, USDTRY
**Range:** 2019-05-27 .. 2026-06-29  (371 weeks)
**Walk-forward:** train < 2025-01, test >= 2025-01

---

## Verdict: **BORDERLINE (paper-trade only)**

Recommended params (best in-sample by Sharpe): **lookback = 6 months, min_return = 5.0%**, top 4 concurrent, weekly Monday rebalance.

> Time-series momentum: each week, rank the basket by trailing return, go long
> the strongest uptrends / short the strongest downtrends, hold the top 4.
> Costs modeled as round-trip bps of notional on turnover (majors 2-3 bps,
> USDZAR 15 bps, USDTRY 35 bps).

## Walk-forward results

| Period | Sharpe | Ann. return | Total | Win rate | Max DD | Weeks |
|--------|--------|-------------|-------|----------|--------|-------|
| In-sample (2020-2024) | 1.14 | +13.0% | +81.6% | 58% | -9.6% | 266 |
| **Out-of-sample (2025-2026)** | **0.14** | **+0.7%** | **+0.9%** | 56% | -4.3% | 78 |

## Monte Carlo (10,000 bootstrap resamples of the OOS weekly-return sequence)

| Metric | Value |
|--------|-------|
| Total return — median | +0.9% |
| Total return — 5th percentile | -8.4% |
| Total return — 95th percentile | +11.2% |
| Sharpe — median | 0.14 |
| Sharpe — 5th percentile | -1.17 |
| P(negative OOS total) | 44% |

## Top in-sample parameter sets (by Sharpe)

| Lookback | Min return | IS Sharpe | IS ann. return |
|----------|-----------|-----------|----------------|
| 6m | 5.0% | 1.14 | +13.0% |
| 12m | 5.0% | 1.14 | +11.8% |
| 12m | 2.0% | 0.89 | +8.1% |
| 12m | 3.0% | 0.87 | +8.0% |
| 12m | 0.0% | 0.83 | +7.5% |
| 12m | 1.0% | 0.83 | +7.4% |
| 6m | 3.0% | 0.82 | +8.4% |
| 3m | 5.0% | 0.76 | +14.2% |

## Notes & caveats

- **Units differ from the straddle reports.** Momentum is a multi-pair portfolio
  strategy, so results are in **% return / Sharpe**, not pips-per-trade.
- Costs are modeled on turnover but slippage on exotics (ZAR/TRY) at weekly
  rebalance is uncertain; the OOS figure is sensitive to the cost assumptions.
- Daily Dukascopy close (BID) is a proxy; live fills use IB mid with spread.
- Single train/test split (matching the project convention). A rolling
  multi-fold walk-forward would add confidence.
- The verdict gates whether momentum should stay enabled beyond paper-trade
  evaluation. Re-run with `/trade-review` once live paper data accumulates.
