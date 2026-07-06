# Monte Carlo — Currency Momentum Strategy (expanded pair universe)

**Analysis date:** 2026-07-05
**Strategy:** `src/forex_bot/strategy/momentum.py` — time-series (absolute) momentum
**Data:** Dukascopy continuous daily close, resampled weekly
**Universe (17 pairs):** EURUSD, GBPUSD, AUDUSD, USDJPY, USDCAD, NZDUSD, EURJPY, EURGBP, GBPJPY, AUDJPY, CADJPY, NZDJPY, EURCAD, GBPCAD, USDMXN, USDZAR, USDTRY
**Range:** 2019-05-27 .. 2026-06-29  (371 weeks)
**Walk-forward:** train < 2025-01, test >= 2025-01 (out-of-sample)

This reevaluates momentum across a broader universe — including pairs that
**failed the event-straddle evaluation** (GBPJPY, CADJPY, EURCAD, GBPCAD) —
because momentum is a different edge and a straddle failure says nothing about it.

---

## Key finding

**Momentum's out-of-sample edge is concentrated in USDTRY** (OOS Sharpe 5.91,
+20.4%/yr), far ahead of the next pair (EURCAD, OOS Sharpe 0.48).
Only **3 of 17** pairs have a positive out-of-sample momentum
Sharpe above 0.3.

- **Broadening the basket HURTS.** The full 17-pair universe scores OOS
  Sharpe -0.09 — *worse* than the original 7 — because the added majors and
  crosses mostly fail out-of-sample and dilute the signal.
- **The star result is a concentration bet, not diversified momentum.** The
  in-sample-selected basket's strong OOS number is dominated by **USDTRY** (an exotic USD trend).
  USDTRY is already a **carry** pair — its persistent trend is the same lira-depreciation
  move the carry book captures — so this momentum "edge" **overlaps the carry strategy**
  and carries the same regime/tail risk (a Turkish-policy reversal breaks it violently).
- **Straddle-failed crosses under momentum:** GBPJPY and EURCAD show *weak-positive*
  OOS momentum (Sharpe ~0.3-0.5) but nothing compelling; CADJPY, GBPCAD, NZDJPY fail.

**Recommendation:** do **not** broaden the live momentum basket. There is no robust
*diversified* momentum edge across majors OOS; the only strong signal (USDTRY) is
already owned by carry, making broad momentum largely redundant. Keep the current
paper-trade evaluation, and if momentum is pursued, treat it as a small USDTRY-centric
sleeve with explicit concentration limits — not a diversified 7- or 17-pair book.

---

## Per-pair diagnostics (single-pair time-series momentum, at lookback=12m / min_return=2.0%)

Which pairs individually carry a momentum edge, sorted by out-of-sample Sharpe.
"pass" = OOS Sharpe > 0.3; "weak+" = positive but marginal; "fail" = non-positive OOS.

| Pair | IS Sharpe | IS ann. | OOS Sharpe | OOS ann. | Verdict |
|------|-----------|---------|------------|----------|---------|
| USDTRY | +1.53 | +47.8% | +5.91 | +20.4% | ✅ pass |
| EURCAD | -0.16 | -0.9% | +0.48 | +2.6% | ✅ pass |
| GBPJPY | +0.04 | +0.4% | +0.30 | +1.5% | ✅ pass |
| AUDJPY | -0.48 | -4.8% | +0.24 | +2.3% | ~ weak+ |
| GBPUSD | -0.06 | -0.5% | +0.05 | +0.3% | ~ weak+ |
| GBPCAD | -0.09 | -0.6% | -0.02 | -0.1% | ❌ fail |
| CADJPY | -0.17 | -1.5% | -0.08 | -0.5% | ❌ fail |
| NZDJPY | -0.32 | -3.1% | -0.14 | -1.4% | ❌ fail |
| USDJPY | +0.55 | +4.9% | -0.26 | -1.4% | ❌ fail |
| AUDUSD | -0.35 | -3.0% | -0.27 | -2.5% | ❌ fail |
| NZDUSD | -0.06 | -0.6% | -0.29 | -2.7% | ❌ fail |
| USDMXN | +0.21 | +2.5% | -0.30 | -2.6% | ❌ fail |
| EURUSD | +0.18 | +1.2% | -0.36 | -2.4% | ❌ fail |
| EURJPY | +0.20 | +1.5% | -0.48 | -2.6% | ❌ fail |
| USDCAD | +0.12 | +0.6% | -0.60 | -2.9% | ❌ fail |
| EURGBP | -0.63 | -2.6% | -0.73 | -2.4% | ❌ fail |
| USDZAR | -0.15 | -2.0% | -0.80 | -6.9% | ❌ fail |

