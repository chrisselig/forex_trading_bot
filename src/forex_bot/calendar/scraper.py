from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from forex_bot.models.events import EconomicEvent, EventImpact

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

# Forex Factory calendar URL
FF_BASE_URL = "https://www.forexfactory.com/calendar"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class ForexFactoryScraper:
    """Scrapes economic calendar from Forex Factory."""

    def __init__(self, rate_limit_seconds: float = 2.0):
        self._rate_limit = rate_limit_seconds
        self._last_request: float = 0

    async def _throttle(self) -> None:
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request
        if elapsed < self._rate_limit:
            await asyncio.sleep(self._rate_limit - elapsed)
        self._last_request = asyncio.get_event_loop().time()

    async def fetch_week(self, date: datetime | None = None) -> list[EconomicEvent]:
        """Fetch events for the week containing the given date."""
        if date is None:
            date = datetime.now(UTC)

        # FF uses format like "jan1.2024" for the week URL
        date_str = date.strftime("%b").lower() + date.strftime("%-d.%Y")
        url = f"{FF_BASE_URL}?week={date_str}"

        await self._throttle()

        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            logger.info(f"Fetching Forex Factory calendar: {url}")
            response = await client.get(url)
            response.raise_for_status()

        return self._parse_html(response.text)

    def _parse_html(self, html: str) -> list[EconomicEvent]:
        """Parse FF calendar HTML into EconomicEvent objects."""
        soup = BeautifulSoup(html, "lxml")
        events: list[EconomicEvent] = []
        current_date: datetime | None = None
        current_time: str | None = None

        table = soup.find("table", class_="calendar__table")
        if not table:
            logger.warning("Could not find calendar table in FF HTML")
            return events

        rows = table.find_all("tr", class_="calendar__row")

        for row in rows:
            # Check for date header
            date_cell = row.find("td", class_="calendar__date")
            if date_cell:
                date_text = date_cell.get_text(strip=True)
                if date_text:
                    try:
                        parsed = datetime.strptime(date_text, "%a%b %d")
                        current_date = parsed.replace(year=datetime.now().year)
                    except ValueError:
                        pass

            if current_date is None:
                continue

            # Time cell (only shown for first event in a time group)
            time_cell = row.find("td", class_="calendar__time")
            if time_cell:
                time_text = time_cell.get_text(strip=True)
                if time_text and time_text not in ("", "Tentative", "All Day"):
                    current_time = time_text

            if current_time is None:
                continue

            # Currency
            currency_cell = row.find("td", class_="calendar__currency")
            currency = currency_cell.get_text(strip=True) if currency_cell else ""

            # Impact
            impact_cell = row.find("td", class_="calendar__impact")
            impact = EventImpact.LOW
            if impact_cell:
                impact_icon = impact_cell.find("span")
                if impact_icon:
                    classes = impact_icon.get("class", [])
                    class_str = " ".join(classes) if isinstance(classes, list) else str(classes)
                    if "high" in class_str or "red" in class_str:
                        impact = EventImpact.HIGH
                    elif "medium" in class_str or "ora" in class_str:
                        impact = EventImpact.MEDIUM

            # Event title
            event_cell = row.find("td", class_="calendar__event")
            title = ""
            if event_cell:
                title_span = event_cell.find("span", class_="calendar__event-title")
                title = title_span.get_text(strip=True) if title_span else event_cell.get_text(strip=True)

            if not title:
                continue

            # Actual, forecast, previous
            actual_cell = row.find("td", class_="calendar__actual")
            forecast_cell = row.find("td", class_="calendar__forecast")
            previous_cell = row.find("td", class_="calendar__previous")

            actual = actual_cell.get_text(strip=True) if actual_cell else None
            forecast = forecast_cell.get_text(strip=True) if forecast_cell else None
            previous = previous_cell.get_text(strip=True) if previous_cell else None

            # Parse time and combine with date (ET timezone)
            try:
                scheduled_et = self._parse_event_time(current_date, current_time)
                scheduled_utc = scheduled_et.astimezone(UTC).replace(tzinfo=None)
            except ValueError:
                continue

            events.append(
                EconomicEvent(
                    title=title,
                    country=currency,
                    impact=impact,
                    scheduled_at=scheduled_utc,
                    actual=actual if actual else None,
                    forecast=forecast if forecast else None,
                    previous=previous if previous else None,
                )
            )

        logger.info(f"Parsed {len(events)} events from Forex Factory")
        return events

    @staticmethod
    def _parse_event_time(date: datetime, time_str: str) -> datetime:
        """Parse FF time string (e.g., '8:30am') and combine with date in ET."""
        time_str = time_str.strip().lower()
        try:
            t = datetime.strptime(time_str, "%I:%M%p")
        except ValueError:
            t = datetime.strptime(time_str, "%I:%M %p")
        return date.replace(hour=t.hour, minute=t.minute, second=0, tzinfo=ET)
