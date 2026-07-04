from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from forex_bot.calendar.store import EventStore
from forex_bot.data import database as db_module
from forex_bot.data.database import get_session, init_db
from forex_bot.data.schemas import EventRecord
from forex_bot.models.events import EconomicEvent, EventImpact


@pytest.fixture
async def store_db(tmp_path, monkeypatch):
    """Point the database module at a fresh, isolated SQLite file per test."""
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_events.db")
    db_module._engine = None
    db_module._session_factory = None
    await init_db()
    yield
    if db_module._engine is not None:
        await db_module._engine.dispose()
    db_module._engine = None
    db_module._session_factory = None


async def _fetch_record(title: str, country: str) -> EventRecord | None:
    async with get_session() as session:
        result = await session.execute(
            select(EventRecord).where(
                EventRecord.title == title,
                EventRecord.country == country,
            )
        )
        return result.scalars().first()


def _make_event(**overrides) -> EconomicEvent:
    defaults = dict(
        title="BOJ Policy Rate",
        country="JPY",
        impact=EventImpact.HIGH,
        scheduled_at=datetime(2026, 6, 16, 3, 0),
    )
    defaults.update(overrides)
    return EconomicEvent(**defaults)


class TestSourceAwareSaveEvents:
    """FF is authoritative whenever both feeds cover the same event — this
    is the core fix for the FF/static ping-pong bug (BOJ Policy Rate was
    flip-flopping between FF's 03:19 and static's 03:00 every refresh)."""

    async def test_ff_save_then_static_save_keeps_ff_time(self, store_db):
        store = EventStore()

        ff_event = _make_event(scheduled_at=datetime(2026, 6, 16, 3, 19))
        await store.save_events([ff_event], source="ff")

        static_event = _make_event(scheduled_at=datetime(2026, 6, 16, 3, 0))
        await store.save_events([static_event], source="static")

        record = await _fetch_record("BOJ Policy Rate", "JPY")
        assert record is not None
        assert record.scheduled_at == datetime(2026, 6, 16, 3, 19)
        assert record.source == "ff"

    async def test_static_insert_creates_row_with_static_source(self, store_db):
        store = EventStore()

        static_event = _make_event(
            title="SARB Interest Rate Decision", country="ZAR"
        )
        await store.save_events([static_event], source="static")

        record = await _fetch_record("SARB Interest Rate Decision", "ZAR")
        assert record is not None
        assert record.source == "static"

    async def test_static_save_updates_time_of_existing_static_row(self, store_db):
        store = EventStore()

        original = _make_event(
            title="TCMB Interest Rate Decision",
            country="TRY",
            scheduled_at=datetime(2026, 7, 24, 11, 0),
        )
        await store.save_events([original], source="static")

        corrected = _make_event(
            title="TCMB Interest Rate Decision",
            country="TRY",
            scheduled_at=datetime(2026, 7, 23, 11, 0),
        )
        await store.save_events([corrected], source="static")

        record = await _fetch_record("TCMB Interest Rate Decision", "TRY")
        assert record is not None
        assert record.scheduled_at == datetime(2026, 7, 23, 11, 0)
        assert record.source == "static"

    async def test_ff_save_takes_ownership_and_blocks_later_static_update(
        self, store_db
    ):
        store = EventStore()

        static_event = _make_event(scheduled_at=datetime(2026, 6, 16, 3, 0))
        await store.save_events([static_event], source="static")

        ff_event = _make_event(scheduled_at=datetime(2026, 6, 16, 3, 19))
        await store.save_events([ff_event], source="ff")

        record = await _fetch_record("BOJ Policy Rate", "JPY")
        assert record is not None
        assert record.scheduled_at == datetime(2026, 6, 16, 3, 19)
        assert record.source == "ff"

        # A subsequent static save must no longer be able to move this
        # FF-owned record's time back.
        stale_static = _make_event(scheduled_at=datetime(2026, 6, 16, 3, 0))
        await store.save_events([stale_static], source="static")

        record = await _fetch_record("BOJ Policy Rate", "JPY")
        assert record is not None
        assert record.scheduled_at == datetime(2026, 6, 16, 3, 19)
        assert record.source == "ff"
