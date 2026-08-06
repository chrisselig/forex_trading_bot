"""Unit tests for InterestJournal: upsert idempotency and period aggregation."""

from __future__ import annotations

from datetime import datetime

import pytest

from forex_bot.data import database as db_module
from forex_bot.data.database import get_session, init_db
from forex_bot.data.interest_journal import InterestJournal
from forex_bot.data.schemas import InterestAccrualRecord
from forex_bot.models.interest import InterestAccrualRow


@pytest.fixture
async def journal_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_interest.db")
    db_module._engine = None
    db_module._session_factory = None
    await init_db()
    yield
    if db_module._engine is not None:
        await db_module._engine.dispose()
    db_module._engine = None
    db_module._session_factory = None


def _row(currency, day, amount):
    dt = datetime(2026, 7, day)
    return InterestAccrualRow(currency=currency, from_date=dt, to_date=dt, amount_cad=amount)


@pytest.mark.asyncio
async def test_upsert_inserts_new_rows(journal_db):
    journal = InterestJournal()
    written = await journal.upsert_rows([_row("USD", 1, 1.0), _row("TRY", 1, 5.0)])
    assert written == 2

    async with get_session() as session:
        from sqlalchemy import select

        result = await session.execute(select(InterestAccrualRecord))
        records = result.scalars().all()
    assert len(records) == 2


@pytest.mark.asyncio
async def test_upsert_is_idempotent_for_same_day(journal_db):
    journal = InterestJournal()
    await journal.upsert_rows([_row("USD", 1, 1.0)])
    await journal.upsert_rows([_row("USD", 1, 1.0)])  # re-fetch of same day

    async with get_session() as session:
        from sqlalchemy import select

        result = await session.execute(select(InterestAccrualRecord))
        records = result.scalars().all()
    assert len(records) == 1


@pytest.mark.asyncio
async def test_upsert_updates_amount_on_conflict(journal_db):
    journal = InterestJournal()
    await journal.upsert_rows([_row("USD", 1, 1.0)])
    await journal.upsert_rows([_row("USD", 1, 1.5)])  # revised accrual for same day

    totals = await journal.sum_by_currency()
    assert totals["USD"] == pytest.approx(1.5)


@pytest.mark.asyncio
async def test_sum_by_currency_since_filters_by_from_date(journal_db):
    journal = InterestJournal()
    await journal.upsert_rows(
        [
            InterestAccrualRow(
                currency="USD",
                from_date=datetime(2025, 12, 31),
                to_date=datetime(2025, 12, 31),
                amount_cad=10.0,
            ),
            _row("USD", 1, 2.0),
        ]
    )

    all_time = await journal.sum_by_currency()
    this_year = await journal.sum_by_currency(since=datetime(2026, 1, 1))

    assert all_time["USD"] == pytest.approx(12.0)
    assert this_year["USD"] == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_get_period_summary_buckets_correctly(journal_db):
    journal = InterestJournal()
    await journal.upsert_rows(
        [
            InterestAccrualRow(
                currency="TRY",
                from_date=datetime(2025, 1, 1),
                to_date=datetime(2025, 1, 1),
                amount_cad=100.0,
            ),
            InterestAccrualRow(
                currency="TRY",
                from_date=datetime(2026, 6, 1),
                to_date=datetime(2026, 6, 1),
                amount_cad=10.0,
            ),
            _row("TRY", 15, 3.0),  # 2026-07-15
        ]
    )

    summary = await journal.get_period_summary(now=datetime(2026, 7, 20))

    assert summary["all_time"]["TRY"] == pytest.approx(113.0)
    assert summary["this_year"]["TRY"] == pytest.approx(13.0)
    assert summary["this_month"]["TRY"] == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_earliest_date_returns_none_when_empty(journal_db):
    journal = InterestJournal()
    assert await journal.earliest_date() is None


@pytest.mark.asyncio
async def test_earliest_date_returns_min_from_date(journal_db):
    journal = InterestJournal()
    await journal.upsert_rows([_row("USD", 15, 1.0), _row("USD", 1, 2.0)])
    earliest = await journal.earliest_date()
    assert earliest == datetime(2026, 7, 1)
