#!/usr/bin/env python3
"""
Deep-dive: CADJPY on Japan events with spread sensitivity & extended OOS.

Tests:
  1. Train 2020-2023, test 2024-2026 (~3 years OOS vs 1.5 in original)
  2. Spread sensitivity: 1.0 to 5.0 pips in 0.5 steps
  3. Full grid search at each spread level
"""

from __future__ import annotations

import time

import numpy as np
from loguru import logger

from monte_carlo_dukascopy import (
    DATA_DIR,
    DISTANCE_RANGE,
    PIP_SIZES,
    SL_RANGE,
    TP_RANGE,
    bootstrap_metrics,
    load_dukascopy_data,
    simulate_straddle,
)

PIP_SIZES["CADJPY"] = 0.01

PAIR = "CADJPY"
JAPAN_EVENTS = {"BOJ Rate Decision", "Japan CPI"}
SPREAD_RANGE = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]

TRAIN_YEARS = [2020, 2021, 2022, 2023]
TEST_YEARS = [2024, 2025, 2026]


def load_japan_data() -> dict[str, dict]:
    all_events = load_dukascopy_data(PAIR)
    filtered = {k: v for k, v in all_events.items() if v["event_name"] in JAPAN_EVENTS}

    by_type: dict[str, int] = {}
    for v in filtered.values():
        by_type[v["event_name"]] = by_type.get(v["event_name"], 0) + 1
    for name, count in sorted(by_type.items()):
        logger.info(f"  {name}: {count} events")
    logger.info(f"Total: {len(filtered)} events")
    return filtered


def filter_years(data: dict[str, dict], years: list[int]) -> dict[str, dict]:
    return {k: v for k, v in data.items() if int(v["event_date"][:4]) in years}


def grid_search(data: dict[str, dict], spread: float) -> list[dict]:
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
                metrics = bootstrap_metrics(pnl_arr)
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


