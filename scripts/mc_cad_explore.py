#!/usr/bin/env python3
"""
Monte Carlo Straddle Optimization — CAD Pair Exploration
=========================================================

Tests alternative CAD-denominated pairs (CADJPY, EURCAD, GBPCAD) on both
US economic events and Canadian economic events to find a tradeable CAD pair.

USDCAD fails walk-forward on both US events (OOS=-14.3) and Canadian events
(OOS=-10.6). These cross pairs may behave differently because:
  - CADJPY: combines CAD with JPY carry dynamics
  - EURCAD: ECB vs BOC divergence
  - GBPCAD: BOE vs BOC divergence

Each pair is tested on two event sources independently:
  1. US events (NFP, CPI, FOMC, PPI, GDP, PCE) — high-frequency, ~475 events
  2. Canadian events (BOC Rate, Canada CPI, Canada Employment) — ~208 events
  3. CADJPY additionally tested on Japanese events (BOJ Rate, Japan CPI)

Usage:
  python scripts/mc_cad_explore.py                          # All 3 pairs
  python scripts/mc_cad_explore.py --pairs CADJPY            # Single pair
  python scripts/mc_cad_explore.py --pairs CADJPY EURCAD     # Multiple pairs
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
from loguru import logger

# Import core engine from existing MC script
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

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CAD_PAIRS = ["CADJPY", "EURCAD", "GBPCAD"]

# Pip sizes for the new pairs
PIP_SIZES.update({
    "CADJPY": 0.01,
    "EURCAD": 0.0001,
    "GBPCAD": 0.0001,
})

# Event-time half-spread in pips (conservative estimates)
EVENT_SPREAD_PIPS = {
    "CADJPY": 3.0,
    "EURCAD": 3.0,
    "GBPCAD": 3.5,
}

# Event sources to test each pair against
US_EVENTS = {"NFP", "CPI", "FOMC", "PPI", "GDP", "PCE"}
CANADA_EVENTS = {"BOC Rate Decision", "Canada CPI", "Canada Employment"}
JAPAN_EVENTS = {"BOJ Rate Decision", "Japan CPI"}

# Which event sources to test per pair
PAIR_EVENT_SOURCES: dict[str, dict[str, set[str]]] = {
    "CADJPY": {
        "US": US_EVENTS,
        "Canada": CANADA_EVENTS,
        "Japan": JAPAN_EVENTS,
    },
    "EURCAD": {
        "US": US_EVENTS,
        "Canada": CANADA_EVENTS,
    },
    "GBPCAD": {
        "US": US_EVENTS,
        "Canada": CANADA_EVENTS,
    },
}

RESULTS_FILE = DATA_DIR / "optimization_results_cad_explore.json"


# ---------------------------------------------------------------------------
# Data Loading — filter by event source
# ---------------------------------------------------------------------------


def load_filtered_data(pair: str, wanted_events: set[str]) -> dict[str, dict]:
    """Load Dukascopy data filtered to specific event names."""
    all_events = load_dukascopy_data(pair)
    filtered = {k: v for k, v in all_events.items() if v["event_name"] in wanted_events}

    by_type: dict[str, int] = {}
    for v in filtered.values():
        by_type[v["event_name"]] = by_type.get(v["event_name"], 0) + 1
    for name, count in sorted(by_type.items()):
        logger.info(f"  {name}: {count} events")

    logger.info(f"Filtered {pair}: {len(filtered)} events (from {len(all_events)} total)")
    return filtered


# ---------------------------------------------------------------------------
# Grid Search
# ---------------------------------------------------------------------------


def run_grid_search(
    data: dict[str, dict],
    pair: str,
    years: list[int] | None = None,
    n_comparisons: int = 1,
) -> list[dict]:
    """Run grid search across parameter space for one pair."""
    pair_data = data
    if years:
        pair_data = {k: v for k, v in data.items()
                     if int(v["event_date"][:4]) in years}

    if len(pair_data) < 5:
        logger.warning(f"Only {len(pair_data)} events for {pair} (years={years}), skipping")
        return []

    spread = EVENT_SPREAD_PIPS.get(pair, 3.0)
    results = []
    total = len(DISTANCE_RANGE) * len(TP_RANGE) * len(SL_RANGE)
    count = 0

    for dist in DISTANCE_RANGE:
        for tp in TP_RANGE:
            for sl in SL_RANGE:
                count += 1
                all_pnl = []

                for key, event_data in pair_data.items():
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
                    "pair": pair,
                    "distance": float(dist),
                    "tp": float(tp),
                    "sl": float(sl),
                    "score": metrics["ci_low"],
                    **metrics,
                })

        if count % 100 == 0:
            logger.debug(f"  {pair}: {count}/{total} parameter combos evaluated")

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Walk-Forward Validation
# ---------------------------------------------------------------------------


def walk_forward_validate(
    data: dict[str, dict],
    pair: str,
    train_years: list[int],
    test_years: list[int],
) -> dict:
    """Train on one period, test on another."""
    train_results = run_grid_search(data, pair, years=train_years)
    if not train_results:
        return {"pair": pair, "status": "insufficient_train_data"}

    best = train_results[0]
    opt_dist = best["distance"]
    opt_tp = best["tp"]
    opt_sl = best["sl"]

    test_results = run_grid_search(data, pair, years=test_years)
    test_match = [r for r in test_results
                  if r["distance"] == opt_dist and r["tp"] == opt_tp and r["sl"] == opt_sl]

    return {
        "pair": pair,
        "optimal_params": {"distance": opt_dist, "tp": opt_tp, "sl": opt_sl},
        "in_sample": {
            "years": train_years,
            "mean_pnl": best["mean_pnl"],
            "ci_low": best["ci_low"],
            "ci_high": best["ci_high"],
            "sharpe": best["sharpe"],
            "win_rate": best["win_rate"],
            "profit_factor": best["profit_factor"],
            "cvar_5": best["cvar_5"],
            "n_trades": best["n_trades"],
        },
        "out_of_sample": {
            "years": test_years,
            **(test_match[0] if test_match else {
                "mean_pnl": 0, "sharpe": 0, "win_rate": 0, "n_trades": 0,
                "ci_low": 0, "ci_high": 0, "profit_factor": 0, "cvar_5": 0,
            }),
        },
    }


# ---------------------------------------------------------------------------
# Per-Event-Type Analysis
# ---------------------------------------------------------------------------


def analyze_by_event_type(
    data: dict[str, dict],
    pair: str,
    params: dict,
) -> dict[str, dict]:
    """Evaluate specific params broken down by event type."""
    spread = EVENT_SPREAD_PIPS.get(pair, 3.0)
    by_type: dict[str, list[float]] = {}

    for key, event_data in data.items():
        event_name = event_data["event_name"]
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
                by_type.setdefault(event_name, []).append(t.pnl_pips)

    results = {}
    for event_name, pnls in by_type.items():
        if len(pnls) >= 3:
            pnl_arr = np.array(pnls)
            metrics = bootstrap_metrics(pnl_arr)
            results[event_name] = metrics

    return results


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------


def generate_report(
    all_results: dict[str, dict[str, list[dict]]],
    wf_results: dict[str, dict[str, dict]],
    event_type_results: dict[str, dict[str, dict[str, dict]]],
    data_counts: dict[str, dict[str, dict[str, int]]],
) -> str:
    """Generate markdown report.

    Structure: all_results[pair][source] = list of grid results
    """
    lines = [
        "# Monte Carlo Optimization — CAD Pair Exploration",
        "",
        "**Date**: June 2026",
        "**Script**: `scripts/mc_cad_explore.py`",
        "**Data source**: Dukascopy Bank SA (1-minute OHLCV, bid-side)",
        "",
        "## Executive Summary",
        "",
        "Testing alternative CAD-denominated pairs as replacements for USDCAD, which",
        "fails walk-forward on both US events (OOS=-14.3) and Canadian events (OOS=-10.6).",
        "",
        "- **Pairs tested**: CADJPY, EURCAD, GBPCAD",
        "- **Event sources**: US (NFP/CPI/FOMC/PPI/GDP/PCE), Canada (BOC/CPI/Employment), Japan (BOJ/CPI, CADJPY only)",
        f"- **Grid**: {len(DISTANCE_RANGE) * len(TP_RANGE) * len(SL_RANGE)} parameter combinations",
        f"- **Bootstrap**: {N_BOOTSTRAP:,} resamples, {CONFIDENCE_LEVEL*100:.0f}% confidence intervals",
        "- **Walk-forward**: Train 2020-2024, test 2025-2026",
        "",
    ]

    # Results by pair and source
    for pair in CAD_PAIRS:
        pair_results = all_results.get(pair, {})
        if not pair_results:
            continue

        lines += [
            f"## {pair}",
            "",
            "### Optimal Parameters by Event Source",
            "",
            "| Source | Distance | TP | SL | E[P&L] | 95% CI | Win Rate | Sharpe | PF | CVaR(5%) | N |",
            "|--------|----------|----|----|--------|--------|----------|--------|----|----------|---|",
        ]

        for source, results in sorted(pair_results.items()):
            if not results:
                lines.append(f"| {source} | — | — | — | insufficient data | | | | | | |")
                continue
            best = results[0]
            lines.append(
                f"| **{source}** | {best['distance']:.0f} | {best['tp']:.0f} | {best['sl']:.0f} | "
                f"{best['mean_pnl']:+.1f} | [{best['ci_low']:+.1f}, {best['ci_high']:+.1f}] | "
                f"{best['win_rate']*100:.1f}% | {best['sharpe']:.2f} | "
                f"{best['profit_factor']:.2f} | {best['cvar_5']:+.1f} | {best['n_trades']} |"
            )

        lines.append("")

        # Per-event-type breakdown
        for source, et_results in sorted(event_type_results.get(pair, {}).items()):
            if not et_results:
                continue
            source_results = pair_results.get(source, [])
            if not source_results:
                continue
            best = source_results[0]
            lines += [
                f"### {pair} — {source} Events (Params: {best['distance']:.0f}/{best['tp']:.0f}/{best['sl']:.0f})",
                "",
                "| Event | E[P&L] | 95% CI | Win Rate | Sharpe | PF | N |",
                "|-------|--------|--------|----------|--------|----|---|",
            ]
            for event_name, metrics in sorted(et_results.items()):
                lines.append(
                    f"| {event_name} | {metrics['mean_pnl']:+.1f} | "
                    f"[{metrics['ci_low']:+.1f}, {metrics['ci_high']:+.1f}] | "
                    f"{metrics['win_rate']*100:.1f}% | {metrics['sharpe']:.2f} | "
                    f"{metrics['profit_factor']:.2f} | {metrics['n_trades']} |"
                )
            lines.append("")

        # Walk-forward
        lines += [
            f"### {pair} — Walk-Forward Validation",
            "",
            "| Source | Params | IS E[P&L] | IS Sharpe | IS N | OOS E[P&L] | OOS Sharpe | OOS N | Verdict |",
            "|--------|--------|-----------|-----------|------|------------|------------|-------|---------|",
        ]

        for source, wf in sorted(wf_results.get(pair, {}).items()):
            if wf.get("status") == "insufficient_train_data":
                lines.append(f"| {source} | — | — | — | — | — | — | — | SKIP |")
                continue
            p = wf.get("optimal_params", {})
            is_d = wf.get("in_sample", {})
            os_d = wf.get("out_of_sample", {})
            oos_pnl = os_d.get("mean_pnl", 0)

            # Determine verdict
            is_ci_low = is_d.get("ci_low", 0)
            if is_ci_low > 0 and oos_pnl > 0:
                verdict = "PASS"
            elif is_ci_low > 0:
                verdict = "FAIL (overfit)"
            else:
                verdict = "FAIL (no edge)"

            lines.append(
                f"| **{source}** | {p.get('distance', 0):.0f}/{p.get('tp', 0):.0f}/{p.get('sl', 0):.0f} | "
                f"{is_d.get('mean_pnl', 0):+.1f} | {is_d.get('sharpe', 0):.2f} | "
                f"{is_d.get('n_trades', 0)} | "
                f"{oos_pnl:+.1f} | {os_d.get('sharpe', 0):.2f} | "
                f"{os_d.get('n_trades', 0)} | {verdict} |"
            )

        lines.append("")

    # Overall recommendation
    lines += [
        "## Recommendation",
        "",
    ]

    for pair in CAD_PAIRS:
        pair_wf = wf_results.get(pair, {})
        passing = []
        for source, wf in pair_wf.items():
            if wf.get("status") == "insufficient_train_data":
                continue
            is_d = wf.get("in_sample", {})
            os_d = wf.get("out_of_sample", {})
            if is_d.get("ci_low", 0) > 0 and os_d.get("mean_pnl", 0) > 0:
                passing.append(source)

        if passing:
            lines.append(
                f"**{pair}**: **Recommended for production** on {', '.join(passing)} events. "
                f"Add to `config/settings.yaml`."
            )
        else:
            lines.append(
                f"**{pair}**: **Not recommended.** No event source passes walk-forward validation."
            )
        lines.append("")

    lines += [
        "## Caveats",
        "",
        "1. **Cross pairs have wider spreads**: CADJPY, EURCAD, GBPCAD typically have wider "
        "event-time spreads than majors. The spread estimates used here are conservative but "
        "should be validated with live data.",
        "",
        "2. **Indirect exposure on US events**: These pairs don't contain USD directly. US events "
        "affect them through cross-rate dynamics (e.g., NFP moves USD, which moves USDCAD and "
        "USDJPY, which affects CADJPY). The signal may be weaker or delayed.",
        "",
        "3. **Canadian event sample**: ~208 Canadian events over 6.5 years. Per-event-type "
        "breakdown (BOC: ~52, CPI: ~78, Employment: ~78) is directional, not definitive.",
        "",
        "4. **Home currency benefit**: Even if edge is marginal, trading a CAD pair avoids "
        "the currency sweep cost (converting exotic trade P&L back to CAD). This is a small "
        "but real operational advantage.",
        "",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Monte Carlo Straddle Optimization — CAD Pair Exploration"
    )
    parser.add_argument(
        "--pairs",
        nargs="+",
        default=CAD_PAIRS,
        choices=CAD_PAIRS,
        help="Pairs to analyze (default: all)",
    )
    args = parser.parse_args()

    train_years = [2020, 2021, 2022, 2023, 2024]
    test_years = [2025, 2026]

    # Structure: all_results[pair][source] = list of grid results
    all_results: dict[str, dict[str, list[dict]]] = {}
    wf_results: dict[str, dict[str, dict]] = {}
    event_type_results: dict[str, dict[str, dict[str, dict]]] = {}
    data_counts: dict[str, dict[str, dict[str, int]]] = {}

    n_comparisons = len(args.pairs)

    for pair in args.pairs:
        logger.info(f"=== {pair} ===")
        sources = PAIR_EVENT_SOURCES.get(pair, {})
        all_results[pair] = {}
        wf_results[pair] = {}
        event_type_results[pair] = {}
        data_counts[pair] = {}

        for source_name, wanted_events in sources.items():
            logger.info(f"--- {pair} on {source_name} events ---")

            # Load and filter data
            data = load_filtered_data(pair, wanted_events)
            if len(data) < 5:
                logger.warning(f"Only {len(data)} events for {pair}/{source_name}, skipping")
                all_results[pair][source_name] = []
                wf_results[pair][source_name] = {"pair": pair, "status": "insufficient_data"}
                continue

            # Count events by type
            counts: dict[str, int] = {}
            for v in data.values():
                counts[v["event_name"]] = counts.get(v["event_name"], 0) + 1
            data_counts[pair][source_name] = counts

            # Grid search
            t0 = time.time()
            logger.info(f"Grid search {pair}/{source_name}...")
            results = run_grid_search(data, pair, n_comparisons=n_comparisons)
            all_results[pair][source_name] = results

            if results:
                best = results[0]
                logger.info(
                    f"  Best: D={best['distance']:.0f} TP={best['tp']:.0f} SL={best['sl']:.0f} "
                    f"E[PnL]={best['mean_pnl']:+.1f} CI=[{best['ci_low']:+.1f},{best['ci_high']:+.1f}] "
                    f"WR={best['win_rate']*100:.1f}% Sharpe={best['sharpe']:.2f} N={best['n_trades']}"
                )

            # Walk-forward
            logger.info(f"Walk-forward {pair}/{source_name}...")
            wf = walk_forward_validate(data, pair, train_years, test_years)
            wf_results[pair][source_name] = wf
            if "optimal_params" in wf:
                p = wf["optimal_params"]
                os_d = wf.get("out_of_sample", {})
                logger.info(
                    f"  WF: params={p['distance']:.0f}/{p['tp']:.0f}/{p['sl']:.0f} "
                    f"OOS E[PnL]={os_d.get('mean_pnl', 0):+.1f} "
                    f"OOS Sharpe={os_d.get('sharpe', 0):.2f}"
                )

            # Per-event-type breakdown
            if results:
                best = results[0]
                params = {"distance": best["distance"], "tp": best["tp"], "sl": best["sl"]}
                event_type_results[pair][source_name] = analyze_by_event_type(data, pair, params)

            elapsed = time.time() - t0
            logger.info(f"  {pair}/{source_name} completed in {elapsed:.0f}s")

    # Visualization
    logger.info("Generating visualizations...")
    for pair in args.pairs:
        for source_name, results in all_results.get(pair, {}).items():
            if results:
                suffix = f"_{source_name.lower()}"
                generate_heatmaps(results, f"{pair}{suffix}", DATA_DIR)

    # Report
    report = generate_report(all_results, wf_results, event_type_results, data_counts)
    report_path = DATA_DIR / "MC_CAD_EXPLORE_REPORT.md"
    with open(report_path, "w") as f:
        f.write(report)
    logger.info(f"Report saved to {report_path}")

    print("\n" + report)

    # Save raw results
    serializable = {}
    for pair, sources in all_results.items():
        serializable[pair] = {}
        for source, results in sources.items():
            serializable[pair][source] = results[:20]
    with open(RESULTS_FILE, "w") as f:
        json.dump(serializable, f, indent=2)


if __name__ == "__main__":
    main()
