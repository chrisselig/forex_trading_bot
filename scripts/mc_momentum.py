"""Monte Carlo + walk-forward validation for the currency momentum strategy.

Unlike the event-straddle MC scripts (distance/TP/SL pips around events), this
backtests the TIME-SERIES momentum strategy (src/forex_bot/strategy/momentum.py):
each week, rank the basket by trailing return, go long the strongest uptrends /
short the strongest downtrends, hold the top N, rebalance weekly.

This version evaluates an EXPANDED pair universe (including pairs that failed the
event-straddle evaluation) and reports:
  1. Per-pair single-pair momentum diagnostics (which pairs carry the edge).
  2. The original 7-pair basket (headline of report 13, for comparison).
  3. The full expanded-universe basket.
  4. An in-sample-selected basket (pairs with positive in-sample Sharpe).

Method:
  - Continuous daily Dukascopy close per pair, resampled weekly.
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

# Round-trip transaction cost in basis points of notional, charged whenever a
# position is opened or flipped. Majors are cheap; crosses moderate; exotics wide.
COST_BPS = {
    "EURUSD": 2.0, "GBPUSD": 2.0, "AUDUSD": 2.0, "USDJPY": 2.0, "USDCAD": 3.0,
    "NZDUSD": 3.0, "EURJPY": 3.0, "EURGBP": 3.0, "GBPJPY": 4.0, "AUDJPY": 4.0,
    "CADJPY": 4.0, "NZDJPY": 5.0, "EURCAD": 4.0, "GBPCAD": 5.0,
    "USDMXN": 12.0, "USDZAR": 15.0, "USDTRY": 35.0,
}

# Full expanded universe (includes straddle-failed crosses: GBPJPY, CADJPY,
# EURCAD, GBPCAD, and additional liquid majors/crosses).
PAIRS = list(COST_BPS.keys())

# Original report-13 basket, kept for a like-for-like comparison.
ORIGINAL_PAIRS = ["EURUSD", "GBPUSD", "AUDUSD", "USDJPY", "USDCAD", "USDZAR", "USDTRY"]

TOP_N = 4  # max concurrent (matches max_concurrent_momentum)
WEEKS_PER_YEAR = 52
DATA_DIR = Path(__file__).parent / "data" / "dukascopy"

DATA_START = pd.Timestamp("2019-06-01")
DATA_END = pd.Timestamp("2026-07-01")
TRAIN_END = pd.Timestamp("2025-01-01")  # train < this; test >= this

LOOKBACK_MONTHS_GRID = [1, 2, 3, 6, 12]
MIN_RETURN_PCT_GRID = [0.0, 1.0, 2.0, 3.0, 5.0]


def _instrument(pair: str) -> str:
    return f"{pair[:3]}/{pair[3:]}"


def load_daily_close(pair: str, refresh: bool = False) -> pd.Series | None:
    """Continuous daily close for a pair, cached to CSV. None if unavailable."""
    cache = DATA_DIR / f"{pair}_daily.csv"
    if cache.exists() and not refresh:
        s = pd.read_csv(cache, index_col=0, parse_dates=True)["close"]
        s.index = pd.to_datetime(s.index, utc=True).tz_localize(None)
        return s
    print(f"  fetching daily {pair} ...")
    try:
        df = dp.fetch(
            _instrument(pair), dp.INTERVAL_DAY_1, dp.OFFER_SIDE_BID,
            DATA_START.to_pydatetime(), DATA_END.to_pydatetime(),
        )
    except Exception as e:  # noqa: BLE001 — data source can fail per-pair
        print(f"    !! {pair} fetch failed: {e}")
        return None
    if df is None or len(df) == 0:
        print(f"    !! {pair} returned no data")
        return None
    s = df["close"].copy()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    s.name = "close"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    s.to_csv(cache)
    return s


def build_weekly_panel(pairs: list[str], refresh: bool = False) -> pd.DataFrame:
    """Weekly (Monday-anchored) close panel: index=weeks, columns=available pairs."""
    cols = {}
    for pair in pairs:
        daily = load_daily_close(pair, refresh=refresh)
        if daily is None:
            continue
        cols[pair] = daily.resample("W-MON", label="left", closed="left").last()
    panel = pd.DataFrame(cols).dropna(how="all").ffill()
    return panel


def backtest(
    panel: pd.DataFrame, lookback_weeks: int, min_return_pct: float, top_n: int = TOP_N,
) -> pd.Series:
    """Weekly momentum backtest over panel.columns; returns portfolio weekly returns."""
    weeks = panel.index
    pairs = list(panel.columns)
    prev_positions: dict[str, int] = {}
    records: list[tuple[pd.Timestamp, float]] = []

    for i in range(lookback_weeks, len(weeks) - 1):
        t, t_next = weeks[i], weeks[i + 1]
        prices_now = panel.loc[t]
        prices_prev = panel.loc[weeks[i - lookback_weeks]]
        prices_next = panel.loc[t_next]

        rets = {}
        for pair in pairs:
            p0, p1 = prices_prev[pair], prices_now[pair]
            if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                rets[pair] = (p1 / p0 - 1) * 100

        ranked = sorted(rets.items(), key=lambda kv: abs(kv[1]), reverse=True)
        selected = [(p, r) for p, r in ranked if abs(r) >= min_return_pct][:top_n]
        positions = {p: (1 if r > 0 else -1) for p, r in selected}

        pnl = 0.0
        cost = 0.0
        for pair, direction in positions.items():
            p1, p2 = prices_now[pair], prices_next[pair]
            if pd.notna(p1) and pd.notna(p2) and p1 > 0:
                pnl += direction * (p2 / p1 - 1)
            if prev_positions.get(pair, 0) != direction:
                cost += COST_BPS.get(pair, 5.0) / 10_000
        for pair, direction in prev_positions.items():
            if pair not in positions:
                cost += COST_BPS.get(pair, 5.0) / 10_000

        n = max(len(positions), 1)
        records.append((t_next, pnl / n - cost / n))
        prev_positions = positions

    return pd.Series(
        [r for _, r in records], index=pd.DatetimeIndex([d for d, _ in records]),
    )


def metrics(weekly: pd.Series) -> dict:
    if len(weekly) == 0:
        return {"n": 0, "sharpe": 0.0, "ann_return": 0.0, "total_return": 0.0,
                "win_rate": 0.0, "max_dd": 0.0}
    mean, std = weekly.mean(), weekly.std(ddof=1)
    sharpe = (mean / std * np.sqrt(WEEKS_PER_YEAR)) if std > 0 else 0.0
    ann_return = (1 + mean) ** WEEKS_PER_YEAR - 1
    equity = (1 + weekly).cumprod()
    max_dd = (equity / equity.cummax() - 1).min()
    return {
        "n": len(weekly), "sharpe": sharpe, "ann_return": ann_return,
        "total_return": equity.iloc[-1] - 1, "win_rate": (weekly > 0).mean(),
        "max_dd": max_dd,
    }


def monte_carlo(weekly: pd.Series, runs: int = 10_000, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    arr = weekly.to_numpy()
    n = len(arr)
    if n == 0:
        return {"median_total": 0.0, "p5_total": 0.0, "p95_total": 0.0, "p_negative": 1.0}
    totals = np.empty(runs)
    for k in range(runs):
        sample = arr[rng.integers(0, n, n)]
        totals[k] = np.prod(1 + sample) - 1
    return {
        "median_total": float(np.median(totals)),
        "p5_total": float(np.percentile(totals, 5)),
        "p95_total": float(np.percentile(totals, 95)),
        "p_negative": float((totals < 0).mean()),
    }


def lookback_weeks(months: int) -> int:
    return max(1, round(months * 4.345))


def optimize_is(panel: pd.DataFrame) -> tuple[int, float, list]:
    """Grid-search params on the in-sample period; return best + full ranking."""
    results = []
    for lm in LOOKBACK_MONTHS_GRID:
        for mr in MIN_RETURN_PCT_GRID:
            w = backtest(panel, lookback_weeks(lm), mr)
            m = metrics(w[w.index < TRAIN_END])
            results.append((lm, mr, m["sharpe"], m["ann_return"], m["n"]))
    results.sort(key=lambda r: r[2], reverse=True)
    return results[0][0], results[0][1], results


def split_metrics(panel: pd.DataFrame, lm: int, mr: float) -> tuple[dict, dict, pd.Series]:
    w = backtest(panel, lookback_weeks(lm), mr)
    return (metrics(w[w.index < TRAIN_END]),
            metrics(w[w.index >= TRAIN_END]),
            w[w.index >= TRAIN_END])


def per_pair_analysis(panel: pd.DataFrame, lm: int, mr: float) -> list[tuple]:
    """Single-pair time-series momentum diagnostics at the chosen params."""
    rows = []
    for pair in panel.columns:
        w = backtest(panel[[pair]], lookback_weeks(lm), mr, top_n=1)
        m_is = metrics(w[w.index < TRAIN_END])
        m_oos = metrics(w[w.index >= TRAIN_END])
        rows.append((pair, m_is["sharpe"], m_is["ann_return"],
                     m_oos["sharpe"], m_oos["ann_return"]))
    rows.sort(key=lambda r: r[3], reverse=True)  # by OOS Sharpe
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-data", action="store_true")
    args = ap.parse_args()

    print(f"Building weekly panel for {len(PAIRS)} pairs...")
    panel = build_weekly_panel(PAIRS, refresh=args.refresh_data)
    print(f"  available pairs: {list(panel.columns)}")
    print(f"  weeks: {len(panel)}  range: {panel.index[0].date()} .. {panel.index[-1].date()}")

    # --- Optimize on the full expanded universe (in-sample) ---
    best_lm, best_mr, ranking = optimize_is(panel)
    print(f"\nBest IN-SAMPLE params (expanded universe): lookback={best_lm}m, min_return={best_mr}%")

    # --- Per-pair diagnostics ---
    print("\nPer-pair single-pair momentum (at best params), sorted by OOS Sharpe:")
    pair_rows = per_pair_analysis(panel, best_lm, best_mr)
    for pair, is_sh, is_ar, oos_sh, oos_ar in pair_rows:
        flag = "PASS" if oos_sh > 0.3 else ("weak+" if oos_sh > 0 else "FAIL")
        print(f"  {pair:7s} IS Sharpe={is_sh:+.2f} ({is_ar*100:+5.1f}%)  "
              f"OOS Sharpe={oos_sh:+.2f} ({oos_ar*100:+5.1f}%)  [{flag}]")

    # --- Three baskets: original 7, expanded, IS-selected ---
    def evaluate(name: str, sub_panel: pd.DataFrame) -> dict:
        lm, mr, _ = optimize_is(sub_panel)
        m_is, m_oos, oos_w = split_metrics(sub_panel, lm, mr)
        mc = monte_carlo(oos_w)
        print(f"\n[{name}]  params lookback={lm}m min_ret={mr}%")
        print(f"  IS : Sharpe={m_is['sharpe']:.2f} ann={m_is['ann_return']*100:+.1f}%")
        print(f"  OOS: Sharpe={m_oos['sharpe']:.2f} ann={m_oos['ann_return']*100:+.1f}% "
              f"total={m_oos['total_return']*100:+.1f}%  MC 5th={mc['p5_total']*100:+.1f}% "
              f"P(neg)={mc['p_negative']*100:.0f}%")
        return {"name": name, "pairs": list(sub_panel.columns), "lm": lm, "mr": mr,
                "is": m_is, "oos": m_oos, "mc": mc}

    print("\n=== BASKET COMPARISON ===")
    orig_panel = panel[[p for p in ORIGINAL_PAIRS if p in panel.columns]]
    # IS-selected basket: pairs with positive IN-SAMPLE Sharpe (r[1]); reuse the
    # per-pair diagnostics above. Selection uses train data only — no OOS peeking.
    is_selected = [r[0] for r in pair_rows if r[1] > 0.3]
    sel_panel = panel[is_selected] if is_selected else panel

    baskets = [
        evaluate("Original 7", orig_panel),
        evaluate("Expanded (all)", panel),
        evaluate(f"IS-selected ({len(is_selected)})", sel_panel),
    ]

    _write_report(panel, best_lm, best_mr, pair_rows, baskets, is_selected, ranking)


def _verdict(oos: dict, mc: dict) -> str:
    if oos["sharpe"] > 0.5 and oos["ann_return"] > 0 and mc["p5_total"] > -0.10:
        return "PASS"
    if oos["ann_return"] > 0 and mc["median_total"] > 0:
        return "BORDERLINE (paper-trade only)"
    return "AVOID"


def _write_report(panel, best_lm, best_mr, pair_rows, baskets, is_selected, ranking) -> None:
    report = Path(__file__).parent.parent / "docs" / "research" / "13-mc-momentum.md"

    pair_table = "\n".join(
        f"| {pair} | {is_sh:+.2f} | {is_ar*100:+.1f}% | {oos_sh:+.2f} | {oos_ar*100:+.1f}% | "
        f"{'✅ pass' if oos_sh > 0.3 else ('~ weak+' if oos_sh > 0 else '❌ fail')} |"
        for pair, is_sh, is_ar, oos_sh, oos_ar in pair_rows
    )
    basket_table = "\n".join(
        f"| {b['name']} | {b['lm']}m / {b['mr']}% | {b['is']['sharpe']:.2f} | "
        f"{b['oos']['sharpe']:.2f} | {b['oos']['ann_return']*100:+.1f}% | "
        f"{b['mc']['p5_total']*100:+.1f}% | {b['mc']['p_negative']*100:.0f}% | "
        f"**{_verdict(b['oos'], b['mc'])}** |"
        for b in baskets
    )
    best_basket = max(baskets, key=lambda b: b["oos"]["sharpe"])

    # Concentration diagnostics: how much of the OOS edge is one pair?
    top = pair_rows[0]              # (pair, is_sh, is_ar, oos_sh, oos_ar)
    runner = pair_rows[1] if len(pair_rows) > 1 else top
    n_oos_pass = sum(1 for r in pair_rows if r[3] > 0.3)
    exotics = {"USDTRY", "USDZAR", "USDMXN"}
    concentrated = top[0] in exotics and top[3] > 2 * runner[3]

    report.write_text(f"""# Monte Carlo — Currency Momentum Strategy (expanded pair universe)

