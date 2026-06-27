#!/usr/bin/env python3
"""
Monte Carlo Straddle Optimization — Remaining US Events
========================================================

Tests three previously-disabled US event types:
  1. Unemployment Claims (weekly, ~339 events)
  2. ISM Manufacturing PMI (monthly, ~78 events)
  3. Retail Sales m/m (monthly, ~78 events)

For each event type, tests on active pairs (USDZAR, USDTRY, AUDUSD):
  - Full-sample grid search at default spread
  - Walk-forward: Train 2020-2023, Test 2024-2026
  - Spread sensitivity at 7 levels

Usage:
  python scripts/mc_remaining_us.py
"""

from __future__ import annotations

import time

import numpy as np
from loguru import logger

from monte_carlo_dukascopy import (
    CONFIDENCE_LEVEL,
    DATA_DIR,
    DISTANCE_RANGE,
    N_BOOTSTRAP,
    PIP_SIZES,
    SL_RANGE,
    TP_RANGE,
    bootstrap_metrics,
    load_dukascopy_data,
    simulate_straddle,
)

PIP_SIZES.setdefault("AUDUSD", 0.0001)

EVENT_TYPES = {
    "Unemployment Claims": {"spread_default": 1.5},
    "ISM Manufacturing PMI": {"spread_default": 1.5},
    "Retail Sales": {"spread_default": 1.5},
}

PAIRS = {
    "USDZAR": {"spread_default": 50.0, "spreads": [30, 40, 50, 60, 70, 80]},
    "USDTRY": {"spread_default": 50.0, "spreads": [30, 40, 50, 60, 70, 80]},
    "AUDUSD": {"spread_default": 1.5, "spreads": [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]},
}

TRAIN_YEARS = [2020, 2021, 2022, 2023]
TEST_YEARS = [2024, 2025, 2026]


def load_filtered(pair: str, wanted: set[str]) -> dict[str, dict]:
    all_events = load_dukascopy_data(pair)
    filtered = {k: v for k, v in all_events.items() if v["event_name"] in wanted}

    by_type: dict[str, int] = {}
    for v in filtered.values():
        by_type[v["event_name"]] = by_type.get(v["event_name"], 0) + 1
    for name, count in sorted(by_type.items()):
        logger.info(f"  {name}: {count}")
    logger.info(f"Total: {len(filtered)} events")
    return filtered


def filter_years(data: dict[str, dict], years: list[int]) -> dict[str, dict]:
    return {k: v for k, v in data.items() if int(v["event_date"][:4]) in years}


def grid_search(
    data: dict[str, dict], pair: str, spread: float, n_comparisons: int = 1
) -> list[dict]:
    results = []
    for dist in DISTANCE_RANGE:
        for tp in TP_RANGE:
            for sl in SL_RANGE:
                all_pnl = []
                for key, event_data in data.items():
                    trades = simulate_straddle(
                        bars=event_data["bars"],
                        event_utc_str=event_data["event_utc"],
                        pair=pair,
                        distance_pips=float(dist),
                        tp_pips=float(tp),
                        sl_pips=float(sl),
                        spread_pips=spread,
                    )
                    for t in trades:
                        if t.triggered:
                            all_pnl.append(t.pnl_pips)

                if len(all_pnl) < 3:
                    continue

                pnl_arr = np.array(all_pnl)
                metrics = bootstrap_metrics(pnl_arr, n_comparisons=n_comparisons)
                results.append({
                    "distance": float(dist),
                    "tp": float(tp),
                    "sl": float(sl),
                    "spread": spread,
                    "score": metrics["ci_low"],
                    **metrics,
                })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def walk_forward(data: dict[str, dict], pair: str, spread: float) -> dict:
    train = filter_years(data, TRAIN_YEARS)
    test = filter_years(data, TEST_YEARS)

    if len(train) < 5:
        return {"status": "insufficient_train_data", "train_n": len(train)}

    train_results = grid_search(train, pair, spread)
    if not train_results:
        return {"status": "no_results"}

    best = train_results[0]
    opt = {"distance": best["distance"], "tp": best["tp"], "sl": best["sl"]}

    test_results = grid_search(test, pair, spread)
    test_match = [r for r in test_results
                  if r["distance"] == opt["distance"]
                  and r["tp"] == opt["tp"]
                  and r["sl"] == opt["sl"]]

    oos = test_match[0] if test_match else {
        "mean_pnl": 0, "sharpe": 0, "win_rate": 0, "n_trades": 0,
        "ci_low": 0, "ci_high": 0, "profit_factor": 0, "cvar_5": 0,
    }

    is_ci_low = best["ci_low"]
    oos_pnl = oos.get("mean_pnl", 0)
    if is_ci_low > 0 and oos_pnl > 0:
        verdict = "PASS"
    elif is_ci_low > 0:
        verdict = "FAIL (overfit)"
    else:
        verdict = "FAIL (no edge)"

    return {
        "status": "ok",
        "params": opt,
        "is": best,
        "oos": oos,
        "verdict": verdict,
        "train_n": len(train),
        "test_n": len(test),
    }


def year_breakdown(
    data: dict[str, dict], pair: str, params: dict, spread: float
) -> dict[int, dict]:
    results = {}
    for yr in range(2020, 2027):
        yr_data = filter_years(data, [yr])
        pnls = []
        for key, event_data in yr_data.items():
            trades = simulate_straddle(
                bars=event_data["bars"],
                event_utc_str=event_data["event_utc"],
                pair=pair,
                distance_pips=params["distance"],
                tp_pips=params["tp"],
                sl_pips=params["sl"],
                spread_pips=spread,
            )
            for t in trades:
                if t.triggered:
                    pnls.append(t.pnl_pips)
        if pnls:
            arr = np.array(pnls)
            results[yr] = {
                "mean_pnl": float(arr.mean()),
                "win_rate": float(np.mean(arr > 0)),
                "n": len(pnls),
            }
    return results


