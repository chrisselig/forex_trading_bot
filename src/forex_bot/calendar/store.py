from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import select

from forex_bot.data.database import get_session
from forex_bot.data.schemas import EventRecord
from forex_bot.models.events import EconomicEvent, EventImpact

if TYPE_CHECKING:
    from forex_bot.data.turso_sync import TursoSyncer


class EventStore:
    """Persists and queries economic events in SQLite."""

    def __init__(self, turso: TursoSyncer | None = None):
        self._turso = turso

    async def save_events(self, events: list[EconomicEvent]) -> int:
        """Save events to the database, deduplicating by title + country + date.

        Country is part of the identity: generic titles like "CPI y/y" exist
        for multiple countries in the same window, and matching on title
        alone overwrote one country's event with another's schedule.

        If a matching event exists on the same day (±1 day window) but at a
        different time, update its scheduled_at (time-change detection).
        """
        saved = 0
        updated = 0
        async with get_session() as session:
            for event in events:
                # Exact match — already stored, skip
                exact = await session.execute(
                    select(EventRecord).where(
                        EventRecord.title == event.title,
                        EventRecord.country == event.country,
                        EventRecord.scheduled_at == event.scheduled_at,
                    )
                )
                if exact.scalars().first() is not None:
                    continue

                # Same-day match — check if FF rescheduled the event
                day_start = event.scheduled_at.replace(
                    hour=0, minute=0, second=0, microsecond=0,
                ) - timedelta(days=1)
                day_end = day_start + timedelta(days=3)
                same_day = await session.execute(
                    select(EventRecord).where(
                        EventRecord.title == event.title,
                        EventRecord.country == event.country,
                        EventRecord.scheduled_at >= day_start,
                        EventRecord.scheduled_at <= day_end,
                    )
                )
                # first() not scalar_one_or_none(): two same-title rows in the
                # window must not abort the whole calendar refresh
                existing_record = same_day.scalars().first()

                if existing_record is not None:
                    # Time changed — update the record
                    old_time = existing_record.scheduled_at
                    existing_record.scheduled_at = event.scheduled_at
                    if event.forecast:
                        existing_record.forecast = event.forecast
                    if event.previous:
                        existing_record.previous = event.previous
                    logger.warning(
                        f"Event time changed: {event.title} "
                        f"{old_time} → {event.scheduled_at}"
                    )
                    if self._turso:
                        await self._turso.push_event(
                            event_id=existing_record.id,
                            title=existing_record.title,
                            country=existing_record.country,
                            impact=existing_record.impact,
                            scheduled_at=existing_record.scheduled_at,
                            actual=existing_record.actual,
                            forecast=existing_record.forecast,
                            previous=existing_record.previous,
                            fred_series=existing_record.fred_series,
                            created_at=existing_record.created_at,
                        )
                    updated += 1
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
                await session.flush()  # Assign record.id before Turso push
                if self._turso:
                    await self._turso.push_event(
                        event_id=record.id,
                        title=record.title,
                        country=record.country,
                        impact=record.impact,
                        scheduled_at=record.scheduled_at,
                        actual=record.actual,
                        forecast=record.forecast,
                        previous=record.previous,
                        fred_series=record.fred_series,
                        created_at=record.created_at,
                    )
                saved += 1
            await session.commit()

        logger.info(
            f"Saved {saved} new events, {updated} time-updated "
            f"({len(events) - saved - updated} duplicates skipped)"
        )
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
                        EventRecord.country == event.country,
                        EventRecord.scheduled_at == event.scheduled_at,
                    )
                )
                record = result.scalars().first()
                if record and not record.actual:
                    record.actual = event.actual
                    if self._turso:
                        await self._turso.push_event_actual(
                            event_id=record.id,
                            actual=event.actual,
                        )
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

    async def get_events_missing_actuals(self, since_hours: int = 168) -> list[EconomicEvent]:
        """Return past events where actual is NULL (default: last 7 days)."""
        now = datetime.now(UTC).replace(tzinfo=None)
        cutoff = now - timedelta(hours=since_hours)

        async with get_session() as session:
            result = await session.execute(
                select(EventRecord)
                .where(
                    EventRecord.scheduled_at >= cutoff,
                    EventRecord.scheduled_at <= now,
                    EventRecord.actual.is_(None),
                )
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