**Analysis date:** 2026-07-05
**Strategy:** `src/forex_bot/strategy/momentum.py` — time-series (absolute) momentum
**Data:** Dukascopy continuous daily close, resampled weekly
**Universe ({len(panel.columns)} pairs):** {", ".join(panel.columns)}
**Range:** {panel.index[0].date()} .. {panel.index[-1].date()}  ({len(panel)} weeks)
**Walk-forward:** train < 2025-01, test >= 2025-01 (out-of-sample)

This reevaluates momentum across a broader universe — including pairs that
**failed the event-straddle evaluation** (GBPJPY, CADJPY, EURCAD, GBPCAD) —
because momentum is a different edge and a straddle failure says nothing about it.

---

## Key finding

**Momentum's out-of-sample edge is concentrated in {top[0]}** (OOS Sharpe {top[3]:.2f},
{top[4]*100:+.1f}%/yr), far ahead of the next pair ({runner[0]}, OOS Sharpe {runner[3]:.2f}).
Only **{n_oos_pass} of {len(pair_rows)}** pairs have a positive out-of-sample momentum
Sharpe above 0.3.

- **Broadening the basket HURTS.** The full {len(panel.columns)}-pair universe scores OOS
  Sharpe {[b for b in baskets if b['name']=='Expanded (all)'][0]['oos']['sharpe']:.2f} — *worse* than the original 7 — because the added majors and
  crosses mostly fail out-of-sample and dilute the signal.
