from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from loguru import logger

from forex_bot.config import get_settings
from forex_bot.models.events import EconomicEvent, EventImpact

ET = ZoneInfo("America/New_York")
UTC = timezone.utc


class EventParser:
    """Filters and enriches economic events based on configuration."""

    def __init__(self):
        self._settings = get_settings()
        self._targets = self._settings.events.target_events
        self._filters = self._settings.events.filters

    def filter_events(self, events: list[EconomicEvent]) -> list[EconomicEvent]:
        """Filter events to only those matching our target criteria."""
        filtered = []
        for event in events:
            if not self._matches_filters(event):
                continue
            target = self._match_target(event)
            if target:
                event.fred_series = target.fred_series
                event.target_pairs = target.pairs
                filtered.append(event)
        logger.info(f"Filtered {len(events)} events down to {len(filtered)} matching targets")
        return filtered

    def _matches_filters(self, event: EconomicEvent) -> bool:
        """Check if event matches base filters (country, impact)."""
        country_filter = self._filters.country
        if country_filter:
            allowed = [country_filter] if isinstance(country_filter, str) else country_filter
            if event.country not in allowed:
                return False
        if self._filters.min_impact == "high" and event.impact != EventImpact.HIGH:
            return False
        return True

    def _match_target(self, event: EconomicEvent) -> object | None:
        """Check if event title matches any configured target event."""
        title_lower = event.title.lower().strip()
        for target in self._targets:
            # Skip if target is country-specific and event is from a different country
            if target.country and target.country != event.country:
                continue
            # Check exact name match
            if target.name.lower() in title_lower:
                return target
            # Check aliases
            for alias in target.aliases:
                if alias.lower() in title_lower:
                    return target
        return None

    def get_upcoming_events(
        self,
        events: list[EconomicEvent],
        within_minutes: int = 60,
    ) -> list[EconomicEvent]:
        """Get events scheduled within the next N minutes."""
        now = datetime.now(UTC).replace(tzinfo=None)
        cutoff = now + timedelta(minutes=within_minutes)
        return [e for e in events if now <= e.scheduled_at <= cutoff]

    @staticmethod
    def to_eastern(dt: datetime) -> datetime:
        """Convert a naive UTC datetime to Eastern Time for display."""
        return dt.replace(tzinfo=UTC).astimezone(ET)
