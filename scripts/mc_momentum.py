"""Monte Carlo + walk-forward validation for the currency momentum strategy.

Unlike the event-straddle MC scripts (distance/TP/SL pips around events), this
backtests the TIME-SERIES momentum strategy (src/forex_bot/strategy/momentum.py):
each week, rank the basket by trailing return, go long the strongest uptrends /
short the strongest downtrends, hold the top N, rebalance weekly.

Method:
  - Continuous daily Dukascopy close for the basket, resampled to weekly.
  - Walk-forward: optimize (lookback_months, min_return_pct) on 2020-2024,
    test on the untouched 2025-2026 out-of-sample period.
  - Monte Carlo: bootstrap the OOS weekly-return sequence (10k runs).
  - Realistic round-trip costs per pair (bps of notional) charged on turnover.

Usage:
    python scripts/mc_momentum.py [--refresh-data]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import dukascopy_python as dp
import numpy as np
import pandas as pd

# Momentum basket (matches config/settings.yaml momentum.instruments)
PAIRS = ["EURUSD", "GBPUSD", "AUDUSD", "USDJPY", "USDCAD", "USDZAR", "USDTRY"]

# Round-trip transaction cost in basis points of notional, charged whenever a
# position is opened or flipped. Majors are cheap; exotics are wide.
COST_BPS = {
    "EURUSD": 2.0, "GBPUSD": 2.0, "AUDUSD": 2.0, "USDJPY": 2.0,
    "USDCAD": 3.0, "USDZAR": 15.0, "USDTRY": 35.0,
}

TOP_N = 4  # max concurrent (matches max_concurrent_momentum)
WEEKS_PER_YEAR = 52
DATA_DIR = Path(__file__).parent / "data" / "dukascopy"

# Backtest window (extra lead-in for the longest lookback)
DATA_START = pd.Timestamp("2019-06-01")
DATA_END = pd.Timestamp("2026-07-01")
TRAIN_END = pd.Timestamp("2025-01-01")  # train < this; test >= this

# Param grid to sweep
LOOKBACK_MONTHS_GRID = [1, 2, 3, 6, 12]
MIN_RETURN_PCT_GRID = [0.0, 1.0, 2.0, 3.0, 5.0]


def _instrument(pair: str) -> str:
    return f"{pair[:3]}/{pair[3:]}"


def load_daily_close(pair: str, refresh: bool = False) -> pd.Series:
    """Continuous daily close for a pair, cached to CSV."""
    cache = DATA_DIR / f"{pair}_daily.csv"
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


def build_weekly_panel(refresh: bool = False) -> pd.DataFrame:
    """Weekly (Monday-anchored) close panel: index=weeks, columns=pairs."""
    cols = {}
    for pair in PAIRS:
        daily = load_daily_close(pair, refresh=refresh)
        # Weekly close anchored to Monday (label = the Monday of each week)
        weekly = daily.resample("W-MON", label="left", closed="left").last()
        cols[pair] = weekly
    panel = pd.DataFrame(cols).dropna(how="all").ffill()
    return panel


def backtest(
    panel: pd.DataFrame, lookback_weeks: int, min_return_pct: float,
) -> pd.Series:
    """Run the weekly momentum backtest, return the portfolio weekly-return series."""
    weeks = panel.index
    prev_positions: dict[str, int] = {}  # pair -> +1/-1
    records: list[tuple[pd.Timestamp, float]] = []

    # Need lookback history to score, and one week ahead to realize P&L
    for i in range(lookback_weeks, len(weeks) - 1):
        t, t_next = weeks[i], weeks[i + 1]
        prices_now = panel.loc[t]
        prices_prev = panel.loc[weeks[i - lookback_weeks]]
        prices_next = panel.loc[t_next]

        # Trailing return per pair (%), skip pairs with missing data
        rets = {}
        for pair in PAIRS:
            p0, p1 = prices_prev[pair], prices_now[pair]
            if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                rets[pair] = (p1 / p0 - 1) * 100

        # Rank by |return|, filter by threshold, take top N
        ranked = sorted(rets.items(), key=lambda kv: abs(kv[1]), reverse=True)
        selected = [(p, r) for p, r in ranked if abs(r) >= min_return_pct][:TOP_N]
        positions = {p: (1 if r > 0 else -1) for p, r in selected}

        # Realize next-week P&L (equal weight across held positions)
        pnl = 0.0
        cost = 0.0
        for pair, direction in positions.items():
            p1, p2 = prices_now[pair], prices_next[pair]
            if pd.notna(p1) and pd.notna(p2) and p1 > 0:
                pnl += direction * (p2 / p1 - 1)
            # Charge round-trip cost when opening or flipping
            if prev_positions.get(pair, 0) != direction:
                cost += COST_BPS[pair] / 10_000
        # Charge exit cost for positions we dropped this week
        for pair, direction in prev_positions.items():
            if pair not in positions:
                cost += COST_BPS[pair] / 10_000

        n = max(len(positions), 1)
        weekly_ret = pnl / n - cost / n
        records.append((t_next, weekly_ret))
        prev_positions = positions

    return pd.Series(
        [r for _, r in records], index=pd.DatetimeIndex([d for d, _ in records]),
    )


def metrics(weekly: pd.Series) -> dict:
    """Summary metrics for a weekly-return series."""
    if len(weekly) == 0:
        return {"n": 0, "sharpe": 0.0, "ann_return": 0.0, "total_return": 0.0,
                "win_rate": 0.0, "max_dd": 0.0}
    mean, std = weekly.mean(), weekly.std(ddof=1)
    sharpe = (mean / std * np.sqrt(WEEKS_PER_YEAR)) if std > 0 else 0.0
    ann_return = (1 + mean) ** WEEKS_PER_YEAR - 1
    equity = (1 + weekly).cumprod()
    total_return = equity.iloc[-1] - 1
    max_dd = (equity / equity.cummax() - 1).min()
    return {
        "n": len(weekly), "sharpe": sharpe, "ann_return": ann_return,
        "total_return": total_return, "win_rate": (weekly > 0).mean(),
        "max_dd": max_dd,
    }


def monte_carlo(weekly: pd.Series, runs: int = 10_000, seed: int = 42) -> dict:
    """Bootstrap the OOS weekly-return sequence; distribution of total return."""
    rng = np.random.default_rng(seed)
    arr = weekly.to_numpy()
    n = len(arr)
    totals, sharpes = np.empty(runs), np.empty(runs)
    for k in range(runs):
        sample = arr[rng.integers(0, n, n)]
        totals[k] = np.prod(1 + sample) - 1
        s = sample.std(ddof=1)
        sharpes[k] = (sample.mean() / s * np.sqrt(WEEKS_PER_YEAR)) if s > 0 else 0.0
    return {
        "median_total": float(np.median(totals)),
        "p5_total": float(np.percentile(totals, 5)),
        "p95_total": float(np.percentile(totals, 95)),
        "median_sharpe": float(np.median(sharpes)),
        "p5_sharpe": float(np.percentile(sharpes, 5)),
        "p_negative": float((totals < 0).mean()),
    }


def lookback_weeks(months: int) -> int:
    return max(1, round(months * 4.345))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-data", action="store_true", help="Re-download daily data")
    args = ap.parse_args()

    print("Building weekly panel...")
    panel = build_weekly_panel(refresh=args.refresh_data)
    print(f"  weeks: {len(panel)}  range: {panel.index[0].date()} .. {panel.index[-1].date()}")

    train_mask = panel.index < TRAIN_END
    print(f"  train weeks: {train_mask.sum()}  test weeks: {(~train_mask).sum()}")

    # --- Walk-forward: optimize on train, evaluate on test ---
    print("\nGrid search on IN-SAMPLE (train 2020-2024)...")
    results = []
    for lm in LOOKBACK_MONTHS_GRID:
        for mr in MIN_RETURN_PCT_GRID:
            weekly = backtest(panel, lookback_weeks(lm), mr)
            train = weekly[weekly.index < TRAIN_END]
            m = metrics(train)
            results.append((lm, mr, m["sharpe"], m["ann_return"], m["n"]))
    results.sort(key=lambda r: r[2], reverse=True)
    print("  top in-sample params (by Sharpe):")
    for lm, mr, sh, ar, n in results[:5]:
        print(f"    lookback={lm}m min_ret={mr}%  IS Sharpe={sh:.2f}  ann={ar*100:+.1f}%  n={n}")

    best_lm, best_mr = results[0][0], results[0][1]
    print(f"\nBest IN-SAMPLE params: lookback={best_lm}m, min_return={best_mr}%")

    # Out-of-sample with the chosen params
    weekly_full = backtest(panel, lookback_weeks(best_lm), best_mr)
    oos = weekly_full[weekly_full.index >= TRAIN_END]
    is_ = weekly_full[weekly_full.index < TRAIN_END]
    m_is, m_oos = metrics(is_), metrics(oos)

    print("\n=== IN-SAMPLE (2020-2024) ===")
    print(f"  Sharpe={m_is['sharpe']:.2f}  ann={m_is['ann_return']*100:+.1f}%  "
          f"total={m_is['total_return']*100:+.1f}%  win={m_is['win_rate']*100:.0f}%  "
          f"maxDD={m_is['max_dd']*100:.1f}%  n={m_is['n']}")
    print("=== OUT-OF-SAMPLE (2025-2026) ===")
    print(f"  Sharpe={m_oos['sharpe']:.2f}  ann={m_oos['ann_return']*100:+.1f}%  "
          f"total={m_oos['total_return']*100:+.1f}%  win={m_oos['win_rate']*100:.0f}%  "
          f"maxDD={m_oos['max_dd']*100:.1f}%  n={m_oos['n']}")

    # --- Monte Carlo on the OOS sequence ---
    mc = monte_carlo(oos)
    print("\n=== MONTE CARLO (10k bootstrap of OOS weeks) ===")
    print(f"  total return: median={mc['median_total']*100:+.1f}%  "
          f"5th={mc['p5_total']*100:+.1f}%  95th={mc['p95_total']*100:+.1f}%")
    print(f"  Sharpe: median={mc['median_sharpe']:.2f}  5th={mc['p5_sharpe']:.2f}")
    print(f"  P(negative OOS total) = {mc['p_negative']*100:.0f}%")

    # --- Verdict ---
    verdict = _verdict(m_oos, mc)
    print(f"\n=== VERDICT: {verdict} ===")

    _write_report(panel, best_lm, best_mr, m_is, m_oos, mc, results, verdict)


def _verdict(m_oos: dict, mc: dict) -> str:
    if m_oos["sharpe"] > 0.5 and m_oos["ann_return"] > 0 and mc["p5_total"] > -0.10:
        return "PASS"
    if m_oos["ann_return"] > 0 and mc["median_total"] > 0:
        return "BORDERLINE (paper-trade only)"
    return "AVOID"


def _write_report(panel, best_lm, best_mr, m_is, m_oos, mc, results, verdict) -> None:
    report = Path(__file__).parent.parent / "docs" / "research" / "13-mc-momentum.md"
    top_rows = "\n".join(
        f"| {lm}m | {mr}% | {sh:.2f} | {ar*100:+.1f}% |"
        for lm, mr, sh, ar, _ in results[:8]
    )
    report.write_text(f"""# Monte Carlo — Currency Momentum Strategy

