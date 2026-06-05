#!/usr/bin/env python3
"""Populate the database with historical events from Forex Factory and FRED."""

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from forex_bot.calendar.scraper import ForexFactoryScraper
from forex_bot.calendar.parser import EventParser
from forex_bot.calendar.store import EventStore
from forex_bot.data.database import init_db


async def main():
    await init_db()

    scraper = ForexFactoryScraper()
    parser = EventParser()
    store = EventStore()

    # Fetch current and next week
    now = datetime.now(UTC)
    total_saved = 0

    for week_offset in range(0, 2):
        date = now + timedelta(weeks=week_offset)
        print(f"\nFetching week of {date.strftime('%Y-%m-%d')}...")

        try:
            events = await scraper.fetch_week(date)
            filtered = parser.filter_events(events)
            saved = await store.save_events(filtered)
            total_saved += saved
            print(f"  Found {len(events)} total, {len(filtered)} high-impact USD, saved {saved} new")
        except Exception as e:
            print(f"  Error: {e}")

    print(f"\nDone! Saved {total_saved} new events to database.")


if __name__ == "__main__":
    asyncio.run(main())
