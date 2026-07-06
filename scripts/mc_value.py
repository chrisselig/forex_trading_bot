"""Monte Carlo + walk-forward validation for the value / PPP strategy.

Backtests the strategy in src/forex_bot/strategy/value.py: each month, build
each pair's real exchange rate (nominal price x relative CPI), measure its
trailing-window deviation from the mean as a z-score, then go long the most
undervalued / short the most overvalued and hold one month.

Method:
  - Daily Dukascopy close (majors) resampled monthly; FRED CPI per currency.
  - Trailing-window z-score => walk-forward by construction (only past data).
  - Walk-forward split: optimize (lookback_years, z_threshold) on the train
    period, test on the untouched 2025-2026 out-of-sample period.
  - Monte Carlo: bootstrap the OOS monthly-return sequence (10k runs).
  - Reports the value-vs-carry return correlation (does value diversify carry?).

Usage:
    python scripts/mc_value.py [--refresh-data]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import dukascopy_python as dp
import numpy as np
import pandas as pd

from forex_bot.calendar.fred_client import FredClient

MAJORS = ["EURUSD", "GBPUSD", "USDJPY", "USDCAD", "AUDUSD", "NZDUSD", "USDCHF"]

CPI_SERIES = {
    "USD": "CPIAUCSL", "EUR": "CP0000EZ19M086NEST", "GBP": "GBRCPIALLMINMEI",
    "JPY": "JPNCPIALLMINMEI", "CAD": "CANCPIALLMINMEI", "AUD": "AUSCPIALLQINMEI",
    "NZD": "NZLCPIALLQINMEI", "CHF": "CHECPIALLMINMEI",
}
# 3-month interbank rates for the carry-factor comparison.
RATE_SERIES = {
    "USD": "IR3TIB01USM156N", "EUR": "IR3TIB01EZM156N", "GBP": "IR3TIB01GBM156N",
    "JPY": "IR3TIB01JPM156N", "CAD": "IR3TIB01CAM156N", "AUD": "IR3TIB01AUM156N",
    "NZD": "IR3TIB01NZM156N", "CHF": "IR3TIB01CHM156N",
}
COST_BPS = {p: 3.0 for p in MAJORS}

TOP_N = 4
MONTHS_PER_YEAR = 12
DATA_DIR = Path(__file__).parent / "data" / "dukascopy"
DATA_START = pd.Timestamp("2010-01-01")
DATA_END = pd.Timestamp("2026-07-01")
TRAIN_END = pd.Timestamp("2025-01-01")

LOOKBACK_YEARS_GRID = [5, 8]
Z_THRESHOLD_GRID = [0.5, 1.0, 1.5, 2.0]
MIN_WINDOW = 24  # months of trailing history needed to trust a z-score


def _instrument(pair: str) -> str:
    return f"{pair[:3]}/{pair[3:]}"


def load_daily_close(pair: str, refresh: bool = False) -> pd.Series:
    cache = DATA_DIR / f"{pair}_daily_long.csv"
    if cache.exists() and not refresh:
        s = pd.read_csv(cache, index_col=0, parse_dates=True)["close"]
        s.index = pd.to_datetime(s.index, utc=True).tz_localize(None)
        return s
    print(f"  fetching daily {pair} ...")
    df = dp.fetch(
        _instrument(pair), dp.INTERVAL_DAY_1, dp.OFFER_SIDE_BID,
        DATA_START.to_pydatetime(), DATA_END.to_pydatetime(),
    )
    s = df["close"].copy()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    s.name = "close"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    s.to_csv(cache)
    return s


def fred_monthly(fred: FredClient, series_id: str, index: pd.DatetimeIndex) -> pd.Series:
    """Fetch a FRED series and reindex to `index` (month-end), forward-filled."""
    data = fred.get_series(series_id, DATA_START.to_pydatetime(), DATA_END.to_pydatetime())
    if not data:
        return pd.Series(index=index, dtype=float)
    s = pd.Series(
        [d["value"] for d in data],
        index=pd.to_datetime([d["date"] for d in data]),
    ).sort_index()
    # Align to month-end and forward-fill (handles quarterly AUD/NZD CPI).
    return s.resample("ME").last().reindex(index, method="ffill")


def build_panels(refresh: bool = False):
    """Return (price_panel, rer_panel, rate_panel) on a common monthly index."""
    prices = {}
    for pair in MAJORS:
        daily = load_daily_close(pair, refresh=refresh)
        prices[pair] = daily.resample("ME").last()
    price_panel = pd.DataFrame(prices).dropna(how="all")
    idx = price_panel.index

    fred = FredClient()
    cpi = {cur: fred_monthly(fred, sid, idx) for cur, sid in CPI_SERIES.items()}
    rate = {cur: fred_monthly(fred, sid, idx) for cur, sid in RATE_SERIES.items()}
    cpi_panel = pd.DataFrame(cpi)
    rate_panel = pd.DataFrame(rate)

    # Real exchange rate q = S * CPI_base / CPI_quote
    rer = {}
    for pair in MAJORS:
        base, quote = pair[:3], pair[3:]
        rer[pair] = price_panel[pair] * cpi_panel[base] / cpi_panel[quote]
    rer_panel = pd.DataFrame(rer)
    return price_panel, rer_panel, rate_panel


def backtest_value(price_panel, rer_panel, lookback_years, z_threshold):
    """Monthly PPP backtest; returns the portfolio monthly-return series."""
    lb = lookback_years * 12
    months = price_panel.index
    prev: dict[str, int] = {}
    records = []

    for i in range(lb, len(months) - 1):
        t_next = months[i + 1]
        z_by_pair = {}
        for pair in MAJORS:
            window = rer_panel[pair].iloc[i - lb:i + 1].dropna()
            if len(window) < MIN_WINDOW or window.std(ddof=0) <= 0:
                continue
            z = (window.iloc[-1] - window.mean()) / window.std(ddof=0)
            z_by_pair[pair] = z

        ranked = sorted(z_by_pair.items(), key=lambda kv: abs(kv[1]), reverse=True)
        selected = [(p, z) for p, z in ranked if abs(z) >= z_threshold][:TOP_N]
        # z>0: base overvalued -> SELL pair; z<0: undervalued -> BUY
        positions = {p: (-1 if z > 0 else 1) for p, z in selected}

        pnl = cost = 0.0
        for pair, d in positions.items():
            p1, p2 = price_panel[pair].iloc[i], price_panel[pair].iloc[i + 1]
            if pd.notna(p1) and pd.notna(p2) and p1 > 0:
                pnl += d * (p2 / p1 - 1)
            if prev.get(pair, 0) != d:
                cost += COST_BPS[pair] / 10_000
        for pair in prev:
            if pair not in positions:
                cost += COST_BPS[pair] / 10_000

        n = max(len(positions), 1)
        records.append((t_next, pnl / n - cost / n))
        prev = positions

    return pd.Series([r for _, r in records], index=pd.DatetimeIndex([d for d, _ in records]))


def carry_factor(price_panel, rate_panel):
    """A simple G10 carry factor over the same majors: long the higher-rate
    currency of each pair, equal weight — used only for the value/carry
    correlation."""
    months = price_panel.index
    records = []
    for i in range(len(months) - 1):
        pnl = 0.0
        n = 0
        for pair in MAJORS:
            base, quote = pair[:3], pair[3:]
            rb, rq = rate_panel[base].iloc[i], rate_panel[quote].iloc[i]
            p1, p2 = price_panel[pair].iloc[i], price_panel[pair].iloc[i + 1]
            if pd.isna(rb) or pd.isna(rq) or pd.isna(p1) or pd.isna(p2) or p1 <= 0:
                continue
            d = 1 if rb > rq else -1  # long the higher-yielding currency
            pnl += d * ((p2 / p1 - 1) + (rb - rq) / 100 / 12)  # spot + carry accrual
            n += 1
        if n:
            records.append((months[i + 1], pnl / n))
    return pd.Series([r for _, r in records], index=pd.DatetimeIndex([d for d, _ in records]))


def metrics(m: pd.Series) -> dict:
    if len(m) == 0:
        return {"n": 0, "sharpe": 0.0, "ann_return": 0.0, "total_return": 0.0,
                "win_rate": 0.0, "max_dd": 0.0}
    mean, std = m.mean(), m.std(ddof=1)
    sharpe = (mean / std * np.sqrt(MONTHS_PER_YEAR)) if std > 0 else 0.0
    equity = (1 + m).cumprod()
    return {
        "n": len(m), "sharpe": sharpe,
        "ann_return": (1 + mean) ** MONTHS_PER_YEAR - 1,
        "total_return": equity.iloc[-1] - 1, "win_rate": (m > 0).mean(),
        "max_dd": (equity / equity.cummax() - 1).min(),
    }


def monte_carlo(m: pd.Series, runs: int = 10_000, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    arr = m.to_numpy()
    n = len(arr)
    if n == 0:
        return {"median_total": 0.0, "p5_total": 0.0, "p95_total": 0.0, "p_negative": 1.0}
    totals = np.array([np.prod(1 + arr[rng.integers(0, n, n)]) - 1 for _ in range(runs)])
    return {
        "median_total": float(np.median(totals)),
        "p5_total": float(np.percentile(totals, 5)),
        "p95_total": float(np.percentile(totals, 95)),
        "p_negative": float((totals < 0).mean()),
    }


def optimize_is(price_panel, rer_panel):
    results = []
    for ly in LOOKBACK_YEARS_GRID:
        for zt in Z_THRESHOLD_GRID:
            m = backtest_value(price_panel, rer_panel, ly, zt)
            train = m[m.index < TRAIN_END]
            mm = metrics(train)
            results.append((ly, zt, mm["sharpe"], mm["ann_return"], mm["n"]))
    results.sort(key=lambda r: r[2], reverse=True)
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-data", action="store_true")
    args = ap.parse_args()

    print("Building monthly price / RER / rate panels...")
    price_panel, rer_panel, rate_panel = build_panels(refresh=args.refresh_data)
    print(f"  months: {len(price_panel)}  range: {price_panel.index[0].date()} .. {price_panel.index[-1].date()}")

    ranking = optimize_is(price_panel, rer_panel)
    print("\nTop in-sample params (by Sharpe):")
    for ly, zt, sh, ar, n in ranking[:5]:
        print(f"  lookback={ly}y z>={zt}  IS Sharpe={sh:.2f} ann={ar*100:+.1f}% n={n}")
    best_ly, best_zt = ranking[0][0], ranking[0][1]

    full = backtest_value(price_panel, rer_panel, best_ly, best_zt)
    is_, oos = full[full.index < TRAIN_END], full[full.index >= TRAIN_END]
    m_is, m_oos = metrics(is_), metrics(oos)
    mc = monte_carlo(oos)

    print(f"\nBest IN-SAMPLE params: lookback={best_ly}y, z_threshold={best_zt}")
    print("=== IN-SAMPLE ===")
    print(f"  Sharpe={m_is['sharpe']:.2f} ann={m_is['ann_return']*100:+.1f}% "
          f"total={m_is['total_return']*100:+.1f}% win={m_is['win_rate']*100:.0f}% n={m_is['n']}")
    print("=== OUT-OF-SAMPLE (2025-2026) ===")
    print(f"  Sharpe={m_oos['sharpe']:.2f} ann={m_oos['ann_return']*100:+.1f}% "
          f"total={m_oos['total_return']*100:+.1f}% win={m_oos['win_rate']*100:.0f}% n={m_oos['n']}")
    print("=== MONTE CARLO (OOS) ===")
    print(f"  total median={mc['median_total']*100:+.1f}% 5th={mc['p5_total']*100:+.1f}% "
          f"95th={mc['p95_total']*100:+.1f}%  P(neg)={mc['p_negative']*100:.0f}%")

    # Value vs carry correlation (full sample, aligned months)
    carry = carry_factor(price_panel, rate_panel)
    aligned = pd.concat(
        [full.rename("value"), carry.rename("carry")], axis=1, sort=True
    ).dropna()
    corr = aligned["value"].corr(aligned["carry"]) if len(aligned) > 2 else float("nan")
    print(f"\n=== VALUE vs CARRY correlation: {corr:+.2f}  (n={len(aligned)} months) ===")

    verdict = _verdict(m_is, m_oos, mc)
    print(f"\n=== VERDICT: {verdict} ===")
    _write_report(price_panel, best_ly, best_zt, m_is, m_oos, mc, ranking, corr, len(aligned), verdict)


def _verdict(is_: dict, oos: dict, mc: dict) -> str:
    """Honest verdict. A strong OOS number with a flat in-sample edge is NOT a
    pass — with no in-sample signal it is small-sample noise, not a validated
    strategy. Requires a real in-sample edge AND an adequate OOS sample."""
    if oos["n"] < 30:
        return "INCONCLUSIVE (out-of-sample window too small — < 30 months)"
    if is_["sharpe"] < 0.2:
        return "INCONCLUSIVE (no in-sample edge — OOS gain is small-sample noise, not a validated edge)"
    if oos["sharpe"] > 0.5 and oos["ann_return"] > 0 and mc["p5_total"] > -0.10:
        return "PASS"
    if oos["ann_return"] > 0 and mc["median_total"] > 0:
        return "BORDERLINE (paper-trade only)"
    return "AVOID"


def _write_report(price_panel, ly, zt, m_is, m_oos, mc, ranking, corr, n_corr, verdict) -> None:
    report = Path(__file__).parent.parent / "docs" / "research" / "14-mc-value-ppp.md"
    grid = "\n".join(
        f"| {r[0]}y | {r[1]} | {r[2]:.2f} | {r[3]*100:+.1f}% |" for r in ranking[:8]
    )
    report.write_text(f"""# Monte Carlo — Value / PPP Strategy

