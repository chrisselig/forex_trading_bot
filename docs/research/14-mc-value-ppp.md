# Monte Carlo — Value / PPP Strategy

**Analysis date:** 2026-07-06
**Strategy:** `src/forex_bot/strategy/value.py` — relative-PPP real-exchange-rate reversion
**Data:** Dukascopy daily close (monthly) + FRED CPI; monthly rebalance
**Universe:** EURUSD, GBPUSD, USDJPY, USDCAD, AUDUSD, NZDUSD, USDCHF
**Range:** 2010-01-31 .. 2026-07-31  (199 months)
**Walk-forward:** train < 2025-01, test >= 2025-01 (out-of-sample)

---

## Verdict: **INCONCLUSIVE (out-of-sample window too small — < 30 months)**

Recommended params (best in-sample by Sharpe): **lookback = 5 years, z-threshold = 1.0**, top 4 concurrent, monthly rebalance.

> Real exchange rate q = nominal price x (base CPI / quote CPI). Each month, take
> the pairs whose q is furthest from its trailing-window mean (|z| >= threshold):
> long undervalued (z<0), short overvalued (z>0). Costs 3 bps round-trip on turnover.

## Key finding — the OOS number is NOT a validated edge

The out-of-sample Sharpe (1.29) looks strong, but read it with the
in-sample number next to it: **in-sample Sharpe is 0.03** — essentially
flat over ~119 months. This is the *opposite* of overfitting; there is simply
**no in-sample edge**, so the strong OOS result comes from a **19-month
window** — far too short to be statistically meaningful (a good Sharpe over ~1.5
years is well inside noise). The params were chosen from an in-sample surface that
is flat everywhere, so "best params" is close to arbitrary.

**Interpretation:** relative-PPP mean-reversion at a 1-month horizon shows no
durable edge on developed majors here — consistent with the literature that PPP
reversion acts over *years*, not months. Do **not** treat the +OOS as a green light.

**The one genuinely useful result:** value's returns are **-0.47 correlated with
a carry factor** on the same majors — negative, i.e. value is a real *diversifier*,
which was the whole rationale. But a diversifier with ~zero expected standalone
return is not yet a reason to trade it. If pursued, test a **longer holding horizon**
(quarterly/annual) and a longer OOS before enabling.

## Walk-forward results

| Period | Sharpe | Ann. return | Total | Win rate | Max DD | Months |
|--------|--------|-------------|-------|----------|--------|--------|
| In-sample | 0.03 | +0.2% | -0.5% | 48% | -17.3% | 119 |
| **Out-of-sample (2025-2026)** | **1.29** | **+7.0%** | **+11.0%** | 53% | -2.4% | 19 |

## Monte Carlo (10k bootstrap of OOS monthly returns)

| Metric | Value |
|--------|-------|
| Total return — median | +10.7% |
| Total return — 5th percentile | +0.3% |
| Total return — 95th percentile | +23.7% |
| P(negative OOS total) | 5% |

## Longer-horizon test (does PPP work when given time to revert?)

PPP reversion is slow, so a 1-month hold may be too fast. This sweeps holding
horizons with **non-overlapping** formations (honest stats, fewer points at
large H). The **information coefficient** is corr(z, forward-H-month return),
pooled over pairs/dates — **negative = mean-reversion (the value bet works)**;
positive = the signal is anti-predictive at that horizon.

| Hold | IC (z→fwd) | t-stat | IC obs | Backtest Sharpe | Ann. | Rebalances |
|------|-----------|--------|--------|-----------------|------|------------|
| 1 mo | -0.02 | -0.4 | 716 | +0.20 | +1.3% | 129 |
| 3 mo | -0.04 | -0.6 | 238 | +0.04 | +0.3% | 44 |
| 6 mo | +0.00 | +0.0 | 119 | +0.14 | +0.9% | 22 |
| 12 mo | -0.03 | -0.2 | 55 | +0.25 | +1.6% | 10 |

**Conclusion:** **no horizon shows statistically meaningful reversion** (all ICs are near zero or not significant) — lengthening the hold does not rescue the signal.

## Value vs. carry correlation

**-0.47** over 137 common months (a simple G10 carry factor on the same
majors). A low/negative correlation is the whole point — value is meant to
diversify the carry book, not duplicate it (unlike momentum, which was
USDTRY/carry-concentrated).

## Top in-sample parameter sets (by Sharpe)

| Lookback | z-threshold | IS Sharpe | IS ann. |
|----------|-------------|-----------|---------|
| 5y | 1.0 | 0.03 | +0.2% |
| 8y | 1.5 | -0.07 | -0.5% |
| 5y | 0.5 | -0.10 | -0.6% |
| 5y | 2.0 | -0.17 | -1.0% |
| 8y | 1.0 | -0.23 | -1.7% |
| 8y | 0.5 | -0.26 | -2.0% |
| 5y | 1.5 | -0.34 | -2.3% |
| 8y | 2.0 | -0.64 | -4.5% |

## Caveats

- **Low observation count.** Monthly rebalancing means the OOS window (2025-2026)
  has only ~19 data points — statistically thin; the MC bootstrap widens
  but cannot manufacture confidence. Treat the verdict as provisional.
- Value strategies are slow: real mis-pricings can persist for years, so a short
  OOS window may not capture a full reversion cycle.
- FRED CPI is released with a lag and some series (AUD/NZD) are quarterly
  (forward-filled to monthly); daily Dukascopy BID close is a proxy for IB mid.
- Costs modeled on turnover; monthly turnover is low so cost sensitivity is small.
- Re-run with `/trade-review` once live paper data accumulates.