def main():
    lines = [
        "# Monte Carlo Optimization — Remaining US Events",
        "",
        "**Date**: June 2026",
        "**Script**: `scripts/mc_remaining_us.py`",
        "**Data source**: Dukascopy Bank SA (1-minute OHLCV, bid-side)",
        f"**Grid**: {len(DISTANCE_RANGE) * len(TP_RANGE) * len(SL_RANGE)} parameter combinations",
        f"**Bootstrap**: {N_BOOTSTRAP:,} resamples, {CONFIDENCE_LEVEL*100:.0f}% CI",
        "**Walk-forward**: Train 2020-2023, Test 2024-2026",
        "",
    ]

    for event_name, event_cfg in EVENT_TYPES.items():
        lines += [f"## {event_name}", ""]

        for pair, pair_cfg in PAIRS.items():
            logger.info(f"=== {event_name} on {pair} ===")
            data = load_filtered(pair, {event_name})

            if len(data) < 5:
                logger.warning(f"Only {len(data)} events, skipping")
                lines += [f"### {pair}", "", "Insufficient data.", ""]
                continue

            spread = pair_cfg["spread_default"]
            t0 = time.time()

            # Full-sample grid search
            logger.info(f"Full-sample grid search (spread={spread})...")
            full_results = grid_search(data, pair, spread)

            lines += [f"### {pair}", ""]

            if full_results:
                best = full_results[0]
                logger.info(
                    f"  Best: D={best['distance']:.0f} TP={best['tp']:.0f} SL={best['sl']:.0f} "
                    f"E[PnL]={best['mean_pnl']:+.1f} CI=[{best['ci_low']:+.1f},{best['ci_high']:+.1f}] "
                    f"Sharpe={best['sharpe']:.2f} N={best['n_trades']}"
                )
                lines += [
                    f"**Full-sample optimal** (spread={spread}): "
                    f"D={best['distance']:.0f} TP={best['tp']:.0f} SL={best['sl']:.0f}",
                    f"E[P&L]={best['mean_pnl']:+.1f}, CI=[{best['ci_low']:+.1f}, {best['ci_high']:+.1f}], "
                    f"Sharpe={best['sharpe']:.2f}, WR={best['win_rate']*100:.1f}%, "
                    f"PF={best['profit_factor']:.2f}, N={best['n_trades']}",
                    "",
                ]

                # Year breakdown
                yb = year_breakdown(
                    data, pair,
                    {"distance": best["distance"], "tp": best["tp"], "sl": best["sl"]},
                    spread,
                )
                if yb:
                    lines += [
                        "#### Year-by-Year",
                        "",
                        "| Year | E[P&L] | Win Rate | N |",
                        "|------|--------|----------|---|",
                    ]
                    for yr in sorted(yb):
                        y = yb[yr]
                        lines.append(
                            f"| {yr} | {y['mean_pnl']:+.1f} | {y['win_rate']*100:.0f}% | {y['n']} |"
                        )
                    lines.append("")
            else:
                lines += ["No profitable parameter combination found.", ""]
                elapsed = time.time() - t0
                logger.info(f"  {pair} completed in {elapsed:.0f}s (no results)")
                continue

            # Walk-forward at multiple spread levels
            spreads = pair_cfg["spreads"]
            lines += [
                "#### Spread Sensitivity + Walk-Forward",
                "",
                "| Spread | Best Params | IS E[P&L] | IS CI | IS Sharpe | IS N | OOS E[P&L] | OOS Sharpe | OOS WR | OOS N | Verdict |",
                "|--------|-------------|-----------|-------|-----------|------|------------|------------|--------|-------|---------|",
            ]

            for sp in spreads:
                logger.info(f"  Spread={sp}...")
                wf = walk_forward(data, pair, sp)

                if wf["status"] != "ok":
                    lines.append(
                        f"| {sp} | — | — | — | — | — | — | — | — | — | {wf['status']} |"
                    )
                    continue

                p = wf["params"]
                is_d = wf["is"]
                oos = wf["oos"]
                lines.append(
                    f"| {sp} | {p['distance']:.0f}/{p['tp']:.0f}/{p['sl']:.0f} | "
                    f"{is_d['mean_pnl']:+.1f} | [{is_d['ci_low']:+.1f}, {is_d['ci_high']:+.1f}] | "
                    f"{is_d['sharpe']:.2f} | {is_d['n_trades']} | "
                    f"{oos.get('mean_pnl', 0):+.1f} | {oos.get('sharpe', 0):.2f} | "
                    f"{oos.get('win_rate', 0)*100:.1f}% | {oos.get('n_trades', 0)} | {wf['verdict']} |"
                )
                logger.info(
                    f"    WF: {p['distance']:.0f}/{p['tp']:.0f}/{p['sl']:.0f} "
                    f"IS={is_d['mean_pnl']:+.1f} OOS={oos.get('mean_pnl', 0):+.1f} -> {wf['verdict']}"
                )

            elapsed = time.time() - t0
            logger.info(f"  {pair} completed in {elapsed:.0f}s")
            lines.append("")

    # Recommendation
    lines += [
        "## Recommendation",
        "",
        "TBD based on results above.",
        "",
    ]

    report = "\n".join(lines)
    print("\n" + report)

    report_path = DATA_DIR / "MC_REMAINING_US_REPORT.md"
    with open(report_path, "w") as f:
        f.write(report + "\n")
    logger.info(f"Report saved to {report_path}")


if __name__ == "__main__":
    main()
