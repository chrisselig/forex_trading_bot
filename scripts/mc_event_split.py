#!/usr/bin/env python3
"""
Monte Carlo Event-Type Split Analysis
======================================

Runs the straddle optimization separately for NFP, CPI, and FOMC events
to determine whether the strategy performs differently by event type.
Uses the same simulation engine as monte_carlo_dukascopy.py.

This addresses caveat #6: "FOMC dynamics differ from data releases."

Usage:
  python scripts/mc_event_split.py
  python scripts/mc_event_split.py --pairs USDZAR USDTRY
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

# Reuse everything from the main MC script
from monte_carlo_dukascopy import (
    PAIRS,
    EVENT_SPREAD_PIPS,
    DISTANCE_RANGE,
    TP_RANGE,
    SL_RANGE,
    N_BOOTSTRAP,
    DATA_DIR,
    load_dukascopy_data,
    simulate_straddle,
    bootstrap_metrics,
    get_all_events,
)


def run_grid_search_filtered(
    all_data: dict[str, dict],
    pair: str,
    event_name: str | None = None,
    years: list[int] | None = None,
) -> list[dict]:
    """Run grid search with optional event-type and year filters."""
    pair_data = {k: v for k, v in all_data.items() if v["pair"] == pair}
    if event_name:
        pair_data = {k: v for k, v in pair_data.items()
                     if v["event_name"] == event_name}
    if years:
        pair_data = {k: v for k, v in pair_data.items()
                     if int(v["event_date"][:4]) in years}

    if len(pair_data) < 5:
        logger.warning(f"Only {len(pair_data)} events for {pair} {event_name} years={years}, skipping")
        return []

    spread = EVENT_SPREAD_PIPS.get(pair, 2.0)
    results = []

    for dist in DISTANCE_RANGE:
        for tp in TP_RANGE:
            for sl in SL_RANGE:
                all_pnl = []
                for key, data in pair_data.items():
                    trades = simulate_straddle(
                        bars=data["bars"],
                        event_utc_str=data["event_utc"],
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
                    "event_type": event_name or "ALL",
                    "distance": float(dist),
                    "tp": float(tp),
                    "sl": float(sl),
                    "score": metrics["ci_low"],
                    **metrics,
                })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def evaluate_fixed_params(
    all_data: dict[str, dict],
    pair: str,
    event_name: str,
    distance: float,
    tp: float,
    sl: float,
) -> dict | None:
    """Evaluate a specific parameter set on a specific event type."""
    pair_data = {k: v for k, v in all_data.items()
                 if v["pair"] == pair and v["event_name"] == event_name}

    if len(pair_data) < 3:
        return None

    spread = EVENT_SPREAD_PIPS.get(pair, 2.0)
    all_pnl = []

    for key, data in pair_data.items():
        trades = simulate_straddle(
            bars=data["bars"],
            event_utc_str=data["event_utc"],
            pair=pair,
            distance_pips=distance,
            tp_pips=tp,
            sl_pips=sl,
            spread_pips=spread,
        )
        for t in trades:
            if t.triggered:
                all_pnl.append(t.pnl_pips)

    if len(all_pnl) < 3:
        return None

    pnl_arr = np.array(all_pnl)
    metrics = bootstrap_metrics(pnl_arr)
    return {
        "pair": pair,
        "event_type": event_name,
        "distance": distance,
        "tp": tp,
        "sl": sl,
        **metrics,
    }


def main():
    parser = argparse.ArgumentParser(description="Monte Carlo Event-Type Split Analysis")
    parser.add_argument("--pairs", nargs="+", default=["USDZAR", "USDTRY"],
                        help="Pairs to analyze (default: active pairs)")
    args = parser.parse_args()

    events = get_all_events()
    event_types = ["NFP", "CPI", "FOMC", "PPI", "GDP", "PCE"]
    train_years = [2020, 2021, 2022, 2023, 2024]
    test_years = [2025, 2026]

    # Load data
    logger.info("Loading Dukascopy 1-min data...")
    all_data: dict[str, dict] = {}
    for pair in args.pairs:
        pair_data = load_dukascopy_data(pair)
        all_data.update(pair_data)

    logger.info(f"Total: {len(all_data)} event/pair data sets loaded")

    t0 = time.time()
    all_results = {}

    for pair in args.pairs:
        all_results[pair] = {}

        # --- Part 1: Current params (50/70/10) broken out by event type ---
        logger.info(f"\n{'='*60}")
        logger.info(f"{pair}: Evaluating current params (50/70/10) by event type")
        logger.info(f"{'='*60}")

        for evt in event_types:
            result = evaluate_fixed_params(all_data, pair, evt, 50, 70, 10)
            if result:
                logger.info(
                    f"  {pair} {evt}: E[P&L]={result['mean_pnl']:+.1f} "
                    f"CI=[{result['ci_low']:+.1f},{result['ci_high']:+.1f}] "
                    f"WR={result['win_rate']*100:.1f}% Sharpe={result['sharpe']:.2f} "
                    f"N={result['n_trades']}"
                )
                all_results[pair][f"current_{evt}"] = result
            else:
                logger.warning(f"  {pair} {evt}: insufficient data")

        # --- Part 2: Optimize per event type ---
        logger.info(f"\n{pair}: Optimizing per event type (full sample)...")

        for evt in event_types:
            logger.info(f"  Optimizing {pair} {evt}...")
            results = run_grid_search_filtered(all_data, pair, event_name=evt)
            if results:
                best = results[0]
                logger.info(
                    f"  {pair} {evt} best: D={best['distance']:.0f} TP={best['tp']:.0f} "
                    f"SL={best['sl']:.0f} E[P&L]={best['mean_pnl']:+.1f} "
                    f"CI=[{best['ci_low']:+.1f},{best['ci_high']:+.1f}] "
                    f"WR={best['win_rate']*100:.1f}% Sharpe={best['sharpe']:.2f} N={best['n_trades']}"
                )
                all_results[pair][f"optimal_{evt}"] = best
            else:
                logger.warning(f"  {pair} {evt}: optimization failed")

        # --- Part 3: Walk-forward per event type ---
        logger.info(f"\n{pair}: Walk-forward by event type (train 2020-2024, test 2025-2026)...")

        for evt in event_types:
            train_results = run_grid_search_filtered(
                all_data, pair, event_name=evt, years=train_years)
            if not train_results:
                logger.warning(f"  {pair} {evt}: insufficient train data")
                continue

            best_train = train_results[0]
            # Evaluate best train params on test period
            test_data = {k: v for k, v in all_data.items()
                         if v["pair"] == pair and v["event_name"] == evt
                         and int(v["event_date"][:4]) in test_years}

            if len(test_data) < 3:
                logger.warning(f"  {pair} {evt}: insufficient test data")
                continue

            spread = EVENT_SPREAD_PIPS.get(pair, 2.0)
            test_pnl = []
            for key, data in test_data.items():
                trades = simulate_straddle(
                    bars=data["bars"],
                    event_utc_str=data["event_utc"],
                    pair=pair,
                    distance_pips=best_train["distance"],
                    tp_pips=best_train["tp"],
                    sl_pips=best_train["sl"],
                    spread_pips=spread,
                )
                for t in trades:
                    if t.triggered:
                        test_pnl.append(t.pnl_pips)

            if len(test_pnl) < 3:
                logger.warning(f"  {pair} {evt}: insufficient triggered trades in test")
                continue

            test_arr = np.array(test_pnl)
            test_metrics = bootstrap_metrics(test_arr)

            wf_result = {
                "params": {
                    "distance": best_train["distance"],
                    "tp": best_train["tp"],
                    "sl": best_train["sl"],
                },
                "in_sample": {
                    "mean_pnl": best_train["mean_pnl"],
                    "sharpe": best_train["sharpe"],
                    "n_trades": best_train["n_trades"],
                },
                "out_of_sample": test_metrics,
            }
            all_results[pair][f"wf_{evt}"] = wf_result

            logger.info(
                f"  {pair} {evt} WF: params={best_train['distance']:.0f}/{best_train['tp']:.0f}/{best_train['sl']:.0f} "
                f"IS={best_train['mean_pnl']:+.1f} (Sharpe {best_train['sharpe']:.2f}) "
                f"OOS={test_metrics['mean_pnl']:+.1f} (Sharpe {test_metrics['sharpe']:.2f})"
            )

    elapsed = time.time() - t0
    logger.info(f"\nCompleted in {elapsed:.0f}s")

    # Save raw results
    results_file = DATA_DIR / "event_split_results.json"
    with open(results_file, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    logger.info(f"Results saved to {results_file}")

    # Print summary
    print("\n" + "=" * 80)
    print("EVENT-TYPE SPLIT ANALYSIS SUMMARY")
    print("=" * 80)

    for pair in args.pairs:
        print(f"\n{'─' * 60}")
        print(f"  {pair}")
        print(f"{'─' * 60}")

        # Current params by event type
        print(f"\n  Current params (50/70/10) by event type:")
        print(f"  {'Event':<8} {'E[P&L]':>8} {'95% CI':>20} {'WR':>8} {'Sharpe':>8} {'PF':>8} {'N':>5}")
        print(f"  {'─'*65}")
        for evt in event_types:
            r = all_results[pair].get(f"current_{evt}")
            if r:
                print(f"  {evt:<8} {r['mean_pnl']:>+8.1f} [{r['ci_low']:>+8.1f},{r['ci_high']:>+7.1f}] "
                      f"{r['win_rate']*100:>7.1f}% {r['sharpe']:>8.2f} {r['profit_factor']:>8.2f} {r['n_trades']:>5}")

        # Optimal per event type
        print(f"\n  Optimal params per event type:")
        print(f"  {'Event':<8} {'Params':>12} {'E[P&L]':>8} {'95% CI':>20} {'WR':>8} {'Sharpe':>8} {'N':>5}")
        print(f"  {'─'*71}")
        for evt in event_types:
            r = all_results[pair].get(f"optimal_{evt}")
            if r:
                params = f"{r['distance']:.0f}/{r['tp']:.0f}/{r['sl']:.0f}"
                print(f"  {evt:<8} {params:>12} {r['mean_pnl']:>+8.1f} [{r['ci_low']:>+8.1f},{r['ci_high']:>+7.1f}] "
                      f"{r['win_rate']*100:>7.1f}% {r['sharpe']:>8.2f} {r['n_trades']:>5}")

        # Walk-forward per event type
        print(f"\n  Walk-forward (train 2020-2024, test 2025-2026):")
        print(f"  {'Event':<8} {'Params':>12} {'IS E[P&L]':>10} {'IS Sharpe':>10} {'OOS E[P&L]':>11} {'OOS Sharpe':>11}")
        print(f"  {'─'*68}")
        for evt in event_types:
            wf = all_results[pair].get(f"wf_{evt}")
            if wf:
                p = wf["params"]
                params = f"{p['distance']:.0f}/{p['tp']:.0f}/{p['sl']:.0f}"
                print(f"  {evt:<8} {params:>12} {wf['in_sample']['mean_pnl']:>+10.1f} "
                      f"{wf['in_sample']['sharpe']:>10.2f} {wf['out_of_sample']['mean_pnl']:>+11.1f} "
                      f"{wf['out_of_sample']['sharpe']:>11.2f}")


if __name__ == "__main__":
    main()