> Note: single-pair diagnostics use the basket-optimal params for comparability;
> they indicate *contribution*, not a standalone tradeable per-pair strategy.

## Basket comparison (walk-forward: params optimized in-sample, tested OOS)

| Basket | Params | IS Sharpe | OOS Sharpe | OOS ann. | MC 5th %ile | P(losing OOS) | Verdict |
|--------|--------|-----------|------------|----------|-------------|---------------|---------|
| Original 7 | 6m / 5.0% | 1.14 | 0.14 | +0.7% | -8.4% | 44% | **BORDERLINE (paper-trade only)** |
| Expanded (all) | 12m / 2.0% | 0.71 | -0.09 | -0.4% | -10.4% | 55% | **AVOID** |
| IS-selected (2) | 12m / 5.0% | 1.88 | 3.87 | +14.4% | +15.0% | 0% | **PASS** |

- **Original 7** — the report-13 basket (EURUSD, GBPUSD, AUDUSD, USDJPY, USDCAD, USDZAR, USDTRY).
- **Expanded (all)** — the full 17-pair universe.
- **IS-selected** — pairs with positive **in-sample** Sharpe only (selection done on
  train data, no out-of-sample peeking): USDTRY, USDJPY.

**Best out-of-sample basket:** IS-selected (2) (OOS Sharpe 3.87).

## Top in-sample parameter sets (expanded universe, by Sharpe)

| Lookback | Min return | IS Sharpe | IS ann. |
|----------|-----------|-----------|---------|
| 12m | 2.0% | 0.71 | +6.4% |
| 12m | 0.0% | 0.70 | +6.4% |
| 12m | 1.0% | 0.70 | +6.4% |
| 12m | 3.0% | 0.70 | +6.4% |
| 12m | 5.0% | 0.66 | +6.0% |
| 6m | 5.0% | 0.63 | +7.3% |
| 6m | 3.0% | 0.55 | +6.0% |
| 6m | 2.0% | 0.47 | +5.1% |

## Takeaways

- The highest OOS *basket* Sharpe (IS-selected (2)) is driven by the
  concentration effect described in **Key finding** above — it is not evidence of a
  broad, diversifiable momentum edge.
- Diversified currency momentum across majors/crosses is **absent out-of-sample**
  here, consistent with the well-documented post-2015 weakening of the factor.
- Use the per-pair table to see which currencies actually trend-follow OOS rather
  than trading a basket blindly — but note the winners overlap the carry book.
- All results remain **paper-trade evidence only** until the live paper period
  confirms (or kills) the edge.

## Additional pairs screened (2026-07-05) — none recommended

Single-pair momentum was also screened on every additional exotic USD pair
Dukascopy can serve daily history for. None produced a robust, tradeable edge:

| Pair | OOS Sharpe (6m/5%) | OOS Sharpe (12m/2%) | Note |
|------|--------------------|---------------------|------|
| USDILS | +0.76 | +1.35 | war-driven regime trend (2023-24); thin; IB tradeability unclear |
| USDCNH | 0.00 | +1.44 | PBOC-managed — intervention / peg-break tail risk |
| USDSGD | −0.52 | +0.40 | MAS-managed; param-sensitive |
| USDTHB | −0.94 | +0.34 | managed; param-sensitive |
| USDHUF | −0.44 | +0.05 | negative-to-flat |
| USDMXN, USDPLN, USDCZK, USDNOK, USDSEK | negative | negative | no edge |

The high-inflation EM depreciators most likely to trend (USDBRL, USDINR, USDIDR,
USDPHP, USDCLP, USDCOP, USDRUB) are **not available in Dukascopy**, so they could
not be validated — and, like USDTRY, they would overlap the carry book. The
apparent winners (ILS, CNH) are regime / intervention artifacts that only pass at
one param set and fail the data-snooping smell test given the pairs×params
screened. **No new momentum pair is recommended.**

## Caveats

- Units are **% return / Sharpe** (portfolio strategy), not pips-per-trade.
- Costs modeled on turnover; exotic (ZAR/TRY/MXN) slippage at weekly rebalance is
  uncertain and the OOS figures are sensitive to it.
- Daily Dukascopy BID close is a proxy; live fills use IB mid + spread.
- Single train/test split; a rolling multi-fold walk-forward would add confidence.
- Re-run with `/trade-review` once live paper data accumulates.
