"""Static calendar for events not covered by Forex Factory (SARB, TCMB, SA CPI, BOJ)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml
from loguru import logger

from forex_bot.config import PROJECT_ROOT
from forex_bot.models.events import EconomicEvent, EventImpact

STATIC_EVENTS_PATH = PROJECT_ROOT / "config" / "static_events.yaml"


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