def main():
    data = load_japan_data()

    train_data = filter_years(data, TRAIN_YEARS)
    test_data = filter_years(data, TEST_YEARS)
    logger.info(f"Train: {len(train_data)} events ({TRAIN_YEARS})")
    logger.info(f"Test: {len(test_data)} events ({TEST_YEARS})")

    # Count test events by year
    by_year: dict[int, int] = {}
    for v in test_data.values():
        yr = int(v["event_date"][:4])
        by_year[yr] = by_year.get(yr, 0) + 1
    for yr, count in sorted(by_year.items()):
        logger.info(f"  OOS {yr}: {count} events")

    lines = [
        "# CADJPY / Japan Events — Deep Dive",
        "",
        "**Train**: 2020-2023 (4 years), **Test**: 2024-2026 (3 years)",
        "",
        "## Spread Sensitivity",
        "",
        "| Spread | Best Params | IS E[P&L] | IS CI | IS Sharpe | IS N | OOS E[P&L] | OOS Sharpe | OOS WR | OOS N | Verdict |",
        "|--------|-------------|-----------|-------|-----------|------|------------|------------|--------|-------|---------|",
    ]

    for spread in SPREAD_RANGE:
        logger.info(f"=== Spread: {spread} pips ===")
        t0 = time.time()

        # Train
        train_results = grid_search(train_data, spread)
        if not train_results:
            lines.append(f"| {spread:.1f} | — | — | — | — | — | — | — | — | — | NO DATA |")
            continue

        best = train_results[0]
        opt_dist = best["distance"]
        opt_tp = best["tp"]
        opt_sl = best["sl"]

        logger.info(
            f"  Train best: D={opt_dist:.0f} TP={opt_tp:.0f} SL={opt_sl:.0f} "
            f"E[PnL]={best['mean_pnl']:+.1f} CI=[{best['ci_low']:+.1f},{best['ci_high']:+.1f}] "
            f"Sharpe={best['sharpe']:.2f} N={best['n_trades']}"
        )

        # Test with train-optimal params
        test_results = grid_search(test_data, spread)
        test_match = [r for r in test_results
                      if r["distance"] == opt_dist and r["tp"] == opt_tp and r["sl"] == opt_sl]

        if test_match:
            oos = test_match[0]
            oos_pnl = oos["mean_pnl"]
            oos_sharpe = oos["sharpe"]
            oos_wr = oos["win_rate"]
            oos_n = oos["n_trades"]
        else:
            oos_pnl = oos_sharpe = oos_wr = 0
            oos_n = 0

        is_ci_low = best["ci_low"]
        if is_ci_low > 0 and oos_pnl > 0:
            verdict = "PASS"
        elif is_ci_low > 0:
            verdict = "FAIL (overfit)"
        else:
            verdict = "FAIL (no edge)"

        lines.append(
            f"| {spread:.1f} | {opt_dist:.0f}/{opt_tp:.0f}/{opt_sl:.0f} | "
            f"{best['mean_pnl']:+.1f} | [{best['ci_low']:+.1f}, {best['ci_high']:+.1f}] | "
            f"{best['sharpe']:.2f} | {best['n_trades']} | "
            f"{oos_pnl:+.1f} | {oos_sharpe:.2f} | {oos_wr*100:.1f}% | {oos_n} | {verdict} |"
        )

        elapsed = time.time() - t0
        logger.info(f"  OOS: E[PnL]={oos_pnl:+.1f} Sharpe={oos_sharpe:.2f} N={oos_n} [{elapsed:.0f}s]")

    # Also run full-sample at spread=3.0 for per-event breakdown
    lines += [
        "",
        "## Full-Sample Optimal at Spread=3.0 — Per-Event Breakdown",
        "",
    ]
    full_results = grid_search(data, 3.0)
    if full_results:
        best = full_results[0]
        lines += [
            f"**Full-sample optimal**: D={best['distance']:.0f} TP={best['tp']:.0f} SL={best['sl']:.0f}",
            f"E[P&L]={best['mean_pnl']:+.1f}, CI=[{best['ci_low']:+.1f}, {best['ci_high']:+.1f}], "
            f"Sharpe={best['sharpe']:.2f}, N={best['n_trades']}",
            "",
            "| Event | E[P&L] | 95% CI | Win Rate | Sharpe | PF | N |",
            "|-------|--------|--------|----------|--------|----|---|",
        ]

        # Per-event-type breakdown
        by_type: dict[str, list[float]] = {}
        for key, event_data in data.items():
            trades = simulate_straddle(
                bars=event_data["bars"],
                event_utc_str=event_data["event_utc"],
                pair=PAIR,
                distance_pips=best["distance"],
                tp_pips=best["tp"],
                sl_pips=best["sl"],
                spread_pips=3.0,
            )
            for t in trades:
                if t.triggered:
                    by_type.setdefault(event_data["event_name"], []).append(t.pnl_pips)

        for event_name, pnls in sorted(by_type.items()):
            if len(pnls) >= 3:
                metrics = bootstrap_metrics(np.array(pnls))
                lines.append(
                    f"| {event_name} | {metrics['mean_pnl']:+.1f} | "
                    f"[{metrics['ci_low']:+.1f}, {metrics['ci_high']:+.1f}] | "
                    f"{metrics['win_rate']*100:.1f}% | {metrics['sharpe']:.2f} | "
                    f"{metrics['profit_factor']:.2f} | {metrics['n_trades']} |"
                )

    # Per-year breakdown at spread=3.0 with full-sample optimal
    if full_results:
        best = full_results[0]
        lines += [
            "",
            "## Year-by-Year Performance (Full-Sample Optimal, Spread=3.0)",
            "",
            "| Year | E[P&L] | Win Rate | N |",
            "|------|--------|----------|---|",
        ]
        for yr in range(2020, 2027):
            yr_data = filter_years(data, [yr])
            yr_pnls = []
            for key, event_data in yr_data.items():
                trades = simulate_straddle(
                    bars=event_data["bars"],
                    event_utc_str=event_data["event_utc"],
                    pair=PAIR,
                    distance_pips=best["distance"],
                    tp_pips=best["tp"],
                    sl_pips=best["sl"],
                    spread_pips=3.0,
                )
                for t in trades:
                    if t.triggered:
                        yr_pnls.append(t.pnl_pips)
            if yr_pnls:
                arr = np.array(yr_pnls)
                wr = np.mean(arr > 0) * 100
                lines.append(f"| {yr} | {arr.mean():+.1f} | {wr:.0f}% | {len(yr_pnls)} |")
            else:
                lines.append(f"| {yr} | — | — | 0 |")

    report = "\n".join(lines)
    print("\n" + report)

    report_path = DATA_DIR / "MC_CADJPY_JAPAN_DEEP.md"
    with open(report_path, "w") as f:
        f.write(report + "\n")
    logger.info(f"Report saved to {report_path}")


if __name__ == "__main__":
    main()
