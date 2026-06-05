from __future__ import annotations

from datetime import UTC, datetime, timedelta
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forex_bot.data.database import get_session
from forex_bot.data.schemas import EventRecord
from forex_bot.models.events import EconomicEvent, EventImpact


class EventStore:
    """Persists and queries economic events in SQLite."""

    async def save_events(self, events: list[EconomicEvent]) -> int:
        """Save events to the database, deduplicating by title + scheduled_at."""
        saved = 0
        async with get_session() as session:
            for event in events:
                existing = await session.execute(
                    select(EventRecord).where(
                        EventRecord.title == event.title,
                        EventRecord.scheduled_at == event.scheduled_at,
                    )
                )
                if existing.scalar_one_or_none() is not None:
                    continue

                record = EventRecord(
                    title=event.title,
                    country=event.country,
                    impact=event.impact.value,
                    scheduled_at=event.scheduled_at,
                    actual=event.actual,
                    forecast=event.forecast,
                    previous=event.previous,
                    fred_series=event.fred_series,
                )
                session.add(record)
                saved += 1
            await session.commit()

        logger.info(f"Saved {saved} new events ({len(events) - saved} duplicates skipped)")
        return saved

    async def update_actuals(self, events: list[EconomicEvent]) -> int:
        """Update actual values for events that now have them."""
        updated = 0
        async with get_session() as session:
            for event in events:
                if not event.has_actual:
                    continue
                result = await session.execute(
                    select(EventRecord).where(
                        EventRecord.title == event.title,
                        EventRecord.scheduled_at == event.scheduled_at,
                    )
                )
                record = result.scalar_one_or_none()
                if record and not record.actual:
                    record.actual = event.actual
                    updated += 1
            await session.commit()

        if updated:
            logger.info(f"Updated actuals for {updated} events")
        return updated

    async def get_upcoming(self, within_hours: int = 24) -> list[EconomicEvent]:
        """Get events scheduled within the next N hours."""
        now = datetime.now(UTC).replace(tzinfo=None)
        cutoff = now + timedelta(hours=within_hours)

        async with get_session() as session:
            result = await session.execute(
                select(EventRecord)
                .where(EventRecord.scheduled_at >= now, EventRecord.scheduled_at <= cutoff)
                .order_by(EventRecord.scheduled_at)
            )
            records = result.scalars().all()

        return [self._to_model(r) for r in records]

    async def get_events_range(self, start: datetime, end: datetime) -> list[EconomicEvent]:
        """Get events within a date range."""
        async with get_session() as session:
            result = await session.execute(
                select(EventRecord)
                .where(EventRecord.scheduled_at >= start, EventRecord.scheduled_at <= end)
                .order_by(EventRecord.scheduled_at)
            )
            records = result.scalars().all()

        return [self._to_model(r) for r in records]

    @staticmethod
    def _to_model(record: EventRecord) -> EconomicEvent:
        return EconomicEvent(
            id=record.id,
            title=record.title,
            country=record.country,
            impact=EventImpact(record.impact),
            scheduled_at=record.scheduled_at,
            actual=record.actual,
            forecast=record.forecast,
            previous=record.previous,
            fred_series=record.fred_series or "",
        )