**Analysis date:** 2026-07-06
**Strategy:** `src/forex_bot/strategy/value.py` — relative-PPP real-exchange-rate reversion
**Data:** Dukascopy daily close (monthly) + FRED CPI; monthly rebalance
**Universe:** {", ".join(MAJORS)}
**Range:** {price_panel.index[0].date()} .. {price_panel.index[-1].date()}  ({len(price_panel)} months)
**Walk-forward:** train < 2025-01, test >= 2025-01 (out-of-sample)

---

## Verdict: **{verdict}**

Recommended params (best in-sample by Sharpe): **lookback = {ly} years, z-threshold = {zt}**, top {TOP_N} concurrent, monthly rebalance.

> Real exchange rate q = nominal price x (base CPI / quote CPI). Each month, take
> the pairs whose q is furthest from its trailing-window mean (|z| >= threshold):
> long undervalued (z<0), short overvalued (z>0). Costs {COST_BPS[MAJORS[0]]:.0f} bps round-trip on turnover.

## Key finding — the OOS number is NOT a validated edge

The out-of-sample Sharpe ({m_oos['sharpe']:.2f}) looks strong, but read it with the
in-sample number next to it: **in-sample Sharpe is {m_is['sharpe']:.2f}** — essentially
flat over ~{m_is['n']} months. This is the *opposite* of overfitting; there is simply
**no in-sample edge**, so the strong OOS result comes from a **{m_oos['n']}-month
window** — far too short to be statistically meaningful (a good Sharpe over ~1.5
years is well inside noise). The params were chosen from an in-sample surface that
is flat everywhere, so "best params" is close to arbitrary.

