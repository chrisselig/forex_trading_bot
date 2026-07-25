"""Fast replacement for the killed mc_remaining_us / mc_audusd_explore runs.

Same grids (DISTANCE x TP x SL), same cell-ranking criterion (bootstrap CI
lower bound), same train/test split (2020-2023 / 2024-2026, matching reports
11/12). Speedup: cells are pre-ranked by a normal-approximation CI lower bound
(mean - 1.96*std/sqrt(n)); the top 25 cells are then re-ranked with the full
10k bootstrap and the winner reported. Prints incrementally (survives kills).

Usage: mc_grids_fast.py usdtry | audusd
"""
from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, "/home/doopdeep/00_data_projects/forex_trading_bot/scripts")

from monte_carlo_dukascopy import (  # noqa: E402
    DISTANCE_RANGE,
    SL_RANGE,
    TP_RANGE,
    bootstrap_metrics,
    load_dukascopy_data,
    simulate_straddle,
)

TRAIN_YEARS = {2020, 2021, 2022, 2023}
TEST_YEARS = {2024, 2025, 2026}
TOP_K = 25


def collect_pnls(data, pair, dist, tp, sl, spread):
    pnls = []
    for v in data.values():
        trades = simulate_straddle(
            v["bars"], v["event_utc"], pair, float(dist), float(tp), float(sl),
            spread_pips=spread,
        )
        pnls.extend(t.pnl_pips for t in trades if t.triggered)
    return np.array(pnls)


def grid_best(data, pair, spread):
    """Full grid; rank by approx CI-low, re-rank top K by bootstrap ci_low."""
    cells = []
    for dist in DISTANCE_RANGE:
        for tp in TP_RANGE:
            for sl in SL_RANGE:
                pnl = collect_pnls(data, pair, dist, tp, sl, spread)
                if len(pnl) < 3:
                    continue
                approx = pnl.mean() - 1.96 * pnl.std(ddof=1) / max(np.sqrt(len(pnl)), 1)
                cells.append((approx, int(dist), int(tp), int(sl), pnl))
    if not cells:
        return None
    cells.sort(key=lambda c: c[0], reverse=True)
    best = None
    for _, dist, tp, sl, pnl in cells[:TOP_K]:
        m = bootstrap_metrics(pnl)
        if best is None or m["ci_low"] > best[3]["ci_low"]:
            best = (dist, tp, sl, m)
    return best


def filter_years(data, years):
    return {k: v for k, v in data.items() if int(v["event_date"][:4]) in years}


def fmt(m):
    return (
        f"E={m['mean_pnl']:+6.1f} CI=[{m['ci_low']:+6.1f},{m['ci_high']:+6.1f}] "
        f"WR={m['win_rate'] * 100:4.1f}% Sh={m['sharpe']:+5.2f} N={m['n_trades']}"
    )


def analyze(pair, data, label, spread, sens_spreads):
    print(f"\n### {pair} / {label} (spread {spread}, {len(data)} events)", flush=True)
    full = grid_best(data, pair, spread)
    if full is None:
        print("  insufficient data", flush=True)
        return
    d, tp, sl, m = full
    print(f"  FULL grid best {d}/{tp}/{sl}: {fmt(m)}", flush=True)

    train = filter_years(data, TRAIN_YEARS)
    test = filter_years(data, TEST_YEARS)
    tb = grid_best(train, pair, spread)
    if tb:
        td, ttp, tsl, tm = tb
        oos_pnl = collect_pnls(test, pair, td, ttp, tsl, spread)
        if len(oos_pnl) >= 3:
            om = bootstrap_metrics(oos_pnl)
            print(f"  WF train-best {td}/{ttp}/{tsl}: IS {fmt(tm)}", flush=True)
            print(f"                              OOS {fmt(om)}", flush=True)
        else:
            print(f"  WF train-best {td}/{ttp}/{tsl}: OOS <3 trades", flush=True)

    for s in sens_spreads:
        pnl = collect_pnls(data, pair, d, tp, sl, s)
        if len(pnl) >= 3:
            sm = bootstrap_metrics(pnl)
            print(f"  spread {s:>5}: best-cell {d}/{tp}/{sl} {fmt(sm)}", flush=True)


def main():
    which = sys.argv[1]
    if which == "usdtry":
        data = load_dukascopy_data("USDTRY")
        for evt in ["Unemployment Claims", "ISM Manufacturing PMI", "Retail Sales"]:
            sub = {k: v for k, v in data.items() if v["event_name"] == evt}
            analyze("USDTRY", sub, evt, 50.0, [30.0, 80.0])
            # configured params at report-12 spread for the verdict table
            pnl = collect_pnls(sub, "USDTRY", 50, 70, 10, 50.0)
            if len(pnl) >= 3:
                print(f"  cfg 50/70/10 @ spread 50: {fmt(bootstrap_metrics(pnl))}",
                      flush=True)
    elif which == "audusd":
        data = load_dukascopy_data("AUDUSD")
        us = {"NFP", "CPI", "FOMC", "PPI", "GDP", "PCE"}
        au = {"RBA Rate Decision", "Australia CPI", "Australia Employment"}
        for label, wanted in [("US", us), ("Australia", au), ("Combined", us | au)]:
            sub = {k: v for k, v in data.items() if v["event_name"] in wanted}
            analyze("AUDUSD", sub, label, 1.5, [1.0, 2.0, 3.0, 4.0])


if __name__ == "__main__":
    main()
