#!/usr/bin/env python3
"""
Monte Carlo Straddle Optimization — AUDUSD Exploration
========================================================

Tests AUDUSD on three event sources:
  1. US events (NFP, CPI, FOMC, PPI, GDP, PCE)
  2. Australian events (RBA Rate, AU CPI, AU Employment)
  3. Combined (all events)

Previous analysis (07-mc-eurusd-audusd.md) found E[P&L]=+4.8 on US events
but N=19 (too few trades at 50/50/10) with CI spanning zero. This re-analysis:
  - Uses the full 6.5-year dataset (2020-2026)
  - Tests Australian events independently
  - Runs spread sensitivity (1.0-5.0 pips)
  - Walk-forward: Train 2020-2023, Test 2024-2026

Usage:
  python scripts/mc_audusd_explore.py
"""

from __future__ import annotations

import time
from pathlib import Path

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
    generate_heatmaps,
    load_dukascopy_data,
    simulate_straddle,
)

PAIR = "AUDUSD"
PIP_SIZES.setdefault("AUDUSD", 0.0001)

US_EVENTS = {"NFP", "CPI", "FOMC", "PPI", "GDP", "PCE"}
AU_EVENTS = {"RBA Rate Decision", "Australia CPI", "Australia Employment"}

SPREAD_RANGE = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]

TRAIN_YEARS = [2020, 2021, 2022, 2023]
TEST_YEARS = [2024, 2025, 2026]


def load_filtered(wanted: set[str]) -> dict[str, dict]:
    all_events = load_dukascopy_data(PAIR)
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


