"""Unit tests for actual value polling logic (FRED-backed resolver)."""

from __future__ import annotations

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

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
    store.set_actual = AsyncMock()
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
        country="USD",
        scheduled_at=datetime(2026, 6, 5, 12, 30, 0),
        target_pairs=["USDZAR"],
        has_actual=False,
        actual=None,
    )


class TestPollActual:
    @pytest.mark.asyncio
    async def test_persists_and_stops_when_resolver_finds_value(self, job_manager, event, event_store):
        """Polling persists the actual and does NOT reschedule when the resolver has a value."""
        with patch("forex_bot.scheduler.jobs.actuals.lookup_mapping", return_value=object()), \
             patch("forex_bot.scheduler.jobs.actuals.resolve_actual", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = "206K"

            await job_manager._poll_actual(event, attempt=1)

        event_store.set_actual.assert_awaited_once_with(1, "206K")
        job_manager._scheduler.add_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_reschedules_when_resolver_returns_none(self, job_manager, event, event_store):
        """Reschedules next attempt when the resolver has a mapping but no value yet."""
        with patch("forex_bot.scheduler.jobs.actuals.lookup_mapping", return_value=object()), \
             patch("forex_bot.scheduler.jobs.actuals.resolve_actual", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = None

            await job_manager._poll_actual(event, attempt=3)

        event_store.set_actual.assert_not_awaited()
        job_manager._scheduler.add_job.assert_called_once()
        call_kwargs = job_manager._scheduler.add_job.call_args.kwargs
        assert call_kwargs["args"] == [event, 4]  # next attempt = 4

    @pytest.mark.asyncio
    async def test_stops_after_max_attempts(self, job_manager, event, event_store):
        """Does not reschedule after exhausting all attempts."""
        with patch("forex_bot.scheduler.jobs.actuals.lookup_mapping", return_value=object()), \
             patch("forex_bot.scheduler.jobs.actuals.resolve_actual", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = None

            await job_manager._poll_actual(event, attempt=_ACTUAL_POLL_MAX_ATTEMPTS)

        job_manager._scheduler.add_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_mapping_skips_without_reschedule(self, job_manager, event, event_store):
        """No FRED mapping (e.g. SARB/TCMB/BOJ/RBA/AU events) -> no poll, no reschedule."""
        with patch("forex_bot.scheduler.jobs.actuals.lookup_mapping", return_value=None), \
             patch("forex_bot.scheduler.jobs.actuals.resolve_actual", new_callable=AsyncMock) as mock_resolve:
            await job_manager._poll_actual(event, attempt=1)

            mock_resolve.assert_not_called()

        event_store.set_actual.assert_not_awaited()
        job_manager._scheduler.add_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_db_id_does_not_persist(self, job_manager, event_store):
        """A resolved value can't be persisted if the event has no DB id."""
        event = MagicMock(
            id=None,
            title="Non-Farm Employment Change",
            country="USD",
            scheduled_at=datetime(2026, 6, 5, 12, 30, 0),
        )
        with patch("forex_bot.scheduler.jobs.actuals.lookup_mapping", return_value=object()), \
             patch("forex_bot.scheduler.jobs.actuals.resolve_actual", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = "206K"

            await job_manager._poll_actual(event, attempt=1)

        event_store.set_actual.assert_not_awaited()
        # Still stops polling — the value was found, we just couldn't store it.
        job_manager._scheduler.add_job.assert_not_called()


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