**Analysis date:** 2026-07-05
**Strategy:** `src/forex_bot/strategy/momentum.py` — time-series (absolute) momentum
**Data:** Dukascopy continuous daily close, resampled weekly
**Basket:** {", ".join(PAIRS)}
**Range:** {panel.index[0].date()} .. {panel.index[-1].date()}  ({len(panel)} weeks)
**Walk-forward:** train < 2025-01, test >= 2025-01

---

## Verdict: **{verdict}**

Recommended params (best in-sample by Sharpe): **lookback = {best_lm} months, min_return = {best_mr}%**, top {TOP_N} concurrent, weekly Monday rebalance.

> Time-series momentum: each week, rank the basket by trailing return, go long
> the strongest uptrends / short the strongest downtrends, hold the top {TOP_N}.
> Costs modeled as round-trip bps of notional on turnover (majors 2-3 bps,
> USDZAR 15 bps, USDTRY 35 bps).

## Walk-forward results

| Period | Sharpe | Ann. return | Total | Win rate | Max DD | Weeks |
|--------|--------|-------------|-------|----------|--------|-------|
| In-sample (2020-2024) | {m_is['sharpe']:.2f} | {m_is['ann_return']*100:+.1f}% | {m_is['total_return']*100:+.1f}% | {m_is['win_rate']*100:.0f}% | {m_is['max_dd']*100:.1f}% | {m_is['n']} |
| **Out-of-sample (2025-2026)** | **{m_oos['sharpe']:.2f}** | **{m_oos['ann_return']*100:+.1f}%** | **{m_oos['total_return']*100:+.1f}%** | {m_oos['win_rate']*100:.0f}% | {m_oos['max_dd']*100:.1f}% | {m_oos['n']} |

## Monte Carlo (10,000 bootstrap resamples of the OOS weekly-return sequence)

| Metric | Value |
|--------|-------|
| Total return — median | {mc['median_total']*100:+.1f}% |
| Total return — 5th percentile | {mc['p5_total']*100:+.1f}% |
| Total return — 95th percentile | {mc['p95_total']*100:+.1f}% |
| Sharpe — median | {mc['median_sharpe']:.2f} |
| Sharpe — 5th percentile | {mc['p5_sharpe']:.2f} |
| P(negative OOS total) | {mc['p_negative']*100:.0f}% |

## Top in-sample parameter sets (by Sharpe)

| Lookback | Min return | IS Sharpe | IS ann. return |
|----------|-----------|-----------|----------------|
{top_rows}

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
""")
    print(f"\nReport written to {report}")


if __name__ == "__main__":
    main()