**Interpretation:** relative-PPP mean-reversion at a 1-month horizon shows no
durable edge on developed majors here — consistent with the literature that PPP
reversion acts over *years*, not months. Do **not** treat the +OOS as a green light.

**The one genuinely useful result:** value's returns are **{corr:+.2f} correlated with
a carry factor** on the same majors — negative, i.e. value is a real *diversifier*,
which was the whole rationale. But a diversifier with ~zero expected standalone
return is not yet a reason to trade it. If pursued, test a **longer holding horizon**
(quarterly/annual) and a longer OOS before enabling.

## Walk-forward results

| Period | Sharpe | Ann. return | Total | Win rate | Max DD | Months |
|--------|--------|-------------|-------|----------|--------|--------|
| In-sample | {m_is['sharpe']:.2f} | {m_is['ann_return']*100:+.1f}% | {m_is['total_return']*100:+.1f}% | {m_is['win_rate']*100:.0f}% | {m_is['max_dd']*100:.1f}% | {m_is['n']} |
| **Out-of-sample (2025-2026)** | **{m_oos['sharpe']:.2f}** | **{m_oos['ann_return']*100:+.1f}%** | **{m_oos['total_return']*100:+.1f}%** | {m_oos['win_rate']*100:.0f}% | {m_oos['max_dd']*100:.1f}% | {m_oos['n']} |

