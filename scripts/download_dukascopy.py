#!/usr/bin/env python3
"""
Dukascopy Historical Data Downloader
=====================================

Downloads 1-minute and 5-minute OHLCV bar data from Dukascopy Bank SA for all
5 trading pairs around major US economic events (NFP, CPI, FOMC).

Downloads a configurable window around each event (default: 2 hours before,
4 hours after) at 1-min resolution. Also saves 5-min resampled bars.

Data is saved per-pair as CSV in scripts/data/dukascopy/.

Usage:
  python scripts/download_dukascopy.py                    # Download all pairs, all events
  python scripts/download_dukascopy.py --pair GBPUSD      # Single pair
  python scripts/download_dukascopy.py --timeframe 5min   # 5-min bars only
  python scripts/download_dukascopy.py --skip-existing     # Skip already-downloaded event windows
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import dukascopy_python as dp
import pandas as pd
from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "scripts" / "data" / "dukascopy"

PAIRS = ["GBPUSD", "USDCAD", "GBPJPY", "USDZAR", "USDTRY"]

# Map our pair names to Dukascopy instrument strings
DUKASCOPY_INSTRUMENTS = {
    "GBPUSD": "GBP/USD",
    "USDCAD": "USD/CAD",
    "GBPJPY": "GBP/JPY",
    "USDZAR": "USD/ZAR",
    "USDTRY": "USD/TRY",
}

# How much data to grab around each event
PRE_EVENT_HOURS = 2
POST_EVENT_HOURS = 4

# Dukascopy rate limiting — be polite
REQUEST_DELAY_SECS = 1.5

# ---------------------------------------------------------------------------
# Event Schedule (2020-01 to 2026-06)
# NFP: first Friday of each month, 8:30 AM ET
# CPI: mid-month release, 8:30 AM ET
# FOMC: scheduled meeting dates, 2:00 PM ET
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
        # 2020 (emergency cuts in March not included — only scheduled meetings)
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
# Download Logic
# ---------------------------------------------------------------------------


def fetch_event_bars(
    pair: str,
    event: dict,
    timeframe: str,
) -> pd.DataFrame | None:
    """Fetch OHLCV bars for a single pair/event from Dukascopy.

    Args:
        pair: e.g. "GBPUSD"
        event: dict with 'utc_dt', 'name', 'date'
        timeframe: "1min" or "5min"

    Returns:
        DataFrame with OHLCV data, or None on failure.
    """
    instrument = DUKASCOPY_INSTRUMENTS[pair]
    event_utc = event["utc_dt"]
    start = event_utc - timedelta(hours=PRE_EVENT_HOURS)
    end = event_utc + timedelta(hours=POST_EVENT_HOURS)

    interval = dp.INTERVAL_MIN_1 if timeframe == "1min" else dp.INTERVAL_MIN_5

    try:
        df = dp.fetch(
            instrument,
            interval,
            dp.OFFER_SIDE_BID,
            start,
            end,
        )
        if df is None or df.empty:
            logger.warning(f"No data for {pair} {event['name']} {event['date']}")
            return None

        # Add metadata columns
        df["pair"] = pair
        df["event_name"] = event["name"]
        df["event_date"] = event["date"]
        df["event_utc"] = event_utc.isoformat()

        return df

    except Exception as exc:
        logger.error(f"Failed {pair} {event['name']} {event['date']}: {exc}")
        return None


def output_path(pair: str, timeframe: str) -> Path:
    """Return the CSV output path for a pair/timeframe."""
    return DATA_DIR / f"{pair}_{timeframe}.csv"


def load_existing_events(path: Path) -> set[str]:
    """Load event dates already present in a CSV to support --skip-existing."""
    if not path.exists():
        return set()
    try:
        df = pd.read_csv(path, usecols=["event_date", "event_name"])
        return {f"{row.event_name}_{row.event_date}" for row in df.itertuples()}
    except Exception:
        return set()


def download_pair(
    pair: str,
    events: list[dict],
    timeframe: str,
    skip_existing: bool,
) -> int:
    """Download all event windows for a single pair.

    Returns the number of events successfully downloaded.
    """
    csv_path = output_path(pair, timeframe)
    existing = load_existing_events(csv_path) if skip_existing else set()

    frames: list[pd.DataFrame] = []
    downloaded = 0

    for i, event in enumerate(events, 1):
        event_key = f"{event['name']}_{event['date']}"

        if event_key in existing:
            logger.debug(f"Skipping {pair} {event_key} (already downloaded)")
            continue

        # Skip future events (no data yet)
        if event["utc_dt"] > datetime.now(tz=UTC).replace(tzinfo=None):
            logger.debug(f"Skipping {pair} {event_key} (future event)")
            continue

        logger.info(
            f"[{pair}] {event['name']} {event['date']} "
            f"({i}/{len(events)})"
        )

        df = fetch_event_bars(pair, event, timeframe)
        if df is not None:
            frames.append(df)
            downloaded += 1

        time.sleep(REQUEST_DELAY_SECS)

    if not frames:
        logger.info(f"[{pair}] No new data to save")
        return downloaded

    new_data = pd.concat(frames)

    # Append to existing CSV or create new one
    if csv_path.exists() and skip_existing:
        old = pd.read_csv(csv_path, index_col=0, parse_dates=True)
        combined = pd.concat([old, new_data])
        combined.sort_index(inplace=True)
        combined.to_csv(csv_path)
        logger.info(
            f"[{pair}] Appended {len(new_data)} rows -> {csv_path.name} "
            f"(total: {len(combined)})"
        )
    else:
        new_data.sort_index(inplace=True)
        new_data.to_csv(csv_path)
        logger.info(f"[{pair}] Saved {len(new_data)} rows -> {csv_path.name}")

    return downloaded


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download historical forex data from Dukascopy around US economic events."
    )
    parser.add_argument(
        "--pair",
        choices=PAIRS,
        help="Download a single pair (default: all 5)",
    )
    parser.add_argument(
        "--timeframe",
        choices=["1min", "5min", "both"],
        default="both",
        help="Bar timeframe to download (default: both)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip events already present in the output CSV",
    )
    parser.add_argument(
        "--pre-hours",
        type=int,
        default=PRE_EVENT_HOURS,
        help=f"Hours before event to download (default: {PRE_EVENT_HOURS})",
    )
    parser.add_argument(
        "--post-hours",
        type=int,
        default=POST_EVENT_HOURS,
        help=f"Hours after event to download (default: {POST_EVENT_HOURS})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Allow overriding the window
    global PRE_EVENT_HOURS, POST_EVENT_HOURS
    PRE_EVENT_HOURS = args.pre_hours
    POST_EVENT_HOURS = args.post_hours

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    pairs = [args.pair] if args.pair else PAIRS
    timeframes = ["1min", "5min"] if args.timeframe == "both" else [args.timeframe]
    events = get_all_events()

    logger.info(
        f"Downloading {len(pairs)} pair(s) x {len(events)} events x "
        f"{len(timeframes)} timeframe(s) "
        f"(window: -{PRE_EVENT_HOURS}h / +{POST_EVENT_HOURS}h)"
    )

    total_downloaded = 0
    t0 = time.time()

    for tf in timeframes:
        for pair in pairs:
            logger.info(f"--- {pair} @ {tf} ---")
            n = download_pair(pair, events, tf, args.skip_existing)
            total_downloaded += n

    elapsed = time.time() - t0
    logger.info(
        f"Done. Downloaded {total_downloaded} event windows in {elapsed:.0f}s. "
        f"Data saved to {DATA_DIR}/"
    )


if __name__ == "__main__":
    main()