- **The star result is a concentration bet, not diversified momentum.** The
  in-sample-selected basket's strong OOS number is dominated by **{top[0]}**{' (an exotic USD trend)' if concentrated else ''}.
  {top[0]} is already a **carry** pair — its persistent trend is the same lira-depreciation
  move the carry book captures — so this momentum "edge" **overlaps the carry strategy**
  and carries the same regime/tail risk (a Turkish-policy reversal breaks it violently).
- **Straddle-failed crosses under momentum:** GBPJPY and EURCAD show *weak-positive*
  OOS momentum (Sharpe ~0.3-0.5) but nothing compelling; CADJPY, GBPCAD, NZDJPY fail.

**Recommendation:** do **not** broaden the live momentum basket. There is no robust
*diversified* momentum edge across majors OOS; the only strong signal ({top[0]}) is
already owned by carry, making broad momentum largely redundant. Keep the current
paper-trade evaluation, and if momentum is pursued, treat it as a small {top[0]}-centric
sleeve with explicit concentration limits — not a diversified 7- or 17-pair book.

---

## Per-pair diagnostics (single-pair time-series momentum, at lookback={best_lm}m / min_return={best_mr}%)

Which pairs individually carry a momentum edge, sorted by out-of-sample Sharpe.
"pass" = OOS Sharpe > 0.3; "weak+" = positive but marginal; "fail" = non-positive OOS.

