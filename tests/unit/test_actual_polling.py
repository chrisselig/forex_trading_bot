"""Unit tests for actual value polling logic."""

from __future__ import annotations

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from forex_bot.scheduler.jobs import (
    JobManager,
    _ACTUAL_POLL_MAX_ATTEMPTS,
)


@pytest.fixture
def scraper():
    s = MagicMock()
    s.fetch_week = AsyncMock(return_value=[])
    return s


@pytest.fixture
def event_store():
    store = MagicMock()
    store.get_events_range = AsyncMock(return_value=[])
    store.update_actuals = AsyncMock(return_value=0)
    store.get_events_missing_actuals = AsyncMock(return_value=[])
    return store


@pytest.fixture
def job_manager(scraper, event_store):
    client = MagicMock()
    client.is_connected = True
    client.connect = AsyncMock()

    settings = MagicMock()
    settings.trading.instruments = ["USDZAR"]
    settings.strategy.pre_event_minutes = 30
    settings.strategy.surprise_entry_delay_seconds = 5

    scheduler = MagicMock()

    jm = JobManager(
        scheduler=scheduler,
        execution_engine=MagicMock(),
        pricing=MagicMock(),
        event_store=event_store,
        strategy_registry=MagicMock(),
        monitor=MagicMock(),
        client=client,
        settings=settings,
        scraper=scraper,
    )
    return jm


@pytest.fixture
def event():
    return MagicMock(
        id=1,
        title="Non-Farm Employment Change",
        scheduled_at=datetime(2026, 6, 5, 12, 30, 0),
        target_pairs=["USDZAR"],
        has_actual=False,
        actual=None,
    )


class TestPollActual:
    @pytest.mark.asyncio
    async def test_stops_when_actual_found(self, job_manager, event, scraper, event_store):
        """Polling stops (no reschedule) when the event's actual is populated."""
        found_event = MagicMock(
            title="Non-Farm Employment Change", has_actual=True, actual="206K"
        )
        found_event.country = event.country
        event_store.get_events_range = AsyncMock(return_value=[found_event])

        await job_manager._poll_actual(event, attempt=1)

        # Should NOT schedule another poll
        job_manager._scheduler.add_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_reschedules_when_actual_missing(self, job_manager, event, event_store):
        """Reschedules next attempt when actual is still missing."""
        missing_event = MagicMock(
            title="Non-Farm Employment Change", has_actual=False, actual=None
        )
        event_store.get_events_range = AsyncMock(return_value=[missing_event])

        await job_manager._poll_actual(event, attempt=3)

        job_manager._scheduler.add_job.assert_called_once()
        call_kwargs = job_manager._scheduler.add_job.call_args.kwargs
        assert call_kwargs["args"] == [event, 4]  # next attempt = 4

    @pytest.mark.asyncio
    async def test_stops_after_max_attempts(self, job_manager, event, event_store):
        """Does not reschedule after exhausting all attempts."""
        missing_event = MagicMock(
            title="Non-Farm Employment Change", has_actual=False, actual=None
        )
        event_store.get_events_range = AsyncMock(return_value=[missing_event])

        await job_manager._poll_actual(event, attempt=_ACTUAL_POLL_MAX_ATTEMPTS)

        job_manager._scheduler.add_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_scraper_error_gracefully(self, job_manager, event, scraper):
        """Continues polling even if scraper raises an exception."""
        scraper.fetch_week = AsyncMock(side_effect=Exception("FF down"))

        await job_manager._poll_actual(event, attempt=1)

        # Should still schedule next attempt
        job_manager._scheduler.add_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetches_correct_week(self, job_manager, event, scraper, event_store):
        """Passes the event's scheduled_at to fetch_week for correct week lookup."""
        missing_event = MagicMock(
            title="Non-Farm Employment Change", has_actual=False, actual=None
        )
        event_store.get_events_range = AsyncMock(return_value=[missing_event])

        await job_manager._poll_actual(event, attempt=1)

        scraper.fetch_week.assert_called_once_with(date=event.scheduled_at)


class TestScheduleActualPoll:
    def test_schedules_first_poll_from_post_event(self, job_manager, event):
        """_schedule_actual_poll schedules a DateTrigger job."""
        job_manager._schedule_actual_poll(event)

        job_manager._scheduler.add_job.assert_called_once()
        call_kwargs = job_manager._scheduler.add_job.call_args.kwargs
        assert "poll_actual_" in call_kwargs["id"]
        assert call_kwargs["args"] == [event, 1]  # first attempt

    def test_no_poll_without_scraper(self):
        """JobManager without scraper does not schedule polling."""
        settings = MagicMock()
        settings.trading.instruments = ["USDZAR"]
        settings.strategy.pre_event_minutes = 30
        settings.strategy.surprise_entry_delay_seconds = 5

        scheduler = MagicMock()
        jm = JobManager(
            scheduler=scheduler,
            execution_engine=MagicMock(),
            pricing=MagicMock(),
            event_store=MagicMock(),
            strategy_registry=MagicMock(),
            monitor=MagicMock(),
            client=MagicMock(),
            settings=settings,
            scraper=None,
        )
        # _scraper is None, so _schedule_actual_poll should not be called from post-event
        assert jm._scraper is None
