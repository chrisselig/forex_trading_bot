from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
from loguru import logger

from forex_bot.models.events import EconomicEvent, EventImpact

ET = ZoneInfo("America/New_York")

# Primary: JSON API mirroring Forex Factory data (no Cloudflare)
FF_JSON_THIS_WEEK = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FF_JSON_NEXT_WEEK = "https://nfs.faireconomy.media/ff_calendar_nextweek.json"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

IMPACT_MAP = {
    "high": EventImpact.HIGH,
    "medium": EventImpact.MEDIUM,
    "low": EventImpact.LOW,
    "holiday": EventImpact.LOW,
}


class ForexFactoryScraper:
    """Fetches economic calendar data from the Forex Factory JSON API."""

    def __init__(self, rate_limit_seconds: float = 2.0):
        self._rate_limit = rate_limit_seconds
        self._last_request: float = 0

    async def _throttle(self) -> None:
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request
        if elapsed < self._rate_limit:
            await asyncio.sleep(self._rate_limit - elapsed)
        self._last_request = asyncio.get_event_loop().time()

    async def _fetch_json(self, url: str) -> list[dict]:
        """Fetch and return JSON event list from the given URL."""
        await self._throttle()
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            logger.info(f"Fetching calendar JSON: {url}")
            response = await client.get(url)
            response.raise_for_status()
            return response.json()

    async def fetch_week(self, date: datetime | None = None) -> list[EconomicEvent]:
        """Fetch events for the current week and next week (2-week lookahead)."""
        raw_events = await self._fetch_json(FF_JSON_THIS_WEEK)
        events = self._parse_json(raw_events)

        # Always fetch next week for maximum event visibility
        try:
            next_raw = await self._fetch_json(FF_JSON_NEXT_WEEK)
            events.extend(self._parse_json(next_raw))
        except httpx.HTTPError as e:
            logger.warning(f"Failed to fetch next week calendar: {e}")

        logger.info(f"Fetched {len(events)} events from calendar API")
        return events

    def _parse_json(self, raw_events: list[dict]) -> list[EconomicEvent]:
        """Convert raw JSON events to EconomicEvent models."""
        events: list[EconomicEvent] = []

        for item in raw_events:
            title = item.get("title", "").strip()
            if not title:
                continue

            country = item.get("country", "").strip()
            impact_str = item.get("impact", "low").strip().lower()
            impact = IMPACT_MAP.get(impact_str, EventImpact.LOW)

            # Parse the ISO 8601 date string (ET timezone from API)
            date_str = item.get("date", "")
            if not date_str:
                continue

            try:
                scheduled_et = datetime.fromisoformat(date_str)
                scheduled_utc = scheduled_et.astimezone(UTC).replace(tzinfo=None)
            except ValueError:
                logger.debug(f"Skipping event with unparseable date: {date_str}")
                continue

            actual = item.get("actual", "").strip() or None
            forecast = item.get("forecast", "").strip() or None
            previous = item.get("previous", "").strip() or None

            events.append(
                EconomicEvent(
                    title=title,
                    country=country,
                    impact=impact,
                    scheduled_at=scheduled_utc,
                    actual=actual,
                    forecast=forecast,
                    previous=previous,
                )
            )

        return events
