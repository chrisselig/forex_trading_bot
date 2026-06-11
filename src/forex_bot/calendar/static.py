"""Static calendar for events not covered by Forex Factory (SARB, TCMB, SA CPI, BOJ)."""
from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from loguru import logger

from forex_bot.config import PROJECT_ROOT
from forex_bot.models.events import EconomicEvent, EventImpact

STATIC_EVENTS_PATH = PROJECT_ROOT / "config" / "static_events.yaml"
DOWNLOAD_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "download_dukascopy.py"

# Events that require static scheduling (not on Forex Factory)
STATIC_EVENT_NAMES = {
    "SARB Rate Decision": "SARB Interest Rate Decision",
    "South Africa CPI": "CPI y/y",
    "TCMB Rate Decision": "TCMB Interest Rate Decision",
    "BOJ Rate Decision": "BOJ Policy Rate",
}

# How far ahead to check for missing events
VALIDATION_HORIZON_DAYS = 30


def load_static_events() -> list[EconomicEvent]:
    """Load upcoming events from the static calendar YAML."""
    if not STATIC_EVENTS_PATH.exists():
        logger.debug("No static_events.yaml found, skipping")
        return []

    with open(STATIC_EVENTS_PATH) as f:
        data = yaml.safe_load(f) or {}

    events: list[EconomicEvent] = []
    for entry in data.get("static_events", []):
        title = entry.get("title", "")
        country = entry.get("country", "")
        impact_str = entry.get("impact", "high")
        impact = EventImpact.HIGH if impact_str == "high" else EventImpact.MEDIUM

        for date_str in entry.get("dates", []):
            try:
                scheduled_utc = datetime.fromisoformat(date_str)
            except ValueError:
                logger.warning(f"Skipping unparseable static event date: {date_str}")
                continue

            events.append(
                EconomicEvent(
                    title=title,
                    country=country,
                    impact=impact,
                    scheduled_at=scheduled_utc,
                )
            )

    logger.info(f"Loaded {len(events)} static events from {STATIC_EVENTS_PATH.name}")
    return events


def _load_master_dates() -> dict[str, list[str]]:
    """Load the master event date list from the download script.

    Returns a dict of event_name -> list of "YYYY-MM-DD" date strings.
    """
    if not DOWNLOAD_SCRIPT_PATH.exists():
        return {}

    try:
        spec = importlib.util.spec_from_file_location("download_dukascopy", DOWNLOAD_SCRIPT_PATH)
        mod = importlib.util.module_from_spec(spec)
        # Don't pollute sys.modules or run CLI code
        sys.modules["download_dukascopy"] = mod
        spec.loader.exec_module(mod)

        events = mod.get_all_events()
        result: dict[str, list[str]] = {}
        for e in events:
            name = e["name"]
            if name in STATIC_EVENT_NAMES:
                result.setdefault(name, []).append(e["date"])
        return result
    except Exception as exc:
        logger.warning(f"Could not load master dates from download script: {exc}")
        return {}
    finally:
        sys.modules.pop("download_dukascopy", None)


def validate_static_calendar() -> list[str]:
    """Check for upcoming events in the master list that are missing from static_events.yaml.

    Returns a list of warning strings for each missing event. Empty list = all good.
    """
    master = _load_master_dates()
    if not master:
        logger.debug("No master dates loaded, skipping static calendar validation")
        return []

    # Load static calendar dates as a set of (title, date_str) for fast lookup
    static_events = load_static_events()
    static_dates: set[tuple[str, str]] = set()
    for ev in static_events:
        date_str = ev.scheduled_at.strftime("%Y-%m-%d")
        static_dates.add((ev.title, date_str))

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=VALIDATION_HORIZON_DAYS)
    warnings: list[str] = []

    for master_name, dates in master.items():
        static_title = STATIC_EVENT_NAMES[master_name]
        for date_str in dates:
            event_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if event_date < now or event_date > horizon:
                continue
            if (static_title, date_str) not in static_dates:
                warnings.append(
                    f"MISSING from static_events.yaml: {master_name} on {date_str} "
                    f"(expected title: '{static_title}')"
                )

    if warnings:
        logger.warning(f"Static calendar validation: {len(warnings)} missing event(s)!")
        for w in warnings:
            logger.warning(f"  {w}")
    else:
        logger.info("Static calendar validation passed: all upcoming events present")

    return warnings
