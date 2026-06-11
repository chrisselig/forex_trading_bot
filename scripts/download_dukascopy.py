#!/usr/bin/env python3
"""
Dukascopy Historical Data Downloader
=====================================

Downloads 1-minute and 5-minute OHLCV bar data from Dukascopy Bank SA for
trading pairs around major economic events (US, Canada, Japan, South Africa,
Turkey).

Downloads a configurable window around each event (default: 2 hours before,
4 hours after) at 1-min resolution. Also saves 5-min resampled bars.

Data is saved per-pair as CSV in scripts/data/dukascopy/.

Usage:
  python scripts/download_dukascopy.py                        # Download all event groups
  python scripts/download_dukascopy.py --group us             # US events only
  python scripts/download_dukascopy.py --group canada,japan   # Multiple groups
  python scripts/download_dukascopy.py --pair USDCAD          # Single pair
  python scripts/download_dukascopy.py --timeframe 5min       # 5-min bars only
  python scripts/download_dukascopy.py --skip-existing        # Skip already-downloaded windows
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

PAIRS = ["GBPUSD", "USDCAD", "GBPJPY", "USDZAR", "USDTRY", "USDJPY", "EURUSD", "AUDUSD"]

# Map our pair names to Dukascopy instrument strings
DUKASCOPY_INSTRUMENTS = {
    "GBPUSD": "GBP/USD",
    "USDCAD": "USD/CAD",
    "GBPJPY": "GBP/JPY",
    "USDZAR": "USD/ZAR",
    "USDTRY": "USD/TRY",
    "USDJPY": "USD/JPY",
    "EURUSD": "EUR/USD",
    "AUDUSD": "AUD/USD",
}

# Which pairs to download for each event type
EVENT_PAIRS: dict[str, list[str]] = {
    # US events — download all pairs (any could react)
    "NFP": PAIRS,
    "CPI": PAIRS,
    "FOMC": PAIRS,
    "PPI": PAIRS,
    "GDP": PAIRS,
    "PCE": PAIRS,
    # Canada events — primarily moves USDCAD
    "BOC Rate Decision": ["USDCAD"],
    "Canada CPI": ["USDCAD"],
    "Canada Employment": ["USDCAD"],
    # Japan events — primarily moves USDJPY
    "BOJ Rate Decision": ["USDJPY"],
    "Japan CPI": ["USDJPY"],
    # South Africa events — primarily moves USDZAR
    "SARB Rate Decision": ["USDZAR"],
    "South Africa CPI": ["USDZAR"],
    # Turkey events — primarily moves USDTRY
    "TCMB Rate Decision": ["USDTRY"],
}

# Event groups for CLI filtering
EVENT_GROUPS: dict[str, list[str]] = {
    "us": ["NFP", "CPI", "FOMC", "PPI", "GDP", "PCE"],
    "canada": ["BOC Rate Decision", "Canada CPI", "Canada Employment"],
    "japan": ["BOJ Rate Decision", "Japan CPI"],
    "south_africa": ["SARB Rate Decision", "South Africa CPI"],
    "turkey": ["TCMB Rate Decision"],
}

# How much data to grab around each event
PRE_EVENT_HOURS = 2
POST_EVENT_HOURS = 4

# Dukascopy rate limiting — be polite
REQUEST_DELAY_SECS = 1.5

# ---------------------------------------------------------------------------
# Event Schedule (2020-01 to 2026-06)
#
# US events:
#   NFP: first Friday of each month, 8:30 AM ET
#   CPI: mid-month release, 8:30 AM ET
#   FOMC: scheduled meeting dates, 2:00 PM ET
#
# Canada events:
#   BOC Rate Decision: 10:00 AM ET (8/year)
#   Canada CPI: 8:30 AM ET (monthly)
#   Canada Employment: 8:30 AM ET (monthly)
#
# Japan events (times in UTC, not ET):
#   BOJ Rate Decision: ~03:00 UTC / 12:00 PM JST
#   Japan CPI: 23:30 UTC / 8:30 AM JST (prior day in UTC)
#
# Emerging market events:
#   SARB Rate Decision: 09:00 ET / 3:00 PM SAST (6/year)
#   TCMB Rate Decision: 07:00 ET / 2:00 PM TRT (8-12/year)
#   South Africa CPI: 04:00 ET / 10:00 AM SAST (monthly)
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
        # 2026 (FRED release calendar, rid=50)
        "2026-01-09", "2026-02-06", "2026-03-06", "2026-04-03", "2026-05-01",
        "2026-06-05", "2026-07-02", "2026-08-07", "2026-09-04", "2026-10-02",
        "2026-11-06", "2026-12-04",
    ]
    return [{"name": "NFP", "date": d, "time": "08:30", "tz": "ET"} for d in dates]


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
        # 2026 (FRED release calendar, rid=10)
        "2026-01-14", "2026-02-11", "2026-03-11", "2026-04-14", "2026-05-12",
        "2026-06-10", "2026-07-14", "2026-08-12", "2026-09-11", "2026-10-14",
        "2026-11-10", "2026-12-10",
    ]
    return [{"name": "CPI", "date": d, "time": "08:30", "tz": "ET"} for d in dates]


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
        # 2026 (Federal Reserve FOMC calendar)
        "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
        "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
        # 2027
        "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09",
        "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08",
    ]
    return [{"name": "FOMC", "date": d, "time": "14:00", "tz": "ET"} for d in dates]


def _ppi_dates() -> list[dict]:
    """PPI m/m — monthly, 8:30 AM ET. Dates from FRED release calendar (rid=46)."""
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
        # NOTE: Oct-Nov 2025 disrupted by government shutdown
        "2025-11-25",
        # 2026 (FRED release calendar, rid=46)
        "2026-01-14", "2026-02-27", "2026-03-18", "2026-04-14", "2026-05-13",
        "2026-06-11", "2026-07-15", "2026-08-13", "2026-09-10", "2026-10-15",
        "2026-11-13", "2026-12-15",
    ]
    return [{"name": "PPI", "date": d, "time": "08:30", "tz": "ET"} for d in dates]


def _gdp_dates() -> list[dict]:
    """GDP q/q (Advance/Preliminary/Final) — 8:30 AM ET. FRED rid=53."""
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
        "2025-12-23",
        # 2026 (FRED release calendar, rid=53; BEA schedule)
        "2026-01-22", "2026-02-20", "2026-03-13", "2026-04-09", "2026-05-28",
        "2026-06-25", "2026-07-30", "2026-08-26", "2026-09-30", "2026-10-29",
        "2026-11-25", "2026-12-23",
    ]
    return [{"name": "GDP", "date": d, "time": "08:30", "tz": "ET"} for d in dates]


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
        "2025-12-05",
        # 2026 (FRED release calendar, rid=54; BEA schedule)
        "2026-01-22", "2026-02-20", "2026-03-13", "2026-04-09", "2026-05-28",
        "2026-06-25", "2026-07-30", "2026-08-26", "2026-09-30", "2026-10-29",
        "2026-11-25", "2026-12-23",
    ]
    return [{"name": "PCE", "date": d, "time": "08:30", "tz": "ET"} for d in dates]


# ---------------------------------------------------------------------------
# Canada Events
# ---------------------------------------------------------------------------


def _boc_rate_dates() -> list[dict]:
    """Bank of Canada Rate Decision — 10:00 AM ET."""
    dates = [
        # 2020
        "2020-01-22", "2020-03-04", "2020-04-15", "2020-06-03",
        "2020-07-15", "2020-09-09", "2020-10-28", "2020-12-09",
        # 2021
        "2021-01-20", "2021-03-10", "2021-04-21", "2021-06-09",
        "2021-07-14", "2021-09-08", "2021-10-27", "2021-12-08",
        # 2022
        "2022-01-26", "2022-03-02", "2022-04-13", "2022-06-01",
        "2022-07-13", "2022-09-07", "2022-10-26", "2022-12-07",
        # 2023
        "2023-01-25", "2023-03-08", "2023-04-12", "2023-06-07",
        "2023-07-12", "2023-09-06", "2023-10-25", "2023-12-06",
        # 2024
        "2024-01-24", "2024-03-06", "2024-04-10", "2024-06-05",
        "2024-07-24", "2024-09-04", "2024-10-23", "2024-12-11",
        # 2025
        "2025-01-29", "2025-03-12", "2025-04-16", "2025-06-04",
        "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
        # 2026 (Bank of Canada schedule)
        "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-10",
        "2026-07-15", "2026-09-02", "2026-10-28", "2026-12-09",
    ]
    return [{"name": "BOC Rate Decision", "date": d, "time": "10:00", "tz": "ET"} for d in dates]


def _canada_cpi_dates() -> list[dict]:
    """Canada CPI — 8:30 AM ET, monthly."""
    dates = [
        # 2020
        "2020-01-22", "2020-02-19", "2020-03-18", "2020-04-22", "2020-05-20",
        "2020-06-17", "2020-07-22", "2020-08-19", "2020-09-16", "2020-10-21",
        "2020-11-18", "2020-12-16",
        # 2021
        "2021-01-20", "2021-02-17", "2021-03-17", "2021-04-21", "2021-05-19",
        "2021-06-16", "2021-07-28", "2021-08-18", "2021-09-15", "2021-10-20",
        "2021-11-17", "2021-12-15",
        # 2022
        "2022-01-19", "2022-02-16", "2022-03-16", "2022-04-20", "2022-05-18",
        "2022-06-22", "2022-07-20", "2022-08-16", "2022-09-20", "2022-10-19",
        "2022-11-16", "2022-12-21",
        # 2023
        "2023-01-17", "2023-02-21", "2023-03-21", "2023-04-18", "2023-05-16",
        "2023-06-27", "2023-07-18", "2023-08-15", "2023-09-19", "2023-10-17",
        "2023-11-21", "2023-12-19",
        # 2024
        "2024-01-16", "2024-02-20", "2024-03-19", "2024-04-16", "2024-05-21",
        "2024-06-25", "2024-07-16", "2024-08-20", "2024-09-17", "2024-10-15",
        "2024-11-19", "2024-12-17",
        # 2025
        "2025-01-21", "2025-02-18", "2025-03-18", "2025-04-15", "2025-05-20",
        "2025-06-24", "2025-07-15", "2025-08-19", "2025-09-16", "2025-10-21",
        "2025-11-17", "2025-12-15",
        # 2026 (Jan-Jun from Stats Canada; Jul-Dec estimated 3rd Tuesday)
        "2026-01-19", "2026-02-17", "2026-03-16", "2026-04-20", "2026-05-19",
        "2026-06-22", "2026-07-21", "2026-08-18", "2026-09-15", "2026-10-20",
        "2026-11-17", "2026-12-15",
    ]
    return [{"name": "Canada CPI", "date": d, "time": "08:30", "tz": "ET"} for d in dates]


def _canada_employment_dates() -> list[dict]:
    """Canada Employment (Labour Force Survey) — 8:30 AM ET, monthly."""
    dates = [
        # 2020
        "2020-01-10", "2020-02-07", "2020-03-06", "2020-04-09", "2020-05-08",
        "2020-06-05", "2020-07-10", "2020-08-07", "2020-09-04", "2020-10-09",
        "2020-11-06", "2020-12-04",
        # 2021
        "2021-01-08", "2021-02-05", "2021-03-12", "2021-04-09", "2021-05-07",
        "2021-06-04", "2021-07-09", "2021-08-06", "2021-09-10", "2021-10-08",
        "2021-11-05", "2021-12-03",
        # 2022
        "2022-01-07", "2022-02-04", "2022-03-11", "2022-04-08", "2022-05-06",
        "2022-06-10", "2022-07-08", "2022-08-05", "2022-09-09", "2022-10-07",
        "2022-11-04", "2022-12-02",
        # 2023
        "2023-01-06", "2023-02-10", "2023-03-10", "2023-04-06", "2023-05-05",
        "2023-06-09", "2023-07-07", "2023-08-04", "2023-09-08", "2023-10-06",
        "2023-11-03", "2023-12-01",
        # 2024
        "2024-01-05", "2024-02-09", "2024-03-08", "2024-04-05", "2024-05-10",
        "2024-06-07", "2024-07-05", "2024-08-09", "2024-09-06", "2024-10-11",
        "2024-11-08", "2024-12-06",
        # 2025
        "2025-01-10", "2025-02-07", "2025-03-07", "2025-04-04", "2025-05-09",
        "2025-06-06", "2025-07-11", "2025-08-08", "2025-09-05", "2025-10-10",
        "2025-11-07", "2025-12-05",
        # 2026 (Jan-Jun from Stats Canada; Jul-Dec estimated 2nd Friday)
        "2026-01-09", "2026-02-06", "2026-03-13", "2026-04-10", "2026-05-08",
        "2026-06-05", "2026-07-10", "2026-08-14", "2026-09-11", "2026-10-09",
        "2026-11-13", "2026-12-11",
    ]
    return [{"name": "Canada Employment", "date": d, "time": "08:30", "tz": "ET"} for d in dates]


# ---------------------------------------------------------------------------
# Japan Events (times in UTC — BOJ/CPI happen during Asian hours)
# ---------------------------------------------------------------------------


def _boj_rate_dates() -> list[dict]:
    """BOJ Rate Decision — ~12:00 PM JST / 03:00 UTC."""
    dates = [
        # 2020 (includes 2 emergency COVID meetings)
        "2020-01-21", "2020-03-16", "2020-04-27", "2020-05-22",
        "2020-06-16", "2020-07-15", "2020-09-17", "2020-10-29", "2020-12-18",
        # 2021
        "2021-01-21", "2021-03-19", "2021-04-27", "2021-06-18",
        "2021-07-16", "2021-09-22", "2021-10-28", "2021-12-17",
        # 2022
        "2022-01-18", "2022-03-18", "2022-04-28", "2022-06-17",
        "2022-07-21", "2022-09-22", "2022-10-28", "2022-12-20",
        # 2023
        "2023-01-18", "2023-03-10", "2023-04-28", "2023-06-16",
        "2023-07-28", "2023-09-22", "2023-10-31", "2023-12-19",
        # 2024
        "2024-01-23", "2024-03-19", "2024-04-26", "2024-06-14",
        "2024-07-31", "2024-09-20", "2024-10-31", "2024-12-19",
        # 2025
        "2025-01-24", "2025-03-19", "2025-05-01", "2025-06-17",
        "2025-07-31", "2025-09-19", "2025-10-30", "2025-12-19",
        # 2026 (Bank of Japan official schedule)
        "2026-01-23", "2026-03-19", "2026-04-28", "2026-06-16",
        "2026-07-31", "2026-09-18", "2026-10-30", "2026-12-18",
    ]
    return [{"name": "BOJ Rate Decision", "date": d, "time": "12:00", "tz": "JST"} for d in dates]


def _japan_cpi_dates() -> list[dict]:
    """Japan National CPI — 8:30 AM JST = 23:30 UTC the prior calendar day.

    Dates listed are JST release dates. Since 8:30 AM JST = 23:30 UTC the
    previous day, we use tz="JST" and time="08:30" so get_all_events() can
    convert correctly (JST = UTC+9).
    """
    dates = [
        # 2020
        "2020-01-24", "2020-02-21", "2020-03-19", "2020-04-24", "2020-05-22",
        "2020-06-19", "2020-07-24", "2020-08-21", "2020-09-18", "2020-10-23",
        "2020-11-20", "2020-12-18",
        # 2021
        "2021-01-22", "2021-02-19", "2021-03-19", "2021-04-23", "2021-05-21",
        "2021-06-18", "2021-07-23", "2021-08-20", "2021-09-24", "2021-10-22",
        "2021-11-19", "2021-12-24",
        # 2022
        "2022-01-21", "2022-02-18", "2022-03-18", "2022-04-22", "2022-05-20",
        "2022-06-24", "2022-07-22", "2022-08-19", "2022-09-20", "2022-10-21",
        "2022-11-18", "2022-12-23",
        # 2023
        "2023-01-20", "2023-02-24", "2023-03-24", "2023-04-21", "2023-05-19",
        "2023-06-23", "2023-07-21", "2023-08-18", "2023-09-22", "2023-10-20",
        "2023-11-24", "2023-12-22",
        # 2024
        "2024-01-19", "2024-02-27", "2024-03-22", "2024-04-19", "2024-05-24",
        "2024-06-21", "2024-07-19", "2024-08-23", "2024-09-20", "2024-10-18",
        "2024-11-22", "2024-12-20",
        # 2025
        "2025-01-24", "2025-02-21", "2025-03-21", "2025-04-18", "2025-05-23",
        "2025-06-20", "2025-07-18", "2025-08-22", "2025-09-19", "2025-10-24",
        "2025-11-21", "2025-12-19",
        # 2026 (Jan-Jun from Statistics Bureau; Jul-Dec estimated 3rd/4th Friday)
        "2026-01-23", "2026-02-20", "2026-03-24", "2026-04-24", "2026-05-22",
        "2026-06-19", "2026-07-17", "2026-08-21", "2026-09-18", "2026-10-23",
        "2026-11-20", "2026-12-18",
    ]
    return [{"name": "Japan CPI", "date": d, "time": "08:30", "tz": "JST"} for d in dates]


# ---------------------------------------------------------------------------
# Emerging Market Events
# ---------------------------------------------------------------------------


def _sarb_rate_dates() -> list[dict]:
    """SARB Rate Decision — 3:00 PM SAST / 09:00 ET."""
    dates = [
        # 2020 (includes extraordinary COVID meeting Apr 14)
        "2020-01-16", "2020-03-19", "2020-04-14", "2020-05-21",
        "2020-07-23", "2020-09-17", "2020-11-19",
        # 2021
        "2021-01-21", "2021-03-25", "2021-05-20",
        "2021-07-22", "2021-09-23", "2021-11-18",
        # 2022
        "2022-01-27", "2022-03-24", "2022-05-19",
        "2022-07-21", "2022-09-22", "2022-11-24",
        # 2023
        "2023-01-26", "2023-03-30", "2023-05-25",
        "2023-07-20", "2023-09-21", "2023-11-23",
        # 2024
        "2024-01-25", "2024-03-27", "2024-05-30",
        "2024-07-18", "2024-09-19", "2024-11-21",
        # 2025
        "2025-01-30", "2025-03-20", "2025-05-29",
        "2025-07-31", "2025-09-18", "2025-11-20",
        # 2026 (SARB website; matches static_events.yaml)
        "2026-01-29", "2026-03-26", "2026-05-28",
        "2026-07-23", "2026-09-24", "2026-11-19",
    ]
    return [{"name": "SARB Rate Decision", "date": d, "time": "09:00", "tz": "ET"} for d in dates]


def _tcmb_rate_dates() -> list[dict]:
    """TCMB Rate Decision — 2:00 PM TRT / 07:00 ET."""
    dates = [
        # 2020
        "2020-01-16", "2020-02-19", "2020-03-17", "2020-04-22", "2020-05-21",
        "2020-06-25", "2020-07-23", "2020-08-20", "2020-09-24", "2020-10-22",
        "2020-11-19", "2020-12-24",
        # 2021
        "2021-01-21", "2021-02-18", "2021-03-18", "2021-04-15", "2021-05-06",
        "2021-06-17", "2021-07-14", "2021-08-12", "2021-09-23", "2021-10-21",
        "2021-11-18", "2021-12-16",
        # 2022
        "2022-01-20", "2022-02-17", "2022-03-17", "2022-04-14", "2022-05-26",
        "2022-06-23", "2022-07-21", "2022-08-18", "2022-09-22", "2022-10-20",
        "2022-11-24", "2022-12-22",
        # 2023
        "2023-01-19", "2023-02-23", "2023-03-23", "2023-04-27", "2023-05-25",
        "2023-06-22", "2023-07-20", "2023-08-24", "2023-09-21", "2023-10-26",
        "2023-11-23", "2023-12-21",
        # 2024
        "2024-01-25", "2024-02-22", "2024-03-21", "2024-04-25", "2024-05-23",
        "2024-06-27", "2024-07-23", "2024-08-20", "2024-09-19", "2024-10-17",
        "2024-11-21", "2024-12-26",
        # 2025
        "2025-01-23", "2025-03-06", "2025-03-20", "2025-04-17",
        "2025-06-19", "2025-07-24", "2025-09-11", "2025-10-23", "2025-12-11",
        # 2026 (TCMB website; matches static_events.yaml)
        "2026-01-22", "2026-03-12", "2026-04-22", "2026-06-11",
        "2026-06-19", "2026-07-24", "2026-08-21", "2026-09-18",
        "2026-10-23", "2026-11-20", "2026-12-25",
    ]
    return [{"name": "TCMB Rate Decision", "date": d, "time": "07:00", "tz": "ET"} for d in dates]


def _sa_cpi_dates() -> list[dict]:
    """South Africa CPI — 10:00 AM SAST / 04:00 ET."""
    dates = [
        # 2020
        "2020-01-15", "2020-02-19", "2020-03-18", "2020-04-15", "2020-05-20",
        "2020-06-17", "2020-07-15", "2020-08-19", "2020-09-16", "2020-10-21",
        "2020-11-18", "2020-12-16",
        # 2021
        "2021-01-20", "2021-02-17", "2021-03-17", "2021-04-21", "2021-05-19",
        "2021-06-16", "2021-07-21", "2021-08-18", "2021-09-15", "2021-10-20",
        "2021-11-17", "2021-12-15",
        # 2022
        "2022-01-19", "2022-02-16", "2022-03-16", "2022-04-20", "2022-05-18",
        "2022-06-15", "2022-07-20", "2022-08-17", "2022-09-21", "2022-10-19",
        "2022-11-16", "2022-12-21",
        # 2023
        "2023-01-18", "2023-02-15", "2023-03-15", "2023-04-19", "2023-05-17",
        "2023-06-21", "2023-07-19", "2023-08-16", "2023-09-20", "2023-10-18",
        "2023-11-15", "2023-12-20",
        # 2024
        "2024-01-24", "2024-02-21", "2024-03-20", "2024-04-17", "2024-05-15",
        "2024-06-19", "2024-07-17", "2024-08-21", "2024-09-18", "2024-10-16",
        "2024-11-20", "2024-12-11",
        # 2025
        "2025-01-22", "2025-02-19", "2025-03-19", "2025-04-16", "2025-05-21",
        "2025-06-18", "2025-07-16", "2025-08-20", "2025-09-17", "2025-10-22",
        "2025-11-19", "2025-12-17",
        # 2026 (Stats SA; matches static_events.yaml)
        "2026-01-21", "2026-02-18", "2026-03-18", "2026-04-22", "2026-05-20",
        "2026-06-17", "2026-07-22", "2026-08-19", "2026-09-23", "2026-10-21",
        "2026-11-18", "2026-12-16",
    ]
    return [{"name": "South Africa CPI", "date": d, "time": "04:00", "tz": "ET"} for d in dates]


def get_all_events(groups: list[str] | None = None) -> list[dict]:
    """Return all events with UTC datetime.

    Args:
        groups: Optional list of event group names to include.
                Valid groups: us, canada, japan, south_africa, turkey.
                If None, includes all groups.
    """
    all_event_fns = {
        "NFP": _nfp_dates,
        "CPI": _cpi_dates,
        "FOMC": _fomc_dates,
        "PPI": _ppi_dates,
        "GDP": _gdp_dates,
        "PCE": _pce_dates,
        "BOC Rate Decision": _boc_rate_dates,
        "Canada CPI": _canada_cpi_dates,
        "Canada Employment": _canada_employment_dates,
        "BOJ Rate Decision": _boj_rate_dates,
        "Japan CPI": _japan_cpi_dates,
        "SARB Rate Decision": _sarb_rate_dates,
        "TCMB Rate Decision": _tcmb_rate_dates,
        "South Africa CPI": _sa_cpi_dates,
    }

    # Filter by group if specified
    if groups:
        wanted = set()
        for g in groups:
            wanted.update(EVENT_GROUPS.get(g, []))
        event_fns = {k: v for k, v in all_event_fns.items() if k in wanted}
    else:
        event_fns = all_event_fns

    events: list[dict] = []
    for fn in event_fns.values():
        events.extend(fn())

    JST = ZoneInfo("Asia/Tokyo")

    for e in events:
        tz = e.get("tz", "ET")
        local_dt = datetime.strptime(f"{e['date']} {e['time']}", "%Y-%m-%d %H:%M")
        if tz == "UTC":
            utc_dt = local_dt.replace(tzinfo=UTC)
        elif tz == "JST":
            utc_dt = local_dt.replace(tzinfo=JST).astimezone(UTC)
        else:
            # Eastern Time
            utc_dt = local_dt.replace(tzinfo=ET).astimezone(UTC)
        e["utc_dt"] = utc_dt.replace(tzinfo=None)
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

    Only downloads events where this pair is in the event's pair mapping.

    Returns the number of events successfully downloaded.
    """
    csv_path = output_path(pair, timeframe)
    existing = load_existing_events(csv_path) if skip_existing else set()

    # Filter events to only those relevant to this pair
    relevant = [e for e in events if pair in EVENT_PAIRS.get(e["name"], PAIRS)]

    frames: list[pd.DataFrame] = []
    downloaded = 0

    for i, event in enumerate(relevant, 1):
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
            f"({i}/{len(relevant)})"
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
        description="Download historical forex data from Dukascopy around economic events."
    )
    parser.add_argument(
        "--pair",
        choices=PAIRS,
        help="Download a single pair (default: all)",
    )
    parser.add_argument(
        "--group",
        help=(
            "Comma-separated event groups to download. "
            f"Valid: {', '.join(EVENT_GROUPS.keys())}. "
            "Default: all groups."
        ),
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
    groups = args.group.split(",") if args.group else None
    events = get_all_events(groups=groups)

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
