"""Export a tradeable events calendar as JSON for the web dashboard."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger

from forex_bot.calendar.parser import EventParser
from forex_bot.calendar.scraper import ForexFactoryScraper
from forex_bot.calendar.static import load_static_events
from forex_bot.config import PROJECT_ROOT, get_settings
from forex_bot.models.events import EconomicEvent

ET = ZoneInfo("America/New_York")

# Default output path for the web dashboard to consume
DEFAULT_CALENDAR_PATH = Path.home() / "00_data_projects" / "trading_dashboard" / "data" / "calendar.json"


async def build_calendar(days: int = 30) -> list[dict]:
    """Build a list of upcoming tradeable events with enriched metadata.

    Combines Forex Factory (US/major events) with the static calendar
    (SARB, TCMB, SA CPI, BOJ). Each event is enriched with:
    - target pairs
    - straddle parameters (per-pair, with event overrides)
    - event source (forex_factory or static)
    - display times in both UTC and Eastern

    Returns a list of dicts ready for JSON serialisation.
    """
    settings = get_settings()
    parser = EventParser()
    now = datetime.now(UTC).replace(tzinfo=None)
    cutoff = now + timedelta(days=days)

    # Fetch from both sources
    scraper = ForexFactoryScraper()
    ff_events = await scraper.fetch_week()
    ff_filtered = parser.filter_events(ff_events)

    static_events = load_static_events()
    static_filtered = parser.filter_events(static_events)

    # Tag source before merging
    ff_titles_times: set[tuple[str, datetime]] = set()
    for ev in ff_filtered:
        ff_titles_times.add((ev.title, ev.scheduled_at))

    all_events: list[tuple[EconomicEvent, str]] = []
    for ev in ff_filtered:
        all_events.append((ev, "forex_factory"))
    for ev in static_filtered:
        # Avoid duplicates if FF also has this event
        if (ev.title, ev.scheduled_at) not in ff_titles_times:
            all_events.append((ev, "static"))

    # Filter to the requested window and sort
    all_events = [
        (ev, src) for ev, src in all_events
        if now <= ev.scheduled_at <= cutoff
    ]
    all_events.sort(key=lambda x: x[0].scheduled_at)

    # Build output
    calendar: list[dict] = []
    for event, source in all_events:
        pairs = _resolve_pairs(event, settings)
        if not pairs:
            continue

        scheduled_utc = event.scheduled_at
        scheduled_et = scheduled_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(ET)

        entry = {
            "event": event.title,
            "country": event.country,
            "datetime_utc": scheduled_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "datetime_et": scheduled_et.strftime("%Y-%m-%d %H:%M ET"),
            "source": source,
            "forecast": event.forecast,
            "previous": event.previous,
            "pairs": [],
        }

        for pair in pairs:
            dist, tp, sl = settings.strategy.get_straddle_params(pair, event.title)
            entry["pairs"].append({
                "instrument": pair,
                "straddle_distance_pips": dist,
                "straddle_tp_pips": tp,
                "straddle_sl_pips": sl,
            })

        calendar.append(entry)

    logger.info(f"Built calendar with {len(calendar)} events in next {days} days")
    return calendar


def _resolve_pairs(
    event: EconomicEvent, settings: object
) -> list[str]:
    """Resolve which pairs trade this event, intersected with configured instruments."""
    configured = set(settings.trading.instruments)
    if event.target_pairs:
        return [p for p in event.target_pairs if p in configured]
    return list(configured)


async def export_calendar_json(
    output_path: Path | None = DEFAULT_CALENDAR_PATH, days: int = 30
) -> str:
    """Build the calendar and write/return as JSON.

    Writes to output_path (defaults to data/calendar.json).
    Pass output_path=None to skip file writing.
    Always returns the JSON string.
    """
    calendar = await build_calendar(days=days)

    payload = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "days_ahead": days,
        "event_count": len(calendar),
        "events": calendar,
    }

    json_str = json.dumps(payload, indent=2)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json_str)
        logger.info(f"Calendar exported to {output_path}")

    return json_str