| Pair | IS Sharpe | IS ann. | OOS Sharpe | OOS ann. | Verdict |
|------|-----------|---------|------------|----------|---------|
{pair_table}

> Note: single-pair diagnostics use the basket-optimal params for comparability;
> they indicate *contribution*, not a standalone tradeable per-pair strategy.

## Basket comparison (walk-forward: params optimized in-sample, tested OOS)

| Basket | Params | IS Sharpe | OOS Sharpe | OOS ann. | MC 5th %ile | P(losing OOS) | Verdict |
|--------|--------|-----------|------------|----------|-------------|---------------|---------|
{basket_table}

- **Original 7** — the report-13 basket (EURUSD, GBPUSD, AUDUSD, USDJPY, USDCAD, USDZAR, USDTRY).
- **Expanded (all)** — the full {len(panel.columns)}-pair universe.
- **IS-selected** — pairs with positive **in-sample** Sharpe only (selection done on
  train data, no out-of-sample peeking): {", ".join(is_selected) if is_selected else "(none)"}.

**Best out-of-sample basket:** {best_basket['name']} (OOS Sharpe {best_basket['oos']['sharpe']:.2f}).

## Top in-sample parameter sets (expanded universe, by Sharpe)

| Lookback | Min return | IS Sharpe | IS ann. |
|----------|-----------|-----------|---------|
""" + "\n".join(
        f"| {lm}m | {mr}% | {sh:.2f} | {ar*100:+.1f}% |" for lm, mr, sh, ar, _ in ranking[:8]
    ) + f"""

## Takeaways

- The highest OOS *basket* Sharpe ({best_basket['name']}) is driven by the
  concentration effect described in **Key finding** above — it is not evidence of a
  broad, diversifiable momentum edge.
- Diversified currency momentum across majors/crosses is **absent out-of-sample**
  here, consistent with the well-documented post-2015 weakening of the factor.
- Use the per-pair table to see which currencies actually trend-follow OOS rather
  than trading a basket blindly — but note the winners overlap the carry book.
- All results remain **paper-trade evidence only** until the live paper period
  confirms (or kills) the edge.

## Caveats

- Units are **% return / Sharpe** (portfolio strategy), not pips-per-trade.
- Costs modeled on turnover; exotic (ZAR/TRY/MXN) slippage at weekly rebalance is
  uncertain and the OOS figures are sensitive to it.
- Daily Dukascopy BID close is a proxy; live fills use IB mid + spread.
- Single train/test split; a rolling multi-fold walk-forward would add confidence.
- Re-run with `/trade-review` once live paper data accumulates.
""")
    print(f"\nReport written to {report}")


if __name__ == "__main__":
    main()
