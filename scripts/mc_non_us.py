#!/usr/bin/env python3
"""
Monte Carlo Straddle Optimization — Non-US Events
===================================================

Runs straddle optimization on non-US economic events:
  - Canada (BOC Rate, CPI, Employment) → USDCAD
  - Japan (BOJ Rate, CPI) → USDJPY

Reuses the core simulation engine from monte_carlo_dukascopy.py.
Event data comes from the Dukascopy CSVs which already contain event_name
metadata, so we filter by event name rather than maintaining separate date lists.

Usage:
  python scripts/mc_non_us.py                          # All non-US pairs
  python scripts/mc_non_us.py --pairs USDCAD           # Canada only
  python scripts/mc_non_us.py --pairs USDJPY           # Japan only
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from loguru import logger

# Import core engine from existing MC script
from monte_carlo_dukascopy import (
    CONFIDENCE_LEVEL,
    DATA_DIR,
    DISTANCE_RANGE,
    DUKASCOPY_DIR,
    N_BOOTSTRAP,
    SL_RANGE,
    TP_RANGE,
    bootstrap_metrics,
    generate_heatmaps,
    generate_pnl_distribution,
    load_dukascopy_data,
    simulate_straddle,
)

# ---------------------------------------------------------------------------
# Non-US Configuration
# ---------------------------------------------------------------------------

# Pairs and their associated non-US events
PAIR_EVENTS: dict[str, list[str]] = {
    "USDCAD": ["BOC Rate Decision", "Canada CPI", "Canada Employment"],
    "USDJPY": ["BOJ Rate Decision", "Japan CPI"],
    "USDZAR": ["SARB Rate Decision", "South Africa CPI"],
    "USDTRY": ["TCMB Rate Decision"],
}

# Event-time half-spread in pips (conservative estimates)
EVENT_SPREAD_PIPS = {
    "USDCAD": 2.5,
    "USDJPY": 2.0,
    "USDZAR": 25.0,
    "USDTRY": 30.0,
}

RESULTS_FILE = DATA_DIR / "optimization_results_non_us.json"

# ---------------------------------------------------------------------------
# Data Loading — filter to non-US events only
# ---------------------------------------------------------------------------


def load_non_us_data(pair: str) -> dict[str, dict]:
    """Load Dukascopy data filtered to only non-US events for this pair."""
    all_events = load_dukascopy_data(pair)
    wanted = set(PAIR_EVENTS.get(pair, []))

    filtered = {k: v for k, v in all_events.items() if v["event_name"] in wanted}

    # Log event breakdown
    by_type: dict[str, int] = {}
    for v in filtered.values():
        by_type[v["event_name"]] = by_type.get(v["event_name"], 0) + 1
    for name, count in sorted(by_type.items()):
        logger.info(f"  {name}: {count} events")

    logger.info(f"Filtered {pair}: {len(filtered)} non-US events (from {len(all_events)} total)")
    return filtered


# ---------------------------------------------------------------------------
# Grid Search (reuses simulate_straddle + bootstrap_metrics)
# ---------------------------------------------------------------------------


def run_grid_search(
    data: dict[str, dict],
    pair: str,
    years: list[int] | None = None,
) -> list[dict]:
    """Run grid search across parameter space for one pair.

    Args:
        data: Event data dict (already filtered to non-US events).
        pair: Currency pair.
        years: If provided, only use events from these years.
    """
    pair_data = data
    if years:
        pair_data = {k: v for k, v in data.items()
                     if int(v["event_date"][:4]) in years}

    if len(pair_data) < 5:
        logger.warning(f"Only {len(pair_data)} events for {pair} (years={years}), skipping")
        return []

    spread = EVENT_SPREAD_PIPS.get(pair, 2.0)
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
                metrics = bootstrap_metrics(pnl_arr)
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
    spread = EVENT_SPREAD_PIPS.get(pair, 2.0)
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
    all_results: dict[str, list[dict]],
    wf_results: dict[str, dict],
    event_type_results: dict[str, dict[str, dict]],
    data_counts: dict[str, dict[str, int]],
) -> str:
    """Generate markdown report for non-US event analysis."""
    pairs = list(all_results.keys())

    # Count total events
    total_events = sum(sum(counts.values()) for counts in data_counts.values())

    lines = [
        "# Monte Carlo Optimization — Non-US Events (Canada & Japan)",
        "",
        "**Date**: June 2026",
        "**Script**: `scripts/mc_non_us.py`",
        "**Data source**: Dukascopy Bank SA (1-minute OHLCV, bid-side)",
        "",
        "## Executive Summary",
        "",
        f"- **Analysis period**: January 2020 — June 2026 (6.5 years)",
        f"- **Total events analyzed**: {total_events}",
    ]

    for pair in pairs:
        counts = data_counts.get(pair, {})
        count_str = ", ".join(f"{name}: {n}" for name, n in sorted(counts.items()))
        lines.append(f"- **{pair}**: {sum(counts.values())} events ({count_str})")

    lines += [
        f"- **Grid**: {len(DISTANCE_RANGE) * len(TP_RANGE) * len(SL_RANGE)} parameter combinations "
        f"(distance {int(DISTANCE_RANGE[0])}-{int(DISTANCE_RANGE[-1])}, "
        f"TP {int(TP_RANGE[0])}-{int(TP_RANGE[-1])}, "
        f"SL {int(SL_RANGE[0])}-{int(SL_RANGE[-1])} pips)",
        f"- **Bootstrap**: {N_BOOTSTRAP:,} resamples, {CONFIDENCE_LEVEL*100:.0f}% confidence intervals",
        "- **Walk-forward**: Train 2020-2024 (5 years), test 2025-2026 (18 months)",
        "",
        "This is the first analysis of non-US economic events. These results determine whether "
        "USDCAD (on Canadian events) and USDJPY (on Japanese events) should be added to the "
        "active trading pairs. The existing US-event analysis showed USDCAD failing walk-forward "
        "on US events — but BOC/Canada CPI move USDCAD differently than NFP does.",
        "",
        "## Optimal Parameters by Pair",
        "",
        "| Pair | Distance | TP | SL | E[P&L] | 95% CI | Win Rate | Sharpe | Profit Factor | CVaR(5%) | N |",
        "|------|----------|----|----|--------|--------|----------|--------|---------------|----------|---|",
    ]

    recommendations = {}
    for pair in pairs:
        results = all_results.get(pair, [])
        if not results:
            lines.append(f"| {pair} | — | — | — | insufficient data | | | | | | |")
            continue
        best = results[0]
        recommendations[pair] = best
        lines.append(
            f"| **{pair}** | {best['distance']:.0f} | {best['tp']:.0f} | {best['sl']:.0f} | "
            f"{best['mean_pnl']:+.1f} | [{best['ci_low']:+.1f}, {best['ci_high']:+.1f}] | "
            f"{best['win_rate']*100:.1f}% | {best['sharpe']:.2f} | "
            f"{best['profit_factor']:.2f} | {best['cvar_5']:+.1f} | {best['n_trades']} |"
        )

    # Event-type breakdown
    lines += [
        "",
        "## Performance by Event Type",
        "",
    ]

    for pair in pairs:
        if pair not in event_type_results:
            continue
        best = recommendations.get(pair)
        if not best:
            continue
        lines += [
            f"### {pair} — Params: {best['distance']:.0f}/{best['tp']:.0f}/{best['sl']:.0f}",
            "",
            "| Event | E[P&L] | 95% CI | Win Rate | Sharpe | Profit Factor | N |",
            "|-------|--------|--------|----------|--------|---------------|---|",
        ]
        for event_name, metrics in sorted(event_type_results[pair].items()):
            lines.append(
                f"| {event_name} | {metrics['mean_pnl']:+.1f} | "
                f"[{metrics['ci_low']:+.1f}, {metrics['ci_high']:+.1f}] | "
                f"{metrics['win_rate']*100:.1f}% | {metrics['sharpe']:.2f} | "
                f"{metrics['profit_factor']:.2f} | {metrics['n_trades']} |"
            )
        lines.append("")

    # Walk-forward
    lines += [
        "## Walk-Forward Validation",
        "",
        "Train on 2020-2024 (5 years), test on 2025-2026 (18 months).",
        "",
        "| Pair | Params | IS E[P&L] | IS Sharpe | IS N | OOS E[P&L] | OOS Sharpe | OOS N |",
        "|------|--------|-----------|-----------|------|------------|------------|-------|",
    ]

    for pair in pairs:
        wf = wf_results.get(pair, {})
        if wf.get("status") == "insufficient_train_data":
            lines.append(f"| {pair} | — | — | — | — | — | — | — |")
            continue
        p = wf.get("optimal_params", {})
        is_d = wf.get("in_sample", {})
        os_d = wf.get("out_of_sample", {})
        lines.append(
            f"| **{pair}** | {p.get('distance', 0):.0f}/{p.get('tp', 0):.0f}/{p.get('sl', 0):.0f} | "
            f"{is_d.get('mean_pnl', 0):+.1f} | {is_d.get('sharpe', 0):.2f} | "
            f"{is_d.get('n_trades', 0)} | "
            f"{os_d.get('mean_pnl', 0):+.1f} | {os_d.get('sharpe', 0):.2f} | "
            f"{os_d.get('n_trades', 0)} |"
        )

    # Risk analysis
    lines += [
        "",
        "## Risk Analysis",
        "",
    ]

    for pair in pairs:
        best = recommendations.get(pair)
        if not best:
            continue
        rr_ratio = best["tp"] / best["sl"] if best["sl"] > 0 else 0
        be_wr = 1 / (1 + rr_ratio) if rr_ratio > 0 else 1
        wf = wf_results.get(pair, {})
        os_d = wf.get("out_of_sample", {})
        oos_pnl = os_d.get("mean_pnl", 0)
        oos_sharpe = os_d.get("sharpe", 0)

        verdict = ""
        if best["ci_low"] > 0 and oos_pnl > 0:
            verdict = "PASS — CI above zero and positive out-of-sample"
        elif best["ci_low"] > 0 and oos_pnl <= 0:
            verdict = "FAIL — Positive in-sample but negative out-of-sample (overfit)"
        elif best["ci_low"] <= 0:
            verdict = "FAIL — CI spans zero, no statistical edge"

        lines += [
            f"### {pair}",
            "",
            f"- **Reward:Risk ratio**: {rr_ratio:.1f}:1 (TP={best['tp']:.0f} / SL={best['sl']:.0f})",
            f"- **Breakeven win rate**: {be_wr*100:.1f}% (actual: {best['win_rate']*100:.1f}%)",
            f"- **Edge**: {(best['win_rate'] - be_wr)*100:+.1f} percentage points above breakeven",
            f"- **Median max drawdown**: {best['max_dd_pips']:.0f} pips",
            f"- **95th percentile max drawdown**: {best.get('max_dd_95', 0):.0f} pips",
            f"- **Worst 5% average trade**: {best['cvar_5']:+.1f} pips",
            f"- **Walk-forward OOS E[P&L]**: {oos_pnl:+.1f} (Sharpe: {oos_sharpe:.2f})",
            f"- **Verdict**: {verdict}",
            "",
        ]

    # Recommendation
    lines += [
        "## Recommendation",
        "",
    ]

    for pair in pairs:
        best = recommendations.get(pair)
        wf = wf_results.get(pair, {})
        os_d = wf.get("out_of_sample", {})
        if not best:
            lines.append(f"**{pair}**: Insufficient data for analysis.")
            continue

        if best["ci_low"] > 0 and os_d.get("mean_pnl", 0) > 0:
            lines.append(
                f"**{pair}**: **Recommended for production.** CI entirely above zero, "
                f"walk-forward positive. Add to `config/settings.yaml` with params "
                f"{best['distance']:.0f}/{best['tp']:.0f}/{best['sl']:.0f}."
            )
        elif best["ci_low"] > 0:
            lines.append(
                f"**{pair}**: **Not recommended.** Positive in-sample but walk-forward "
                f"shows signs of overfitting. Monitor with paper trading."
            )
        else:
            lines.append(
                f"**{pair}**: **Not recommended.** CI spans zero — no statistical edge "
                f"detected at any parameter combination."
            )
        lines.append("")

    # Caveats
    lines += [
        "## Caveats",
        "",
        "1. **Different volatility dynamics**: Canadian and Japanese events move their "
        "respective pairs differently than US events. BOC decisions can produce sharp "
        "but short-lived moves; BOJ decisions since 2022 (YCC changes) have been "
        "extremely volatile.",
        "",
        "2. **Timing differences**: BOJ announces ~12 PM JST (overnight for North America). "
        "Liquidity is lower during Asian hours. Canada events are during normal NA hours.",
        "",
        "3. **Spread approximation**: Event-time spreads are fixed estimates. BOJ surprises "
        "can blow out USDJPY spreads to 10+ pips.",
        "",
        "4. **Sample sizes per event type**: With 3 Canadian event types, each has ~52-78 "
        "events. Japan has 2 types with 53-78 events. Per-type analysis is directional, "
        "not definitive.",
        "",
        "5. **USDCAD failed US walk-forward**: USDCAD failed walk-forward on US events "
        "(OOS E[P&L]=-14.3). This analysis tests whether the pair is profitable on its "
        "own country's events, which is a fundamentally different question.",
        "",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Monte Carlo Straddle Optimization — Non-US Events"
    )
    parser.add_argument(
        "--pairs",
        nargs="+",
        default=list(PAIR_EVENTS.keys()),
        choices=list(PAIR_EVENTS.keys()),
        help="Pairs to analyze (default: all)",
    )
    args = parser.parse_args()

    # Phase 1: Load data
    logger.info("Loading Dukascopy 1-min data (non-US events only)...")
    all_data: dict[str, dict[str, dict]] = {}
    data_counts: dict[str, dict[str, int]] = {}

    for pair in args.pairs:
        pair_data = load_non_us_data(pair)
        if not pair_data:
            logger.warning(f"No non-US event data for {pair}. Did you run the download?")
            continue
        all_data[pair] = pair_data

        # Count events by type
        counts: dict[str, int] = {}
        for v in pair_data.values():
            counts[v["event_name"]] = counts.get(v["event_name"], 0) + 1
        data_counts[pair] = counts

    if not all_data:
        logger.error("No data loaded. Run: ~/anaconda3/envs/forex-bot/bin/python "
                      "scripts/download_dukascopy.py --group canada,japan --skip-existing --timeframe 1min")
        sys.exit(1)

    # Phase 2: Grid Search
    t0 = time.time()
    all_results: dict[str, list[dict]] = {}
    for pair, pair_data in all_data.items():
        logger.info(f"Optimizing {pair}...")
        results = run_grid_search(pair_data, pair)
        all_results[pair] = results
        if results:
            best = results[0]
            logger.info(
                f"  {pair} best: D={best['distance']:.0f} TP={best['tp']:.0f} SL={best['sl']:.0f} "
                f"E[PnL]={best['mean_pnl']:+.1f} CI=[{best['ci_low']:+.1f},{best['ci_high']:+.1f}] "
                f"WR={best['win_rate']*100:.1f}% Sharpe={best['sharpe']:.2f} N={best['n_trades']}"
            )

    # Phase 3: Walk-Forward Validation
    train_years = [2020, 2021, 2022, 2023, 2024]
    test_years = [2025, 2026]
    logger.info(f"Walk-forward: train {train_years[0]}-{train_years[-1]}, "
                f"test {test_years[0]}-{test_years[-1]}...")
    wf_results: dict[str, dict] = {}
    for pair, pair_data in all_data.items():
        logger.info(f"Walk-forward {pair}...")
        wf = walk_forward_validate(pair_data, pair, train_years, test_years)
        wf_results[pair] = wf
        if "optimal_params" in wf:
            p = wf["optimal_params"]
            os_d = wf.get("out_of_sample", {})
            logger.info(
                f"  {pair} WF: params={p['distance']:.0f}/{p['tp']:.0f}/{p['sl']:.0f} "
                f"OOS E[PnL]={os_d.get('mean_pnl', 0):+.1f} "
                f"OOS Sharpe={os_d.get('sharpe', 0):.2f}"
            )

    # Phase 4: Per-event-type breakdown at optimal params
    logger.info("Analyzing per-event-type performance...")
    event_type_results: dict[str, dict[str, dict]] = {}
    for pair in args.pairs:
        results = all_results.get(pair, [])
        if not results:
            continue
        best = results[0]
        params = {"distance": best["distance"], "tp": best["tp"], "sl": best["sl"]}
        event_type_results[pair] = analyze_by_event_type(all_data[pair], pair, params)

    elapsed = time.time() - t0
    logger.info(f"Optimization completed in {elapsed:.0f}s")

    # Phase 5: Visualization
    logger.info("Generating visualizations...")
    for pair in args.pairs:
        if pair in all_data:
            generate_heatmaps(all_results.get(pair, []), pair, DATA_DIR)
            # Need to pass data in the format generate_pnl_distribution expects
            flat_data = {k: v for k, v in all_data[pair].items()}
            generate_pnl_distribution(all_results.get(pair, []), flat_data, pair, DATA_DIR)

    # Phase 6: Report
    report = generate_report(all_results, wf_results, event_type_results, data_counts)
    report_path = DATA_DIR / "MC_NON_US_REPORT.md"
    with open(report_path, "w") as f:
        f.write(report)
    logger.info(f"Report saved to {report_path}")

    print("\n" + report)

    # Save raw results
    serializable = {}
    for pair, results in all_results.items():
        serializable[pair] = results[:20]
    with open(RESULTS_FILE, "w") as f:
        json.dump(serializable, f, indent=2)


if __name__ == "__main__":
    main()
