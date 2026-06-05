#!/usr/bin/env python3
"""
Monte Carlo Straddle Parameter Optimization
============================================

Pulls historical 1-hour forex data from IB around major US economic events
(2025-2026), simulates straddle strategies across a parameter grid, and uses
bootstrap Monte Carlo to find optimal parameters with confidence intervals.

Note: IB paper accounts only provide 1-hour bar data (not 1-min). The simulation
uses OHLC from hourly bars to determine if trigger/TP/SL levels were hit. When
both TP and SL could be hit within the same bar, SL is assumed first (conservative).

Methodology:
  1. Collect 1-hour bars for a 2-day window around each event for each pair
  2. For each (distance, TP, SL) triple, simulate the straddle P&L
  3. Bootstrap-resample event outcomes 10,000× to build P&L distributions
  4. Score each parameter set on a pessimistic risk-adjusted metric
  5. Walk-forward validate: train on 2025, test on 2026
  6. Report optimal parameters with confidence intervals

Usage:
  python scripts/monte_carlo_straddle.py                # Full run (collect + analyze)
  python scripts/monte_carlo_straddle.py --collect-only  # Just collect data from IB
  python scripts/monte_carlo_straddle.py --analyze-only  # Just analyze cached data
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "scripts" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

CACHE_FILE = DATA_DIR / "event_bars.json"
RESULTS_FILE = DATA_DIR / "optimization_results.json"
REPORT_FILE = DATA_DIR / "STRADDLE_OPTIMIZATION_REPORT.md"

# IB pacing: 60 historical data requests per 10 minutes
PACING_WINDOW = 600
PACING_LIMIT = 58  # conservative margin
REQUEST_DELAY = 2.5  # seconds between requests (safe default)

# Pairs to analyze
PAIRS = ["GBPUSD", "USDCAD", "GBPJPY", "USDZAR", "USDTRY"]

PIP_SIZES = {
    "EURUSD": 0.0001, "GBPUSD": 0.0001, "USDCAD": 0.0001,
    "GBPJPY": 0.01, "USDJPY": 0.01, "EURJPY": 0.01,
    "USDZAR": 0.0001, "USDTRY": 0.0001,
}

# Typical event-time half-spread in pips (conservative estimates)
EVENT_SPREAD_PIPS = {
    "GBPUSD": 2.0, "USDCAD": 2.5, "GBPJPY": 4.0,
    "USDZAR": 25.0, "USDTRY": 30.0,
}

# Parameter grid
DISTANCE_RANGE = np.arange(10, 55, 5)     # 10..50 pips
TP_RANGE = np.arange(15, 75, 5)           # 15..70 pips
SL_RANGE = np.arange(10, 35, 5)           # 10..30 pips (min 10 for news events)

# Monte Carlo
N_BOOTSTRAP = 10_000
CONFIDENCE_LEVEL = 0.95
MAX_HOLDING_BARS = 12  # 12 hours of 1-hour bars

# ---------------------------------------------------------------------------
# Event Schedule (2025-01 to 2026-06)
# All times are Eastern Time, converted to UTC for IB requests.
# ---------------------------------------------------------------------------

def _nfp_dates() -> list[dict]:
    """Non-Farm Payrolls — first Friday of each month, 8:30 AM ET."""
    dates = [
        # 2025
        "2025-01-10", "2025-02-07", "2025-03-07", "2025-04-04", "2025-05-02",
        "2025-06-06", "2025-07-03", "2025-08-01", "2025-09-05", "2025-10-03",
        "2025-11-07", "2025-12-05",
        # 2026
        "2026-01-09", "2026-02-06", "2026-03-06", "2026-04-03", "2026-05-01",
        "2026-06-05",
    ]
    return [{"name": "NFP", "date": d, "time": "08:30"} for d in dates]


def _cpi_dates() -> list[dict]:
    """CPI — mid-month, 8:30 AM ET."""
    dates = [
        "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10", "2025-05-13",
        "2025-06-11", "2025-07-11", "2025-08-12", "2025-09-10", "2025-10-14",
        "2025-11-12", "2025-12-10",
        "2026-01-14", "2026-02-11", "2026-03-11", "2026-04-14", "2026-05-12",
    ]
    return [{"name": "CPI", "date": d, "time": "08:30"} for d in dates]


def _fomc_dates() -> list[dict]:
    """FOMC Rate Decision — 2:00 PM ET."""
    dates = [
        "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
        "2025-07-30", "2025-09-17", "2025-11-05", "2025-12-17",
        "2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
    ]
    return [{"name": "FOMC", "date": d, "time": "14:00"} for d in dates]


def get_all_events() -> list[dict]:
    """Return all events with UTC datetime."""
    events = _nfp_dates() + _cpi_dates() + _fomc_dates()
    for e in events:
        local_dt = datetime.strptime(f"{e['date']} {e['time']}", "%Y-%m-%d %H:%M")
        local_dt = local_dt.replace(tzinfo=ET)
        e["utc_dt"] = local_dt.astimezone(UTC).replace(tzinfo=None)
        e["year"] = int(e["date"][:4])
    events.sort(key=lambda x: x["utc_dt"])
    return events


# ---------------------------------------------------------------------------
# Data Collection (IB)
# ---------------------------------------------------------------------------

async def collect_data(pairs: list[str] | None = None) -> dict:
    """Pull 1-hour bars from IB for each event × pair. Cache to disk."""
    from ib_async import IB, Forex

    if pairs is None:
        pairs = PAIRS

    # Load existing cache
    cache = {}
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            cache = json.load(f)

    events = get_all_events()
    total_needed = 0
    requests = []
    for event in events:
        for pair in pairs:
            key = f"{event['date']}_{event['name']}_{pair}"
            if key not in cache:
                requests.append((event, pair, key))
                total_needed += 1

    if total_needed == 0:
        logger.info("All data already cached. Skipping collection.")
        return cache

    logger.info(f"Need to collect {total_needed} bar sets ({len(events)} events × {len(pairs)} pairs, minus cached)")

    ib = IB()
    await ib.connectAsync("127.0.0.1", 7497, clientId=10, timeout=30)
    logger.info("Connected to IB for data collection")

    request_times: list[float] = []
    collected = 0
    failed = 0

    for event, pair, key in requests:
        # Pacing control
        now = time.time()
        request_times = [t for t in request_times if now - t < PACING_WINDOW]
        if len(request_times) >= PACING_LIMIT:
            wait = PACING_WINDOW - (now - request_times[0]) + 1
            logger.warning(f"Pacing limit reached, waiting {wait:.0f}s...")
            await asyncio.sleep(wait)

        # Request: 2 days of 1-hour bars ending 12 hours after the event
        end_dt = event["utc_dt"] + timedelta(hours=12)
        end_str = end_dt.strftime("%Y%m%d-%H:%M:%S")

        contract = Forex(pair)
        try:
            await ib.qualifyContractsAsync(contract)
            bars = await ib.reqHistoricalDataAsync(
                contract,
                endDateTime=end_str,
                durationStr="2 D",
                barSizeSetting="1 hour",
                whatToShow="MIDPOINT",
                useRTH=False,
                formatDate=2,
            )
            request_times.append(time.time())

            if bars:
                bar_data = [
                    {
                        "time": bar.date.strftime("%Y-%m-%d %H:%M:%S") if hasattr(bar.date, "strftime") else str(bar.date),
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                    }
                    for bar in bars
                ]
                cache[key] = {
                    "event": event["name"],
                    "date": event["date"],
                    "event_utc": event["utc_dt"].strftime("%Y-%m-%d %H:%M:%S"),
                    "pair": pair,
                    "bars": bar_data,
                }
                collected += 1
                logger.info(f"Collected {key}: {len(bars)} bars")
            else:
                logger.warning(f"No bars returned for {key}")
                failed += 1

        except Exception as e:
            logger.error(f"Failed to fetch {key}: {e}")
            failed += 1

        # Save periodically
        if collected % 10 == 0 and collected > 0:
            with open(CACHE_FILE, "w") as f:
                json.dump(cache, f)
            logger.info(f"Progress: {collected}/{total_needed} collected, {failed} failed")

        await asyncio.sleep(REQUEST_DELAY)

    ib.disconnect()

    # Final save
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)
    logger.info(f"Collection complete: {collected} collected, {failed} failed, {len(cache)} total cached")

    return cache


# ---------------------------------------------------------------------------
# Straddle Simulation
# ---------------------------------------------------------------------------

@dataclass
class TradeResult:
    event_name: str
    event_date: str
    pair: str
    leg: str           # "BUY" or "SELL"
    triggered: bool
    entry_price: float = 0.0
    exit_price: float = 0.0
    pnl_pips: float = 0.0
    outcome: str = ""  # "TP", "SL", "TIMEOUT", "NO_TRIGGER"
    duration_bars: int = 0


def simulate_straddle(
    bars: list[dict],
    event_utc_str: str,
    pair: str,
    distance_pips: float,
    tp_pips: float,
    sl_pips: float,
    spread_pips: float = 0.0,
) -> list[TradeResult]:
    """Simulate a straddle on 1-hour bar data. Returns results for both legs.

    With hourly bars, when both TP and SL could be hit within the same bar,
    SL is checked first (conservative/pessimistic assumption).
    """
    pip = PIP_SIZES.get(pair, 0.0001)

    # Parse bar times and find the event bar index
    bar_times = []
    for b in bars:
        try:
            bt = datetime.strptime(b["time"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            bt = datetime.fromisoformat(b["time"])
        bar_times.append(bt)

    event_time = datetime.strptime(event_utc_str, "%Y-%m-%d %H:%M:%S")

    # Find the bar closest to 1 hour before the event (pre-event entry)
    # With hourly bars, 30 min rounds to the bar starting 1 hour before
    pre_event_time = event_time - timedelta(hours=1)
    pre_idx = None
    min_diff = timedelta(hours=99)
    for i, bt in enumerate(bar_times):
        diff = abs(bt - pre_event_time)
        if diff < min_diff:
            min_diff = diff
            pre_idx = i

    if pre_idx is None or pre_idx >= len(bars) - 10:
        return [
            TradeResult(event_name="", event_date="", pair=pair, leg="BUY",
                        triggered=False, outcome="NO_DATA"),
            TradeResult(event_name="", event_date="", pair=pair, leg="SELL",
                        triggered=False, outcome="NO_DATA"),
        ]

    mid_price = (bars[pre_idx]["high"] + bars[pre_idx]["low"]) / 2
    spread_adj = spread_pips * pip / 2  # half-spread on each side

    buy_stop = mid_price + distance_pips * pip + spread_adj
    sell_stop = mid_price - distance_pips * pip - spread_adj

    buy_sl = buy_stop - sl_pips * pip
    buy_tp = buy_stop + tp_pips * pip
    sell_sl = sell_stop + sl_pips * pip
    sell_tp = sell_stop - tp_pips * pip

    results = []

    # Simulate each leg independently
    for leg, entry, sl, tp in [
        ("BUY", buy_stop, buy_sl, buy_tp),
        ("SELL", sell_stop, sell_sl, sell_tp),
    ]:
        triggered = False
        trigger_idx = None

        # Phase 1: wait for trigger (from pre_idx onward)
        for i in range(pre_idx, min(len(bars), pre_idx + MAX_HOLDING_BARS)):
            if leg == "BUY" and bars[i]["high"] >= entry:
                triggered = True
                trigger_idx = i
                break
            elif leg == "SELL" and bars[i]["low"] <= entry:
                triggered = True
                trigger_idx = i
                break

        if not triggered:
            results.append(TradeResult(
                event_name="", event_date="", pair=pair, leg=leg,
                triggered=False, outcome="NO_TRIGGER",
            ))
            continue

        # Phase 2: track until TP, SL, or timeout
        outcome = "TIMEOUT"
        exit_price = bars[min(trigger_idx + MAX_HOLDING_BARS, len(bars) - 1)]["close"]
        exit_idx = min(trigger_idx + MAX_HOLDING_BARS, len(bars) - 1)

        for i in range(trigger_idx + 1, min(len(bars), trigger_idx + MAX_HOLDING_BARS)):
            bar = bars[i]
            if leg == "BUY":
                # Check SL first (conservative — assume adverse fill)
                if bar["low"] <= sl:
                    outcome = "SL"
                    exit_price = sl
                    exit_idx = i
                    break
                if bar["high"] >= tp:
                    outcome = "TP"
                    exit_price = tp
                    exit_idx = i
                    break
            else:  # SELL
                if bar["high"] >= sl:
                    outcome = "SL"
                    exit_price = sl
                    exit_idx = i
                    break
                if bar["low"] <= tp:
                    outcome = "TP"
                    exit_price = tp
                    exit_idx = i
                    break

        if outcome == "TIMEOUT":
            exit_price = bars[exit_idx]["close"]

        pnl_price = (exit_price - entry) if leg == "BUY" else (entry - exit_price)
        pnl_pips = pnl_price / pip

        results.append(TradeResult(
            event_name="", event_date="", pair=pair, leg=leg,
            triggered=True, entry_price=entry, exit_price=exit_price,
            pnl_pips=pnl_pips, outcome=outcome,
            duration_bars=exit_idx - trigger_idx,
        ))

    return results


# ---------------------------------------------------------------------------
# Monte Carlo Bootstrap
# ---------------------------------------------------------------------------

def bootstrap_metrics(
    pnl_array: np.ndarray,
    n_bootstrap: int = N_BOOTSTRAP,
    confidence: float = CONFIDENCE_LEVEL,
) -> dict:
    """Bootstrap resample P&L to get distribution of key metrics."""
    n = len(pnl_array)
    if n < 3:
        return {
            "mean_pnl": float(np.mean(pnl_array)) if n > 0 else 0.0,
            "ci_low": 0.0, "ci_high": 0.0,
            "sharpe": 0.0, "sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0,
            "win_rate": 0.0, "profit_factor": 0.0,
            "max_dd_pips": 0.0, "cvar_5": 0.0,
            "n_trades": n,
        }

    rng = np.random.default_rng(42)
    boot_idx = rng.integers(0, n, size=(n_bootstrap, n))
    boot_samples = pnl_array[boot_idx]  # shape: (n_bootstrap, n)

    # Per-bootstrap metrics
    boot_means = boot_samples.mean(axis=1)
    boot_stds = boot_samples.std(axis=1, ddof=1)
    # Use a reasonable min std (1 pip) to avoid division-by-near-zero blowups
    boot_stds = np.maximum(boot_stds, 1.0)
    boot_sharpes = boot_means / boot_stds * np.sqrt(n)
    # Clip extreme Sharpe values for numerical stability
    boot_sharpes = np.clip(boot_sharpes, -10, 10)
    boot_win_rates = (boot_samples > 0).mean(axis=1)

    # Cumulative P&L for max drawdown
    boot_cumsum = np.cumsum(boot_samples, axis=1)
    boot_running_max = np.maximum.accumulate(boot_cumsum, axis=1)
    boot_drawdowns = boot_running_max - boot_cumsum
    boot_max_dd = boot_drawdowns.max(axis=1)

    alpha = (1 - confidence) / 2

    # CVaR (expected shortfall) at 5th percentile
    sorted_pnl = np.sort(pnl_array)
    cvar_idx = max(1, int(0.05 * n))
    cvar_5 = float(sorted_pnl[:cvar_idx].mean())

    # Profit factor
    wins = pnl_array[pnl_array > 0].sum()
    losses = abs(pnl_array[pnl_array < 0].sum())
    profit_factor = float(wins / losses) if losses > 0 else float("inf")

    return {
        "mean_pnl": float(np.mean(pnl_array)),
        "median_pnl": float(np.median(pnl_array)),
        "std_pnl": float(np.std(pnl_array, ddof=1)),
        "ci_low": float(np.percentile(boot_means, alpha * 100)),
        "ci_high": float(np.percentile(boot_means, (1 - alpha) * 100)),
        "sharpe": float(np.mean(boot_sharpes)),
        "sharpe_ci_low": float(np.percentile(boot_sharpes, alpha * 100)),
        "sharpe_ci_high": float(np.percentile(boot_sharpes, (1 - alpha) * 100)),
        "win_rate": float((pnl_array > 0).mean()),
        "profit_factor": profit_factor,
        "max_dd_pips": float(np.median(boot_max_dd)),
        "max_dd_95": float(np.percentile(boot_max_dd, 95)),
        "cvar_5": cvar_5,
        "n_trades": n,
    }


# ---------------------------------------------------------------------------
# Grid Search Optimization
# ---------------------------------------------------------------------------

def run_grid_search(
    cache: dict,
    pair: str,
    events: list[dict] | None = None,
    year_filter: int | None = None,
) -> list[dict]:
    """Run grid search across parameter space for one pair."""
    # Filter cache entries for this pair
    pair_data = {k: v for k, v in cache.items() if v["pair"] == pair}
    if events:
        event_names = {e["name"] for e in events}
        pair_data = {k: v for k, v in pair_data.items() if v["event"] in event_names}
    if year_filter:
        pair_data = {k: v for k, v in pair_data.items()
                     if v["date"].startswith(str(year_filter))}

    if len(pair_data) < 5:
        logger.warning(f"Only {len(pair_data)} events for {pair} (year={year_filter}), skipping")
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

                # Scoring: pessimistic risk-adjusted metric
                # Uses the 5th percentile of bootstrap mean distribution
                # This penalizes high-variance strategies
                score = metrics["ci_low"]

                results.append({
                    "pair": pair,
                    "distance": float(dist),
                    "tp": float(tp),
                    "sl": float(sl),
                    "score": score,
                    **metrics,
                })

        if count % 100 == 0:
            logger.debug(f"  {pair}: {count}/{total} parameter combos evaluated")

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def walk_forward_validate(cache: dict, pair: str, train_year: int, test_year: int) -> dict:
    """Train on one year, test on the next. Returns in-sample and out-of-sample metrics."""
    # Train: find optimal params on train_year
    train_results = run_grid_search(cache, pair, year_filter=train_year)
    if not train_results:
        return {"pair": pair, "status": "insufficient_train_data"}

    best = train_results[0]
    opt_dist = best["distance"]
    opt_tp = best["tp"]
    opt_sl = best["sl"]

    # Test: evaluate those params on test_year
    test_results = run_grid_search(cache, pair, year_filter=test_year)
    test_match = [r for r in test_results
                  if r["distance"] == opt_dist and r["tp"] == opt_tp and r["sl"] == opt_sl]

    return {
        "pair": pair,
        "optimal_params": {"distance": opt_dist, "tp": opt_tp, "sl": opt_sl},
        "in_sample": {
            "year": train_year,
            "mean_pnl": best["mean_pnl"],
            "sharpe": best["sharpe"],
            "win_rate": best["win_rate"],
            "n_trades": best["n_trades"],
        },
        "out_of_sample": {
            "year": test_year,
            **(test_match[0] if test_match else {"mean_pnl": 0, "sharpe": 0, "win_rate": 0, "n_trades": 0}),
        },
    }


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------

def generate_heatmaps(results: list[dict], pair: str, output_dir: Path):
    """Generate heatmaps of expected P&L across parameter space."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import TwoSlopeNorm
    except ImportError:
        logger.warning("matplotlib not available, skipping heatmaps")
        return

    if not results:
        return

    # Find the optimal SL, then show distance × TP heatmap at that SL
    best = results[0]
    best_sl = best["sl"]

    # Filter to best SL
    sl_results = [r for r in results if r["sl"] == best_sl]
    if not sl_results:
        return

    # Build matrix
    distances = sorted(set(r["distance"] for r in sl_results))
    tps = sorted(set(r["tp"] for r in sl_results))

    matrix = np.full((len(distances), len(tps)), np.nan)
    for r in sl_results:
        i = distances.index(r["distance"])
        j = tps.index(r["tp"])
        matrix[i, j] = r["mean_pnl"]

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))

    # Heatmap 1: Mean P&L
    vmax = max(abs(np.nanmin(matrix)), abs(np.nanmax(matrix)))
    norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)
    im = axes[0].imshow(matrix, cmap="RdYlGn", norm=norm, aspect="auto", origin="lower")
    axes[0].set_xticks(range(len(tps)))
    axes[0].set_xticklabels([f"{t:.0f}" for t in tps], rotation=45)
    axes[0].set_yticks(range(len(distances)))
    axes[0].set_yticklabels([f"{d:.0f}" for d in distances])
    axes[0].set_xlabel("Take Profit (pips)")
    axes[0].set_ylabel("Distance (pips)")
    axes[0].set_title(f"{pair} — Mean P&L per trade (pips)\n[SL={best_sl:.0f} pips]")
    plt.colorbar(im, ax=axes[0], label="P&L (pips)")

    # Mark the optimum
    best_di = distances.index(best["distance"])
    best_ti = tps.index(best["tp"])
    axes[0].plot(best_ti, best_di, "k*", markersize=15)

    # Heatmap 2: Sharpe ratio
    sharpe_matrix = np.full((len(distances), len(tps)), np.nan)
    for r in sl_results:
        i = distances.index(r["distance"])
        j = tps.index(r["tp"])
        sharpe_matrix[i, j] = r["sharpe"]

    smax = max(abs(np.nanmin(sharpe_matrix)), abs(np.nanmax(sharpe_matrix)), 0.1)
    norm2 = TwoSlopeNorm(vmin=-smax, vcenter=0, vmax=smax)
    im2 = axes[1].imshow(sharpe_matrix, cmap="RdYlGn", norm=norm2, aspect="auto", origin="lower")
    axes[1].set_xticks(range(len(tps)))
    axes[1].set_xticklabels([f"{t:.0f}" for t in tps], rotation=45)
    axes[1].set_yticks(range(len(distances)))
    axes[1].set_yticklabels([f"{d:.0f}" for d in distances])
    axes[1].set_xlabel("Take Profit (pips)")
    axes[1].set_ylabel("Distance (pips)")
    axes[1].set_title(f"{pair} — Sharpe Ratio\n[SL={best_sl:.0f} pips]")
    plt.colorbar(im2, ax=axes[1], label="Sharpe")
    axes[1].plot(best_ti, best_di, "k*", markersize=15)

    plt.tight_layout()
    path = output_dir / f"heatmap_{pair}.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"Saved heatmap: {path}")