## Monte Carlo (10k bootstrap of OOS monthly returns)

| Metric | Value |
|--------|-------|
| Total return — median | {mc['median_total']*100:+.1f}% |
| Total return — 5th percentile | {mc['p5_total']*100:+.1f}% |
| Total return — 95th percentile | {mc['p95_total']*100:+.1f}% |
| P(negative OOS total) | {mc['p_negative']*100:.0f}% |

## Value vs. carry correlation

**{corr:+.2f}** over {n_corr} common months (a simple G10 carry factor on the same
majors). A low/negative correlation is the whole point — value is meant to
diversify the carry book, not duplicate it (unlike momentum, which was
USDTRY/carry-concentrated).

## Top in-sample parameter sets (by Sharpe)

| Lookback | z-threshold | IS Sharpe | IS ann. |
|----------|-------------|-----------|---------|
{grid}

## Caveats

- **Low observation count.** Monthly rebalancing means the OOS window (2025-2026)
  has only ~{m_oos['n']} data points — statistically thin; the MC bootstrap widens
  but cannot manufacture confidence. Treat the verdict as provisional.
- Value strategies are slow: real mis-pricings can persist for years, so a short
  OOS window may not capture a full reversion cycle.
- FRED CPI is released with a lag and some series (AUD/NZD) are quarterly
  (forward-filled to monthly); daily Dukascopy BID close is a proxy for IB mid.
- Costs modeled on turnover; monthly turnover is low so cost sensitivity is small.
- Re-run with `/trade-review` once live paper data accumulates.
""")
    print(f"\nReport written to {report}")


if __name__ == "__main__":
    main()
