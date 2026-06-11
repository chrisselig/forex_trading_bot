#!/usr/bin/env python3
"""
Monte Carlo Straddle Optimization (Dukascopy 1-min data)
========================================================

Uses 1-minute OHLCV bars from Dukascopy to simulate straddle strategies
around major US economic events. This is a significant improvement over the
IB-based script (monte_carlo_straddle.py) which was limited to 1-hour bars
and required a pessimistic SL-first assumption.

With 1-min bars:
  - Actual intra-bar price paths are visible
  - TP vs SL ordering is determined by real price sequence
  - Pre-event entry timing is exact (30 min before, not rounded to hourly)
  - Whipsaw patterns are captured accurately

Methodology:
  1. Load 1-min bars from Dukascopy CSVs for each pair/event
  2. For each (distance, TP, SL) triple, simulate the straddle P&L
  3. Bootstrap-resample event outcomes 10,000x to build P&L distributions
  4. Score each parameter set on a pessimistic risk-adjusted metric
  5. Walk-forward validate: train on 2025, test on 2026
  6. Report optimal parameters with confidence intervals

Usage:
  python scripts/monte_carlo_dukascopy.py
  python scripts/monte_carlo_dukascopy.py --pairs GBPUSD USDCAD
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "scripts" / "data"
DUKASCOPY_DIR = DATA_DIR / "dukascopy"
DATA_DIR.mkdir(parents=True, exist_ok=True)

RESULTS_FILE = DATA_DIR / "optimization_results_1min.json"
REPORT_FILE = DATA_DIR / "STRADDLE_OPTIMIZATION_REPORT_1MIN.md"

PAIRS = ["GBPUSD", "USDCAD", "GBPJPY", "USDZAR", "USDTRY", "EURUSD", "AUDUSD"]

PIP_SIZES = {
    "EURUSD": 0.0001, "GBPUSD": 0.0001, "USDCAD": 0.0001,
    "AUDUSD": 0.0001,
    "GBPJPY": 0.01, "USDJPY": 0.01, "EURJPY": 0.01,
    "USDZAR": 0.0001, "USDTRY": 0.0001,
}

# Typical event-time half-spread in pips (conservative estimates)
EVENT_SPREAD_PIPS = {
    "EURUSD": 1.5, "GBPUSD": 2.0, "USDCAD": 2.5, "AUDUSD": 2.0,
    "GBPJPY": 4.0,
    "USDZAR": 25.0, "USDTRY": 30.0,
}

# Parameter grid
DISTANCE_RANGE = np.arange(10, 55, 5)     # 10..50 pips
TP_RANGE = np.arange(15, 75, 5)           # 15..70 pips
SL_RANGE = np.arange(10, 35, 5)           # 10..30 pips (min 10 for news events)

# Monte Carlo
N_BOOTSTRAP = 10_000
CONFIDENCE_LEVEL = 0.95
MAX_HOLDING_MINUTES = 720  # 12 hours in 1-min bars

# Pre-event entry: place straddle orders 30 min before event
PRE_EVENT_MINUTES = 30

# ---------------------------------------------------------------------------
# Event Schedule (2020-01 to 2026-06)
# ---------------------------------------------------------------------------


def _nfp_dates() -> list[dict]:
    """Non-Farm Payrolls — first Friday of each month, 8:30 AM ET."""
    dates = [
        # 2020
        "2020-01-10", "2020-02-07", "2020-03-06", "2020-04-03", "2020-05-08",
        "2020-06-05", "2020-07-02", "2020-08-07", "2020-09-04", "2020-10-02",
        "2020-11-06", "2020-12-04",
        # 2021
        "2021-01-08", "2021-02-05", "2021-03-05", "2021-04-02", "2021-05-07",
        "2021-06-04", "2021-07-02", "2021-08-06", "2021-09-03", "2021-10-08",
        "2021-11-05", "2021-12-03",
        # 2022
        "2022-01-07", "2022-02-04", "2022-03-04", "2022-04-01", "2022-05-06",
        "2022-06-03", "2022-07-08", "2022-08-05", "2022-09-02", "2022-10-07",
        "2022-11-04", "2022-12-02",
        # 2023
        "2023-01-06", "2023-02-03", "2023-03-10", "2023-04-07", "2023-05-05",
        "2023-06-02", "2023-07-07", "2023-08-04", "2023-09-01", "2023-10-06",
        "2023-11-03", "2023-12-08",
        # 2024
        "2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05", "2024-05-03",
        "2024-06-07", "2024-07-05", "2024-08-02", "2024-09-06", "2024-10-04",
        "2024-11-01", "2024-12-06",
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
        # 2020
        "2020-01-14", "2020-02-13", "2020-03-11", "2020-04-10", "2020-05-12",
        "2020-06-10", "2020-07-14", "2020-08-12", "2020-09-11", "2020-10-13",
        "2020-11-12", "2020-12-10",
        # 2021
        "2021-01-13", "2021-02-10", "2021-03-10", "2021-04-13", "2021-05-12",
        "2021-06-10", "2021-07-13", "2021-08-11", "2021-09-14", "2021-10-13",
        "2021-11-10", "2021-12-10",
        # 2022
        "2022-01-12", "2022-02-10", "2022-03-10", "2022-04-12", "2022-05-11",
        "2022-06-10", "2022-07-13", "2022-08-10", "2022-09-13", "2022-10-13",
        "2022-11-10", "2022-12-13",
        # 2023
        "2023-01-12", "2023-02-14", "2023-03-14", "2023-04-12", "2023-05-10",
        "2023-06-13", "2023-07-12", "2023-08-10", "2023-09-13", "2023-10-12",
        "2023-11-14", "2023-12-12",
        # 2024
        "2024-01-11", "2024-02-13", "2024-03-12", "2024-04-10", "2024-05-15",
        "2024-06-12", "2024-07-11", "2024-08-14", "2024-09-11", "2024-10-10",
        "2024-11-13", "2024-12-11",
        # 2025
        "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10", "2025-05-13",
        "2025-06-11", "2025-07-11", "2025-08-12", "2025-09-10", "2025-10-14",
        "2025-11-12", "2025-12-10",
        # 2026
        "2026-01-14", "2026-02-11", "2026-03-11", "2026-04-14", "2026-05-12",
    ]
    return [{"name": "CPI", "date": d, "time": "08:30"} for d in dates]


def _fomc_dates() -> list[dict]:
    """FOMC Rate Decision — 2:00 PM ET."""
    dates = [
        # 2020
        "2020-01-29", "2020-03-15", "2020-04-29", "2020-06-10",
        "2020-07-29", "2020-09-16", "2020-11-05", "2020-12-16",
        # 2021
        "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16",
        "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
        # 2022
        "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
        "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
        # 2023
        "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
        "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
        # 2024
        "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
        "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
        # 2025
        "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
        "2025-07-30", "2025-09-17", "2025-11-05", "2025-12-17",
        # 2026
        "2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
    ]
    return [{"name": "FOMC", "date": d, "time": "14:00"} for d in dates]


def _ppi_dates() -> list[dict]:
    """PPI m/m — monthly, 8:30 AM ET. Dates from FRED release calendar."""
    dates = [
        # 2020
        "2020-01-15", "2020-02-14", "2020-03-12", "2020-04-09", "2020-05-13",
        "2020-06-11", "2020-07-10", "2020-08-11", "2020-09-10", "2020-10-14",
        "2020-11-13", "2020-12-11",
        # 2021
        "2021-01-15", "2021-02-12", "2021-03-12", "2021-04-09", "2021-05-13",
        "2021-06-15", "2021-07-14", "2021-08-12", "2021-09-10", "2021-10-14",
        "2021-11-09", "2021-12-14",
        # 2022
        "2022-01-13", "2022-02-11", "2022-03-15", "2022-04-13", "2022-05-12",
        "2022-06-14", "2022-07-14", "2022-08-11", "2022-09-14", "2022-10-12",
        "2022-11-15", "2022-12-09",
        # 2023
        "2023-01-18", "2023-02-14", "2023-03-15", "2023-04-13", "2023-05-11",
        "2023-06-14", "2023-07-13", "2023-08-11", "2023-09-14", "2023-10-11",
        "2023-11-15", "2023-12-13",
        # 2024
        "2024-01-12", "2024-02-14", "2024-03-14", "2024-04-11", "2024-05-14",
        "2024-06-13", "2024-07-12", "2024-08-13", "2024-09-12", "2024-10-11",
        "2024-11-14", "2024-12-12",
        # 2025
        "2025-01-14", "2025-02-13", "2025-03-13", "2025-04-11", "2025-05-15",
        "2025-06-12", "2025-07-16", "2025-08-14", "2025-09-10",
        "2025-11-25",
        # 2026
        "2026-01-14", "2026-02-27", "2026-03-18", "2026-04-14", "2026-05-13",
        "2026-06-11",
    ]
    return [{"name": "PPI", "date": d, "time": "08:30"} for d in dates]


def _gdp_dates() -> list[dict]:
    """GDP q/q — Advance/Preliminary/Final, 8:30 AM ET. Dates from FRED (rid=53)."""
    dates = [
        # 2020
        "2020-01-30", "2020-02-27", "2020-03-26", "2020-04-29", "2020-05-28",
        "2020-06-25", "2020-07-30", "2020-08-27", "2020-09-16", "2020-10-29",
        "2020-11-03", "2020-12-22",
        # 2021
        "2021-01-28", "2021-02-25", "2021-03-25", "2021-04-29", "2021-05-27",
        "2021-06-24", "2021-07-29", "2021-08-06", "2021-09-24", "2021-10-28",
        "2021-11-24", "2021-12-22",
        # 2022
        "2022-01-27", "2022-02-24", "2022-03-30", "2022-04-28", "2022-05-26",
        "2022-06-29", "2022-07-28", "2022-08-25", "2022-09-29", "2022-10-06",
        "2022-11-30", "2022-12-22",
        # 2023
        "2023-01-26", "2023-02-23", "2023-03-30", "2023-04-27", "2023-05-25",
        "2023-06-29", "2023-07-27", "2023-08-30", "2023-09-28", "2023-10-26",
        "2023-11-17", "2023-12-21",
        # 2024
        "2024-01-25", "2024-02-28", "2024-03-28", "2024-04-25", "2024-05-30",
        "2024-06-27", "2024-07-25", "2024-08-29", "2024-09-26", "2024-10-02",
        "2024-11-27", "2024-12-19",
        # 2025
        "2025-01-30", "2025-02-27", "2025-03-27", "2025-04-30", "2025-05-29",
        "2025-06-26", "2025-07-30", "2025-08-28", "2025-09-25",
        # NOTE: Oct-Nov 2025 disrupted by government shutdown
        "2025-12-23",
        # 2026
        "2026-01-22", "2026-02-20", "2026-03-13", "2026-04-09", "2026-05-28",
        "2026-06-25",
    ]
    return [{"name": "GDP", "date": d, "time": "08:30"} for d in dates]


def _pce_dates() -> list[dict]:
    """PCE (Personal Consumption Expenditures) — monthly, 8:30 AM ET. FRED rid=54."""
    dates = [
        # 2020
        "2020-01-31", "2020-02-28", "2020-03-27", "2020-04-30", "2020-05-29",
        "2020-06-26", "2020-07-31", "2020-08-28", "2020-10-01",
        "2020-11-25", "2020-12-23",
        # 2021
        "2021-01-29", "2021-02-26", "2021-03-26", "2021-04-30", "2021-05-28",
        "2021-06-25", "2021-07-30", "2021-08-27", "2021-10-01",
        "2021-11-24", "2021-12-23",
        # 2022
        "2022-01-28", "2022-02-25", "2022-03-31", "2022-04-29", "2022-05-27",
        "2022-06-30", "2022-07-29", "2022-08-26", "2022-09-30", "2022-10-28",
        "2022-12-01",
        # 2023
        "2023-01-27", "2023-02-24", "2023-03-31", "2023-04-28", "2023-05-26",
        "2023-06-30", "2023-07-28", "2023-08-31", "2023-09-29", "2023-10-27",
        "2023-11-30", "2023-12-22",
        # 2024
        "2024-01-26", "2024-02-29", "2024-03-29", "2024-04-26", "2024-05-31",
        "2024-06-28", "2024-07-26", "2024-08-30", "2024-09-27", "2024-10-31",
        "2024-11-27", "2024-12-20",
        # 2025
        "2025-01-31", "2025-02-28", "2025-03-28", "2025-04-30", "2025-05-30",
        "2025-06-27", "2025-07-31", "2025-08-29", "2025-09-26",
        # NOTE: Oct-Nov 2025 disrupted by government shutdown
        "2025-12-05",
        # 2026
        "2026-01-22", "2026-02-20", "2026-03-13", "2026-04-09", "2026-05-28",
        "2026-06-25",
    ]
    return [{"name": "PCE", "date": d, "time": "08:30"} for d in dates]


def get_all_events() -> list[dict]:
    """Return all events with UTC datetime."""
    events = (_nfp_dates() + _cpi_dates() + _fomc_dates() + _ppi_dates()
              + _gdp_dates() + _pce_dates())
    for e in events:
        local_dt = datetime.strptime(f"{e['date']} {e['time']}", "%Y-%m-%d %H:%M")
        local_dt = local_dt.replace(tzinfo=ET)
        e["utc_dt"] = local_dt.astimezone(UTC).replace(tzinfo=None)
        e["year"] = int(e["date"][:4])
    events.sort(key=lambda x: x["utc_dt"])
    return events


# ---------------------------------------------------------------------------
# Data Loading (Dukascopy CSVs)
# ---------------------------------------------------------------------------


def load_dukascopy_data(pair: str) -> dict[str, pd.DataFrame]:
    """Load 1-min Dukascopy CSV and split into per-event DataFrames.

    Returns dict mapping "EVENT_DATE" -> DataFrame of 1-min bars for that event.
    """
    csv_path = DUKASCOPY_DIR / f"{pair}_1min.csv"
    if not csv_path.exists():
        logger.error(f"Missing data file: {csv_path}")
        return {}

    df = pd.read_csv(csv_path, index_col=0, parse_dates=True)

    # Group by event
    event_groups = {}
    for event_date, group in df.groupby("event_date"):
        event_name = group["event_name"].iloc[0]
        key = f"{event_date}_{event_name}_{pair}"
        # Sort by timestamp and drop metadata columns
        bars = group[["open", "high", "low", "close", "volume"]].sort_index()
        event_groups[key] = {
            "bars": bars,
            "event_date": event_date,
            "event_name": event_name,
            "event_utc": group["event_utc"].iloc[0],
            "pair": pair,
        }

    logger.info(f"Loaded {pair}: {len(event_groups)} events, {len(df):,} total bars")
    return event_groups


# ---------------------------------------------------------------------------
# Straddle Simulation (1-min bars)
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
    bars: pd.DataFrame,
    event_utc_str: str,
    pair: str,
    distance_pips: float,
    tp_pips: float,
    sl_pips: float,
    spread_pips: float = 0.0,
) -> list[TradeResult]:
    """Simulate a straddle on 1-min bar data. Returns results for both legs.

    With 1-min bars, we can determine the actual order of TP/SL hits
    within each bar using OHLC logic:
    - If open is closer to TP, assume TP was hit first
    - If open is closer to SL, assume SL was hit first
    This is far more accurate than the hourly SL-first pessimistic assumption.
    """
    pip = PIP_SIZES.get(pair, 0.0001)
    event_time = datetime.fromisoformat(event_utc_str)

    # Make bars index timezone-naive for comparison
    bar_times = bars.index
    if bar_times.tz is not None:
        bar_times_naive = bar_times.tz_convert("UTC").tz_localize(None)
    else:
        bar_times_naive = bar_times

    # Find the bar closest to PRE_EVENT_MINUTES before the event
    pre_event_time = event_time - timedelta(minutes=PRE_EVENT_MINUTES)
    time_diffs = abs(bar_times_naive - pre_event_time)
    pre_idx = time_diffs.argmin()

    if pre_idx >= len(bars) - 10:
        return [
            TradeResult(event_name="", event_date="", pair=pair, leg="BUY",
                        triggered=False, outcome="NO_DATA"),
            TradeResult(event_name="", event_date="", pair=pair, leg="SELL",
                        triggered=False, outcome="NO_DATA"),
        ]

    # Use the mid price of the pre-event bar for straddle placement
    pre_bar = bars.iloc[pre_idx]
    mid_price = (pre_bar["high"] + pre_bar["low"]) / 2
    spread_adj = spread_pips * pip / 2

    buy_stop = mid_price + distance_pips * pip + spread_adj
    sell_stop = mid_price - distance_pips * pip - spread_adj

    buy_sl = buy_stop - sl_pips * pip
    buy_tp = buy_stop + tp_pips * pip
    sell_sl = sell_stop + sl_pips * pip
    sell_tp = sell_stop - tp_pips * pip

    results = []
    bar_values = bars[["open", "high", "low", "close"]].values
    n_bars = len(bar_values)

    for leg, entry, sl, tp in [
        ("BUY", buy_stop, buy_sl, buy_tp),
        ("SELL", sell_stop, sell_sl, sell_tp),
    ]:
        triggered = False
        trigger_idx = None
        max_bar = min(n_bars, pre_idx + MAX_HOLDING_MINUTES)

        # Phase 1: wait for trigger
        for i in range(pre_idx, max_bar):
            o, h, l, c = bar_values[i]
            if leg == "BUY" and h >= entry:
                triggered = True
                trigger_idx = i
                break
            elif leg == "SELL" and l <= entry:
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
        exit_idx = min(trigger_idx + MAX_HOLDING_MINUTES, n_bars - 1)
        exit_price = bar_values[exit_idx][3]  # close of last bar

        for i in range(trigger_idx + 1, min(n_bars, trigger_idx + MAX_HOLDING_MINUTES)):
            o, h, l, c = bar_values[i]

            if leg == "BUY":
                hit_sl = l <= sl
                hit_tp = h >= tp

                if hit_sl and hit_tp:
                    # Both could be hit in same bar — use open proximity
                    if abs(o - sl) <= abs(o - tp):
                        outcome = "SL"
                        exit_price = sl
                    else:
                        outcome = "TP"
                        exit_price = tp
                    exit_idx = i
                    break
                elif hit_sl:
                    outcome = "SL"
                    exit_price = sl
                    exit_idx = i
                    break
                elif hit_tp:
                    outcome = "TP"
                    exit_price = tp
                    exit_idx = i
                    break
            else:  # SELL
                hit_sl = h >= sl
                hit_tp = l <= tp

                if hit_sl and hit_tp:
                    if abs(o - sl) <= abs(o - tp):
                        outcome = "SL"
                        exit_price = sl
                    else:
                        outcome = "TP"
                        exit_price = tp
                    exit_idx = i
                    break
                elif hit_sl:
                    outcome = "SL"
                    exit_price = sl
                    exit_idx = i
                    break
                elif hit_tp:
                    outcome = "TP"
                    exit_price = tp
                    exit_idx = i
                    break

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
    n_comparisons: int = 1,
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
    boot_samples = pnl_array[boot_idx]

    boot_means = boot_samples.mean(axis=1)
    boot_stds = boot_samples.std(axis=1, ddof=1)
    boot_stds = np.maximum(boot_stds, 1.0)
    boot_sharpes = boot_means / boot_stds * np.sqrt(n)
    boot_sharpes = np.clip(boot_sharpes, -10, 10)

    # Max drawdown
    boot_cumsum = np.cumsum(boot_samples, axis=1)
    boot_running_max = np.maximum.accumulate(boot_cumsum, axis=1)
    boot_drawdowns = boot_running_max - boot_cumsum
    boot_max_dd = boot_drawdowns.max(axis=1)

    alpha = (1 - confidence) / 2

    # Bonferroni-adjusted CI: widen the CI to account for multiple comparisons
    # Uses Bonferroni correction: alpha_adj = alpha / n_comparisons
    alpha_bonf = alpha / n_comparisons if n_comparisons > 1 else alpha

    # CVaR at 5th percentile
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
        "ci_low_bonf": float(np.percentile(boot_means, alpha_bonf * 100)),
        "ci_high_bonf": float(np.percentile(boot_means, (1 - alpha_bonf) * 100)),
        "sharpe": float(np.mean(boot_sharpes)),
        "sharpe_ci_low": float(np.percentile(boot_sharpes, alpha * 100)),
        "sharpe_ci_high": float(np.percentile(boot_sharpes, (1 - alpha) * 100)),
        "win_rate": float((pnl_array > 0).mean()),
        "profit_factor": profit_factor,
        "max_dd_pips": float(np.median(boot_max_dd)),
        "max_dd_95": float(np.percentile(boot_max_dd, 95)),
        "cvar_5": cvar_5,
        "n_trades": n,
        "n_comparisons": n_comparisons,
    }


# ---------------------------------------------------------------------------
# Grid Search Optimization
# ---------------------------------------------------------------------------

def run_grid_search(
    all_data: dict[str, dict],
    pair: str,
    year_filter: int | None = None,
    n_comparisons: int = 1,
) -> list[dict]:
    """Run grid search across parameter space for one pair.

    n_comparisons: number of pairs being tested simultaneously (for Bonferroni).
    """
    pair_data = {k: v for k, v in all_data.items() if v["pair"] == pair}
    if year_filter:
        pair_data = {k: v for k, v in pair_data.items()
                     if v["event_date"].startswith(str(year_filter))}

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
                metrics = bootstrap_metrics(pnl_arr, n_comparisons=n_comparisons)
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


def walk_forward_validate(
    all_data: dict,
    pair: str,
    train_years: list[int],
    test_years: list[int],
) -> dict:
    """Train on one period, test on another.

    Supports multi-year train/test splits (e.g., train 2020-2024, test 2025-2026).
    """
    # Filter data for train period
    train_data = {k: v for k, v in all_data.items()
                  if v["pair"] == pair and int(v["event_date"][:4]) in train_years}
    test_data = {k: v for k, v in all_data.items()
                 if v["pair"] == pair and int(v["event_date"][:4]) in test_years}

    if len(train_data) < 5:
        return {"pair": pair, "status": "insufficient_train_data"}

    # Build a temporary all_data with only train data for grid search
    train_results = run_grid_search(all_data, pair, year_filter=None)
    # Re-run grid search on just train data
    train_only_data = {k: v for k, v in all_data.items()
                       if v["pair"] == pair and int(v["event_date"][:4]) in train_years}
    # Temporarily replace all_data for train search
    train_all = dict(all_data)
    # Actually, use a simpler approach: filter in grid search
    train_results = _run_grid_search_filtered(all_data, pair, train_years)
    if not train_results:
        return {"pair": pair, "status": "insufficient_train_data"}

    best = train_results[0]
    opt_dist = best["distance"]
    opt_tp = best["tp"]
    opt_sl = best["sl"]

    test_results = _run_grid_search_filtered(all_data, pair, test_years)
    test_match = [r for r in test_results
                  if r["distance"] == opt_dist and r["tp"] == opt_tp and r["sl"] == opt_sl]

    return {
        "pair": pair,
        "optimal_params": {"distance": opt_dist, "tp": opt_tp, "sl": opt_sl},
        "in_sample": {
            "years": train_years,
            "mean_pnl": best["mean_pnl"],
            "sharpe": best["sharpe"],
            "win_rate": best["win_rate"],
            "n_trades": best["n_trades"],
        },
        "out_of_sample": {
            "years": test_years,
            **(test_match[0] if test_match else {"mean_pnl": 0, "sharpe": 0, "win_rate": 0, "n_trades": 0}),
        },
    }


def _run_grid_search_filtered(
    all_data: dict,
    pair: str,
    years: list[int],
) -> list[dict]:
    """Run grid search filtering to specific years."""
    filtered = {k: v for k, v in all_data.items()
                if v["pair"] == pair and int(v["event_date"][:4]) in years}

    if len(filtered) < 5:
        logger.warning(f"Only {len(filtered)} events for {pair} years={years}, skipping")
        return []

    spread = EVENT_SPREAD_PIPS.get(pair, 2.0)
    results = []

    for dist in DISTANCE_RANGE:
        for tp in TP_RANGE:
            for sl in SL_RANGE:
                all_pnl = []
                for key, data in filtered.items():
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
                    "distance": float(dist),
                    "tp": float(tp),
                    "sl": float(sl),
                    "score": metrics["ci_low"],
                    **metrics,
                })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


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

    best = results[0]
    best_sl = best["sl"]
    sl_results = [r for r in results if r["sl"] == best_sl]
    if not sl_results:
        return

    distances = sorted(set(r["distance"] for r in sl_results))
    tps = sorted(set(r["tp"] for r in sl_results))

    matrix = np.full((len(distances), len(tps)), np.nan)
    sharpe_matrix = np.full((len(distances), len(tps)), np.nan)
    for r in sl_results:
        i = distances.index(r["distance"])
        j = tps.index(r["tp"])
        matrix[i, j] = r["mean_pnl"]
        sharpe_matrix[i, j] = r["sharpe"]

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))

    # Mean P&L heatmap
    vmax = max(abs(np.nanmin(matrix)), abs(np.nanmax(matrix)))
    norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)
    im = axes[0].imshow(matrix, cmap="RdYlGn", norm=norm, aspect="auto", origin="lower")
    axes[0].set_xticks(range(len(tps)))
    axes[0].set_xticklabels([f"{t:.0f}" for t in tps], rotation=45)
    axes[0].set_yticks(range(len(distances)))
    axes[0].set_yticklabels([f"{d:.0f}" for d in distances])
    axes[0].set_xlabel("Take Profit (pips)")
    axes[0].set_ylabel("Distance (pips)")
    axes[0].set_title(f"{pair} — Mean P&L per trade (pips)\n[SL={best_sl:.0f} pips, 1-min bars]")
    plt.colorbar(im, ax=axes[0], label="P&L (pips)")

    best_di = distances.index(best["distance"])
    best_ti = tps.index(best["tp"])
    axes[0].plot(best_ti, best_di, "k*", markersize=15)

    # Sharpe heatmap
    smax = max(abs(np.nanmin(sharpe_matrix)), abs(np.nanmax(sharpe_matrix)), 0.1)
    norm2 = TwoSlopeNorm(vmin=-smax, vcenter=0, vmax=smax)
    im2 = axes[1].imshow(sharpe_matrix, cmap="RdYlGn", norm=norm2, aspect="auto", origin="lower")
    axes[1].set_xticks(range(len(tps)))
    axes[1].set_xticklabels([f"{t:.0f}" for t in tps], rotation=45)
    axes[1].set_yticks(range(len(distances)))
    axes[1].set_yticklabels([f"{d:.0f}" for d in distances])
    axes[1].set_xlabel("Take Profit (pips)")
    axes[1].set_ylabel("Distance (pips)")
    axes[1].set_title(f"{pair} — Sharpe Ratio\n[SL={best_sl:.0f} pips, 1-min bars]")
    plt.colorbar(im2, ax=axes[1], label="Sharpe")
    axes[1].plot(best_ti, best_di, "k*", markersize=15)

    plt.tight_layout()
    path = output_dir / f"heatmap_1min_{pair}.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"Saved heatmap: {path}")


def generate_pnl_distribution(results: list[dict], all_data: dict, pair: str, output_dir: Path):
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
    pair_data = {k: v for k, v in all_data.items() if v["pair"] == pair}

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

    axes[0].hist(pnl_arr, bins=30, color="steelblue", edgecolor="white", alpha=0.8)
    axes[0].axvline(0, color="red", linestyle="--", linewidth=1)
    axes[0].axvline(pnl_arr.mean(), color="green", linestyle="-", linewidth=2,
                    label=f"Mean: {pnl_arr.mean():.1f}")
    axes[0].set_xlabel("P&L per trade (pips)")
    axes[0].set_ylabel("Frequency")
    axes[0].set_title(f"{pair} — Per-Trade P&L Distribution (1-min)\n"
                      f"[D={best['distance']:.0f} TP={best['tp']:.0f} SL={best['sl']:.0f}]")
    axes[0].legend()

    ci_low = np.percentile(boot_means, 2.5)
    ci_high = np.percentile(boot_means, 97.5)
    axes[1].hist(boot_means, bins=50, color="darkorange", edgecolor="white", alpha=0.8)
    axes[1].axvline(ci_low, color="red", linestyle="--",
                    label=f"95% CI: [{ci_low:.1f}, {ci_high:.1f}]")
    axes[1].axvline(ci_high, color="red", linestyle="--")
    axes[1].axvline(np.mean(boot_means), color="green", linestyle="-", linewidth=2)
    axes[1].set_xlabel("Mean P&L per trade (pips)")
    axes[1].set_ylabel("Bootstrap frequency")
    axes[1].set_title(f"{pair} — Bootstrap Distribution of Mean P&L\n(N={N_BOOTSTRAP:,} resamples)")
    axes[1].legend()

    plt.tight_layout()
    path = output_dir / f"pnl_dist_1min_{pair}.png"
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
    all_data: dict,
) -> str:
    """Generate a comprehensive markdown report."""
    n_events = len(events)
    n_data = len(all_data)
    pairs = list(all_results.keys())

    lines = [
        "# Straddle Parameter Optimization Report (1-min Dukascopy Data)",
        "",
        "## Executive Summary",
        "",
        f"- **Analysis period**: January 2020 — June 2026",
        f"- **Events analyzed**: {n_events} (NFP: {len(_nfp_dates())}, CPI: {len(_cpi_dates())}, FOMC: {len(_fomc_dates())})",
        f"- **Data points loaded**: {n_data} (event x pair combinations)",
        f"- **Pairs**: {', '.join(pairs)}",
        f"- **Data source**: Dukascopy Bank SA (1-minute OHLCV bars)",
        f"- **Monte Carlo iterations**: {N_BOOTSTRAP:,}",
        f"- **Confidence level**: {CONFIDENCE_LEVEL*100:.0f}%",
        "",
        "### Methodology",
        "",
        "1. Loaded 1-minute bars from Dukascopy for a 6-hour window around each event (-2h / +4h)",
        "2. Simulated straddle mechanics (buy stop + sell stop, each with TP/SL) using 1-min OHLC",
        "3. Grid search over distance (10-50), TP (15-70), SL (10-30) — all in pips",
        "4. Bootstrap resampled 10,000x to build confidence intervals",
        "5. Scored on pessimistic metric: lower bound of 95% CI on mean P&L",
        "6. Bonferroni correction applied: CIs widened for the number of pairs tested simultaneously",
        "7. Walk-forward validation: train on 2020-2024, test on 2025-2026",
        "8. Spread modeled as fixed cost (conservative event-time estimates)",
        "",
        "### Improvement over hourly data",
        "",
        "The previous optimization used 1-hour bars from IB paper accounts. When both TP",
        "and SL could be hit within the same hourly bar, SL was assumed first (pessimistic).",
        "With 1-minute bars, we can observe the actual price sequence and determine which",
        "level was hit first. This removes the systematic negative bias in the old results.",
        "",
        "---",
        "",
        "## Optimal Parameters by Pair",
        "",
        "| Pair | Distance | TP | SL | E[P&L] | 95% CI | Bonferroni CI | Win Rate | Sharpe | PF | N |",
        "|------|----------|----|----|--------|--------|---------------|----------|--------|----|---|",
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
            f"[{best.get('ci_low_bonf', best['ci_low']):+.1f}, {best.get('ci_high_bonf', best['ci_high']):+.1f}] | "
            f"{best['win_rate']*100:.1f}% | {best['sharpe']:.2f} | "
            f"{best['profit_factor']:.2f} | {best['n_trades']} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Walk-Forward Validation",
        "",
        "Train on 2020-2024 data (5 years), test on 2025-2026 data (18 months).",
        "",
        "| Pair | Params | In-Sample E[P&L] | In-Sample Sharpe | Out-of-Sample E[P&L] | Out-of-Sample Sharpe |",
        "|------|--------|-------------------|------------------|----------------------|----------------------|",
    ]

    for pair in pairs:
        wf = wf_results.get(pair, {})
        if wf.get("status") == "insufficient_train_data":
            lines.append(f"| {pair} | — | — | — | — | — |")
            continue
        p = wf.get("optimal_params", {})
        is_data = wf.get("in_sample", {})
        os_data = wf.get("out_of_sample", {})
        is_years = is_data.get("years", [])
        os_years = os_data.get("years", [])
        lines.append(
            f"| **{pair}** | {p.get('distance', 0):.0f}/{p.get('tp', 0):.0f}/{p.get('sl', 0):.0f} | "
            f"{is_data.get('mean_pnl', 0):+.1f} | {is_data.get('sharpe', 0):.2f} | "
            f"{os_data.get('mean_pnl', 0):+.1f} | {os_data.get('sharpe', 0):.2f} |"
        )

    lines += [
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
        "```yaml",
        "strategy:",
    ]

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
        "### Per-pair overrides:",
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
        "## Caveats",
        "",
        "1. **Regime changes**: 6.5 years spans COVID (2020), rate hikes (2022-2023),",
        "   and normalization (2024-2026). Parameters optimized across all regimes may",
        "   not be optimal for any single regime.",
        "",
        "2. **Spread approximation**: Event-time spreads are fixed estimates. Exotic",
        "   pairs (USDZAR, USDTRY) can exceed 50 pips during NFP.",
        "",
        "3. **Slippage not modeled**: Stop orders can gap through during fast markets.",
        "",
        "4. **Bid-side data only**: Dukascopy data is bid OHLCV. The ask side is",
        "   approximated via the spread adjustment.",
        "",
        "5. **Multiple testing**: Grid search over ~540 combos across N pairs inflates false",
        "   positives. Bonferroni correction adjusts CIs by the number of pairs tested.",
        "   Walk-forward validation provides an additional out-of-sample guard.",
        "",
        "6. **FOMC dynamics differ**: Rate decisions move differently from data releases.",
        "",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Monte Carlo Straddle Optimization (1-min Dukascopy)")
    parser.add_argument("--pairs", nargs="+", default=PAIRS, help="Pairs to analyze")
    args = parser.parse_args()

    events = get_all_events()
    logger.info(f"Event schedule: {len(events)} events ({len(_nfp_dates())} NFP, "
                f"{len(_cpi_dates())} CPI, {len(_fomc_dates())} FOMC)")

    # Phase 1: Load Dukascopy data
    logger.info("Loading Dukascopy 1-min data...")
    all_data: dict[str, dict] = {}
    for pair in args.pairs:
        pair_data = load_dukascopy_data(pair)
        all_data.update(pair_data)

    if not all_data:
        logger.error("No data loaded. Run scripts/download_dukascopy.py first.")
        sys.exit(1)

    logger.info(f"Total: {len(all_data)} event/pair data sets loaded")

    # Phase 2: Grid Search Optimization
    logger.info("Starting grid search optimization...")
    t0 = time.time()
    n_pairs = len(args.pairs)
    all_results: dict[str, list[dict]] = {}
    for pair in args.pairs:
        logger.info(f"Optimizing {pair}...")
        results = run_grid_search(all_data, pair, n_comparisons=n_pairs)
        all_results[pair] = results
        if results:
            best = results[0]
            logger.info(
                f"  {pair} best: D={best['distance']:.0f} TP={best['tp']:.0f} SL={best['sl']:.0f} "
                f"E[PnL]={best['mean_pnl']:+.1f} CI=[{best['ci_low']:+.1f},{best['ci_high']:+.1f}] "
                f"WR={best['win_rate']*100:.1f}% Sharpe={best['sharpe']:.2f}"
            )

    # Phase 3: Walk-Forward Validation (train 2020-2024, test 2025-2026)
    train_years = [2020, 2021, 2022, 2023, 2024]
    test_years = [2025, 2026]
    logger.info(f"Running walk-forward validation (train {train_years[0]}-{train_years[-1]}, test {test_years[0]}-{test_years[-1]})...")
    wf_results: dict[str, dict] = {}
    for pair in args.pairs:
        wf = walk_forward_validate(all_data, pair, train_years=train_years, test_years=test_years)
        wf_results[pair] = wf

    elapsed = time.time() - t0
    logger.info(f"Optimization completed in {elapsed:.0f}s")

    # Phase 4: Visualization
    logger.info("Generating visualizations...")
    for pair in args.pairs:
        generate_heatmaps(all_results.get(pair, []), pair, DATA_DIR)
        generate_pnl_distribution(all_results.get(pair, []), all_data, pair, DATA_DIR)

    # Phase 5: Report
    report = generate_report(all_results, wf_results, events, all_data)
    with open(REPORT_FILE, "w") as f:
        f.write(report)
    logger.info(f"Report saved to {REPORT_FILE}")

    print("\n" + report)

    # Save raw results
    serializable = {}
    for pair, results in all_results.items():
        serializable[pair] = results[:20]
    with open(RESULTS_FILE, "w") as f:
        json.dump(serializable, f, indent=2)


if __name__ == "__main__":
    main()