def grid_search(data: dict[str, dict], spread: float, n_comparisons: int = 1) -> list[dict]:
    results = []
    for dist in DISTANCE_RANGE:
        for tp in TP_RANGE:
            for sl in SL_RANGE:
                all_pnl = []
                for key, event_data in data.items():
                    trades = simulate_straddle(
                        bars=event_data["bars"],
                        event_utc_str=event_data["event_utc"],
                        pair=PAIR,
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


def walk_forward(data: dict[str, dict], spread: float) -> dict:
    train = filter_years(data, TRAIN_YEARS)
    test = filter_years(data, TEST_YEARS)

    if len(train) < 5:
        return {"status": "insufficient_train_data", "train_n": len(train)}

    train_results = grid_search(train, spread)
    if not train_results:
        return {"status": "no_results"}

    best = train_results[0]
    opt = {"distance": best["distance"], "tp": best["tp"], "sl": best["sl"]}

    test_results = grid_search(test, spread)
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


def event_breakdown(data: dict[str, dict], params: dict, spread: float) -> dict[str, dict]:
    by_type: dict[str, list[float]] = {}
    for key, event_data in data.items():
        trades = simulate_straddle(
            bars=event_data["bars"],
            event_utc_str=event_data["event_utc"],
            pair=PAIR,
            distance_pips=params["distance"],
            tp_pips=params["tp"],
            sl_pips=params["sl"],
            spread_pips=spread,
        )
        for t in trades:
            if t.triggered:
                by_type.setdefault(event_data["event_name"], []).append(t.pnl_pips)

    results = {}
    for name, pnls in by_type.items():
        if len(pnls) >= 3:
            results[name] = bootstrap_metrics(np.array(pnls))
    return results


def year_breakdown(data: dict[str, dict], params: dict, spread: float) -> dict[int, dict]:
    results = {}
    for yr in range(2020, 2027):
        yr_data = filter_years(data, [yr])
        pnls = []
        for key, event_data in yr_data.items():
            trades = simulate_straddle(
                bars=event_data["bars"],
                event_utc_str=event_data["event_utc"],
                pair=PAIR,
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
    sources = {
        "US": US_EVENTS,
        "Australia": AU_EVENTS,
        "Combined": US_EVENTS | AU_EVENTS,
    }

    lines = [
        "# AUDUSD Monte Carlo Exploration",
        "",
        "**Date**: June 2026",
        "**Script**: `scripts/mc_audusd_explore.py`",
        "**Data source**: Dukascopy Bank SA (1-minute OHLCV, bid-side)",
        f"**Grid**: {len(DISTANCE_RANGE) * len(TP_RANGE) * len(SL_RANGE)} parameter combinations",
        f"**Bootstrap**: {N_BOOTSTRAP:,} resamples, {CONFIDENCE_LEVEL*100:.0f}% CI",
        "**Walk-forward**: Train 2020-2023, Test 2024-2026",
        "",
    ]

    for source_name, wanted in sources.items():
        logger.info(f"=== AUDUSD on {source_name} events ===")
        data = load_filtered(wanted)
        if len(data) < 5:
            logger.warning(f"Only {len(data)} events, skipping")
            lines += [f"## {source_name} Events", "", "Insufficient data.", ""]
            continue

        # Full-sample grid at spread=1.5
        DEFAULT_SPREAD = 1.5
        logger.info(f"Full-sample grid search (spread={DEFAULT_SPREAD})...")
        t0 = time.time()
        full_results = grid_search(data, DEFAULT_SPREAD)

        if full_results:
            best = full_results[0]
            logger.info(
                f"  Best: D={best['distance']:.0f} TP={best['tp']:.0f} SL={best['sl']:.0f} "
                f"E[PnL]={best['mean_pnl']:+.1f} CI=[{best['ci_low']:+.1f},{best['ci_high']:+.1f}] "
                f"Sharpe={best['sharpe']:.2f} N={best['n_trades']}"
            )

        lines += [
            f"## {source_name} Events",
            "",
        ]

        if full_results:
            best = full_results[0]
            lines += [
                f"**Full-sample optimal** (spread=1.5): D={best['distance']:.0f} TP={best['tp']:.0f} SL={best['sl']:.0f}",
                f"E[P&L]={best['mean_pnl']:+.1f}, CI=[{best['ci_low']:+.1f}, {best['ci_high']:+.1f}], "
                f"Sharpe={best['sharpe']:.2f}, WR={best['win_rate']*100:.1f}%, "
                f"PF={best['profit_factor']:.2f}, N={best['n_trades']}",
                "",
            ]

            # Per-event breakdown
            et = event_breakdown(data, {"distance": best["distance"], "tp": best["tp"], "sl": best["sl"]}, DEFAULT_SPREAD)
            if et:
                lines += [
                    f"### Per-Event Breakdown (Params: {best['distance']:.0f}/{best['tp']:.0f}/{best['sl']:.0f})",
                    "",
                    "| Event | E[P&L] | 95% CI | Win Rate | Sharpe | PF | N |",
                    "|-------|--------|--------|----------|--------|----|---|",
                ]
                for name, m in sorted(et.items()):
                    lines.append(
                        f"| {name} | {m['mean_pnl']:+.1f} | "
                        f"[{m['ci_low']:+.1f}, {m['ci_high']:+.1f}] | "
                        f"{m['win_rate']*100:.1f}% | {m['sharpe']:.2f} | "
                        f"{m['profit_factor']:.2f} | {m['n_trades']} |"
                    )
                lines.append("")

            # Year breakdown
            yb = year_breakdown(data, {"distance": best["distance"], "tp": best["tp"], "sl": best["sl"]}, DEFAULT_SPREAD)
            if yb:
                lines += [
                    "### Year-by-Year",
                    "",
                    "| Year | E[P&L] | Win Rate | N |",
                    "|------|--------|----------|---|",
                ]
                for yr in sorted(yb):
                    y = yb[yr]
                    lines.append(f"| {yr} | {y['mean_pnl']:+.1f} | {y['win_rate']*100:.0f}% | {y['n']} |")
                lines.append("")

            # Heatmaps
            generate_heatmaps(full_results, f"AUDUSD_{source_name.lower()}", DATA_DIR)

        # Spread sensitivity with walk-forward
        lines += [
            f"### Spread Sensitivity + Walk-Forward",
            "",
            "| Spread | Best Params | IS E[P&L] | IS CI | IS Sharpe | IS N | OOS E[P&L] | OOS Sharpe | OOS WR | OOS N | Verdict |",
            "|--------|-------------|-----------|-------|-----------|------|------------|------------|--------|-------|---------|",
        ]

        for spread in SPREAD_RANGE:
            logger.info(f"  Spread={spread}...")
            wf = walk_forward(data, spread)

            if wf["status"] != "ok":
                lines.append(f"| {spread:.1f} | — | — | — | — | — | — | — | — | — | {wf['status']} |")
                continue

            p = wf["params"]
            is_d = wf["is"]
            oos = wf["oos"]
            lines.append(
                f"| {spread:.1f} | {p['distance']:.0f}/{p['tp']:.0f}/{p['sl']:.0f} | "
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
        logger.info(f"  {source_name} completed in {elapsed:.0f}s")
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

    report_path = DATA_DIR / "MC_AUDUSD_EXPLORE_REPORT.md"
    with open(report_path, "w") as f:
        f.write(report + "\n")
    logger.info(f"Report saved to {report_path}")


if __name__ == "__main__":
    main()