def generate_pnl_distribution(results: list[dict], cache: dict, pair: str, output_dir: Path):
    """Plot bootstrap P&L distribution for the optimal parameters."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return

    if not results:
        return

    best = results[0]
    spread = EVENT_SPREAD_PIPS.get(pair, 2.0)
    pair_data = {k: v for k, v in cache.items() if v["pair"] == pair}

    all_pnl = []
    for key, data in pair_data.items():
        trades = simulate_straddle(
            bars=data["bars"], event_utc_str=data["event_utc"], pair=pair,
            distance_pips=best["distance"], tp_pips=best["tp"],
            sl_pips=best["sl"], spread_pips=spread,
        )
        for t in trades:
            if t.triggered:
                all_pnl.append(t.pnl_pips)

    if len(all_pnl) < 3:
        return

    pnl_arr = np.array(all_pnl)
    rng = np.random.default_rng(42)
    boot_means = np.array([
        pnl_arr[rng.integers(0, len(pnl_arr), len(pnl_arr))].mean()
        for _ in range(N_BOOTSTRAP)
    ])

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Per-trade P&L distribution
    axes[0].hist(pnl_arr, bins=30, color="steelblue", edgecolor="white", alpha=0.8)
    axes[0].axvline(0, color="red", linestyle="--", linewidth=1)
    axes[0].axvline(pnl_arr.mean(), color="green", linestyle="-", linewidth=2, label=f"Mean: {pnl_arr.mean():.1f}")
    axes[0].set_xlabel("P&L per trade (pips)")
    axes[0].set_ylabel("Frequency")
    axes[0].set_title(f"{pair} — Per-Trade P&L Distribution\n"
                      f"[D={best['distance']:.0f} TP={best['tp']:.0f} SL={best['sl']:.0f}]")
    axes[0].legend()

    # Bootstrap mean distribution
    axes[1].hist(boot_means, bins=50, color="darkorange", edgecolor="white", alpha=0.8)
    ci_low = np.percentile(boot_means, 2.5)
    ci_high = np.percentile(boot_means, 97.5)
    axes[1].axvline(ci_low, color="red", linestyle="--", label=f"95% CI: [{ci_low:.1f}, {ci_high:.1f}]")
    axes[1].axvline(ci_high, color="red", linestyle="--")
    axes[1].axvline(np.mean(boot_means), color="green", linestyle="-", linewidth=2)
    axes[1].set_xlabel("Mean P&L per trade (pips)")
    axes[1].set_ylabel("Bootstrap frequency")
    axes[1].set_title(f"{pair} — Bootstrap Distribution of Mean P&L\n(N={N_BOOTSTRAP:,} resamples)")
    axes[1].legend()

    plt.tight_layout()
    path = output_dir / f"pnl_dist_{pair}.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"Saved P&L distribution: {path}")


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------

def generate_report(
    all_results: dict[str, list[dict]],
    wf_results: dict[str, dict],
    events: list[dict],
    cache: dict,
) -> str:
    """Generate a comprehensive markdown report."""
    n_events = len(events)
    n_cached = len(cache)
    pairs = list(all_results.keys())

    lines = [
        "# Straddle Parameter Optimization Report",
        "",
        "## Executive Summary",
        "",
        f"- **Analysis period**: January 2025 — June 2026",
        f"- **Events analyzed**: {n_events} (NFP: {len(_nfp_dates())}, CPI: {len(_cpi_dates())}, FOMC: {len(_fomc_dates())})",
        f"- **Data points cached**: {n_cached} (event × pair combinations)",
        f"- **Pairs**: {', '.join(pairs)}",
        f"- **Monte Carlo iterations**: {N_BOOTSTRAP:,}",
        f"- **Confidence level**: {CONFIDENCE_LEVEL*100:.0f}%",
        "",
        "### Methodology",
        "",
        "1. Collected 1-hour bars from IB for a 2-day window around each event",
        "2. Simulated straddle mechanics (buy stop + sell stop, each with TP/SL) using hourly OHLC",
        "3. Grid search over distance (10-50), TP (15-70), SL (5-30) — all in pips",
        "4. Bootstrap resampled 10,000x to build confidence intervals",
        "5. Scored on pessimistic metric: lower bound of 95% CI on mean P&L",
        "6. Walk-forward validation: train on 2025, test on 2026",
        "7. Spread modeled as fixed cost (conservative event-time estimates)",
        "",
        "---",
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

    lines += [
        "",
        "> **Reading the table**: E[P&L] is the expected profit per trade in pips.",
        "> The 95% CI is the confidence interval on that mean — if the CI excludes zero,",
        "> we have statistical evidence the strategy is profitable. CVaR(5%) is the",
        "> average P&L of the worst 5% of trades (tail risk). Profit factor > 1.0 means",
        "> gross profits exceed gross losses.",
        "",
        "---",
        "",
        "## Walk-Forward Validation",
        "",
        "Train on 2025 data, test on 2026 data. This detects overfitting — if in-sample",
        "performance is strong but out-of-sample collapses, the parameters are overfit.",
        "",
        "| Pair | Params | In-Sample (2025) | | Out-of-Sample (2026) | |",
        "|------|--------|-----|------|------|------|",
        "| | D / TP / SL | E[P&L] | Sharpe | E[P&L] | Sharpe |",
    ]

    for pair in pairs:
        wf = wf_results.get(pair, {})
        if wf.get("status") == "insufficient_train_data":
            lines.append(f"| {pair} | — | — | — | — | — |")
            continue
        p = wf.get("optimal_params", {})
        is_data = wf.get("in_sample", {})
        os_data = wf.get("out_of_sample", {})
        lines.append(
            f"| **{pair}** | {p.get('distance', 0):.0f} / {p.get('tp', 0):.0f} / {p.get('sl', 0):.0f} | "
            f"{is_data.get('mean_pnl', 0):+.1f} | {is_data.get('sharpe', 0):.2f} | "
            f"{os_data.get('mean_pnl', 0):+.1f} | {os_data.get('sharpe', 0):.2f} |"
        )

    lines += [
        "",
        "> **What to look for**: Out-of-sample Sharpe should be at least 50% of in-sample.",
        "> If it collapses to near-zero or negative, the in-sample result was likely noise.",
        "",
        "---",
        "",
        "## Risk Analysis at Optimal Parameters",
        "",
    ]

    for pair in pairs:
        best = recommendations.get(pair)
        if not best:
            continue
        rr_ratio = best["tp"] / best["sl"] if best["sl"] > 0 else 0
        be_wr = 1 / (1 + rr_ratio) if rr_ratio > 0 else 1
        lines += [
            f"### {pair}",
            "",
            f"- **Reward:Risk ratio**: {rr_ratio:.1f}:1 (TP={best['tp']:.0f} / SL={best['sl']:.0f})",
            f"- **Breakeven win rate**: {be_wr*100:.1f}% (actual: {best['win_rate']*100:.1f}%)",
            f"- **Edge**: {(best['win_rate'] - be_wr)*100:+.1f} percentage points above breakeven",
            f"- **Median max drawdown**: {best['max_dd_pips']:.0f} pips",
            f"- **95th percentile max drawdown**: {best['max_dd_95']:.0f} pips",
            f"- **Worst 5% average trade**: {best['cvar_5']:+.1f} pips",
            "",
        ]

    lines += [
        "---",
        "",
        "## Recommended Settings",
        "",
        "Based on the full-sample optimization and walk-forward validation,",
        "the recommended `settings.yaml` straddle parameters are:",
        "",
        "```yaml",
        "strategy:",
    ]

    # Pick the most robust pair's parameters as default, or GBPUSD as reference
    ref_pair = "GBPUSD" if "GBPUSD" in recommendations else (pairs[0] if pairs else "")
    if ref_pair and ref_pair in recommendations:
        best = recommendations[ref_pair]
        lines += [
            f"  straddle_distance_pips: {best['distance']:.0f}",
            f"  straddle_tp_pips: {best['tp']:.0f}",
            f"  straddle_sl_pips: {best['sl']:.0f}",
        ]
    lines += [
        "```",
        "",
        "### Per-pair overrides (if implementing pair-specific params):",
        "",
        "| Pair | Distance | TP | SL |",
        "|------|----------|----|----|",
    ]
    for pair in pairs:
        best = recommendations.get(pair)
        if best:
            lines.append(f"| {pair} | {best['distance']:.0f} | {best['tp']:.0f} | {best['sl']:.0f} |")

    lines += [
        "",
        "---",
        "",
        "## Caveats and Limitations",
        "",
        "1. **Hourly bar resolution**: IB paper accounts only provide 1-hour bars for",
        "   historical forex data. Intra-hour price paths cannot be observed. When both",
        "   TP and SL could be hit in the same bar, SL is assumed first (pessimistic).",
        "   Results may improve with finer granularity (live account with 1-min data).",
        "",
        "2. **Small sample size**: ~48 events over 18 months. Bootstrap CIs account for",
        "   sampling uncertainty, but structural regime changes (e.g., shift from",
        "   tightening to easing) are not captured.",
        "",
        "3. **Spread approximation**: Event-time spreads are modeled as fixed estimates.",
        "   Actual spreads vary by broker, time, and event magnitude. Exotic pairs",
        "   (USDZAR, USDTRY) spreads can exceed 50 pips during NFP.",
        "",
        "4. **Slippage not modeled**: Stop orders can gap through during fast markets.",
        "   Actual fills may be worse than simulated, especially for the straddle entry.",
        "",
        "5. **No OCA modeling**: Both straddle legs can trigger independently. In the",
        "   worst case (whipsaw), both legs trigger and both stop out. This is modeled",
        "   accurately — it contributes to the tail risk in CVaR.",
        "",
        "6. **Multiple testing**: Grid search over ~500 parameter combinations inflates",
        "   the chance of finding spuriously good parameters. Walk-forward validation",
        "   is the primary guard against this, but with only ~6 months of test data,",
        "   out-of-sample results have wide confidence intervals.",
        "",
        "7. **FOMC has different dynamics**: Rate decisions move markets differently from",
        "   data releases (NFP/CPI). The optimal straddle parameters may differ for FOMC.",
        "   Consider splitting the analysis by event type for production use.",
        "",
    ]

    report = "\n".join(lines)
    return report


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="Monte Carlo Straddle Optimization")
    parser.add_argument("--collect-only", action="store_true", help="Only collect data from IB")
    parser.add_argument("--analyze-only", action="store_true", help="Only analyze cached data")
    parser.add_argument("--pairs", nargs="+", default=PAIRS, help="Pairs to analyze")
    args = parser.parse_args()

    events = get_all_events()
    logger.info(f"Event schedule: {len(events)} events ({len(_nfp_dates())} NFP, "
                f"{len(_cpi_dates())} CPI, {len(_fomc_dates())} FOMC)")

    # Phase 1: Data Collection
    if not args.analyze_only:
        cache = await collect_data(args.pairs)
    else:
        if not CACHE_FILE.exists():
            logger.error("No cached data found. Run without --analyze-only first.")
            sys.exit(1)
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        logger.info(f"Loaded {len(cache)} cached bar sets")

    if args.collect_only:
        logger.info("Collection complete. Run with --analyze-only to analyze.")
        return

    # Phase 2: Grid Search Optimization
    logger.info("Starting grid search optimization...")
    all_results: dict[str, list[dict]] = {}
    for pair in args.pairs:
        logger.info(f"Optimizing {pair}...")
        results = run_grid_search(cache, pair)
        all_results[pair] = results
        if results:
            best = results[0]
            logger.info(
                f"  {pair} best: D={best['distance']:.0f} TP={best['tp']:.0f} SL={best['sl']:.0f} "
                f"E[PnL]={best['mean_pnl']:+.1f} CI=[{best['ci_low']:+.1f},{best['ci_high']:+.1f}] "
                f"WR={best['win_rate']*100:.1f}% Sharpe={best['sharpe']:.2f}"
            )

    # Phase 3: Walk-Forward Validation
    logger.info("Running walk-forward validation (train 2025, test 2026)...")
    wf_results: dict[str, dict] = {}
    for pair in args.pairs:
        wf = walk_forward_validate(cache, pair, train_year=2025, test_year=2026)
        wf_results[pair] = wf

    # Phase 4: Visualization
    logger.info("Generating visualizations...")
    for pair in args.pairs:
        generate_heatmaps(all_results.get(pair, []), pair, DATA_DIR)
        generate_pnl_distribution(all_results.get(pair, []), cache, pair, DATA_DIR)

    # Phase 5: Report
    report = generate_report(all_results, wf_results, events, cache)
    with open(REPORT_FILE, "w") as f:
        f.write(report)
    logger.info(f"Report saved to {REPORT_FILE}")

    # Print to stdout
    print("\n" + report)

    # Save raw results
    serializable = {}
    for pair, results in all_results.items():
        serializable[pair] = results[:20]  # top 20 per pair
    with open(RESULTS_FILE, "w") as f:
        json.dump(serializable, f, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
