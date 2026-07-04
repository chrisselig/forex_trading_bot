"""Unit tests for job manager retry and pre-flight logic."""

from __future__ import annotations

import pytest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from forex_bot.scheduler.jobs import JobManager, _MAX_RETRIES, _PREFLIGHT_MAX_ATTEMPTS
from forex_bot.strategy.straddle import StraddleStrategy


@pytest.fixture
def job_manager():
    client = MagicMock()
    client.is_connected = True
    client.connect = AsyncMock()
    client.get_open_orders = AsyncMock(return_value=[])

    pricing = MagicMock()
    pricing.get_snapshot = AsyncMock()

    engine = MagicMock()
    engine.execute_signals = AsyncMock()

    event_store = MagicMock()
    event_store.get_events_range = AsyncMock(return_value=[])

    strategy = MagicMock()
    strategy.name = "straddle"
    strategy.evaluate_pre_event = AsyncMock(return_value=[])
    strategy.evaluate_post_event = AsyncMock(return_value=[])

    registry = MagicMock()
    registry.all.return_value = [strategy]

    settings = MagicMock()
    settings.trading.instruments = ["EURUSD"]
    settings.strategy.pre_event_minutes = 30
    settings.strategy.surprise_entry_delay_seconds = 5
    settings.strategy.min_pre_event_lead_seconds = 90

    scheduler = MagicMock()

    jm = JobManager(
        scheduler=scheduler,
        execution_engine=engine,
        pricing=pricing,
        event_store=event_store,
        strategy_registry=registry,
        monitor=MagicMock(),
        client=client,
        settings=settings,
    )
    return jm, client, pricing, engine, strategy


@pytest.fixture
def event():
    # Scheduled comfortably in the future so the pre-event min-lead gate passes.
    return MagicMock(
        id=1,
        title="Non-Farm Employment Change",
        scheduled_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2),
        target_pairs=["EURUSD"],
    )


class TestPreflightCheck:
    @pytest.mark.asyncio
    async def test_preflight_passes_when_connected(self, job_manager, event):
        jm, client, *_ = job_manager
        client.is_connected = True

        await jm._preflight_check(event)
        client.connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_preflight_reconnects_when_disconnected(self, job_manager, event):
        jm, client, *_ = job_manager
        client.is_connected = False
        client.connect = AsyncMock(side_effect=lambda: setattr(client, 'is_connected', True))

        await jm._preflight_check(event)
        client.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_preflight_retries_on_failure(self, job_manager, event):
        jm, client, *_ = job_manager
        client.is_connected = False
        from forex_bot.broker.exceptions import BrokerConnectionError
        client.connect = AsyncMock(
            side_effect=[BrokerConnectionError("fail"), BrokerConnectionError("fail"), None]
        )

        with patch("forex_bot.scheduler.jobs.asyncio.sleep", new_callable=AsyncMock):
            await jm._preflight_check(event)
        assert client.connect.call_count == 3

    @pytest.mark.asyncio
    async def test_preflight_logs_critical_after_all_attempts_fail(self, job_manager, event):
        jm, client, *_ = job_manager
        client.is_connected = False
        from forex_bot.broker.exceptions import BrokerConnectionError
        client.connect = AsyncMock(side_effect=BrokerConnectionError("fail"))

        with patch("forex_bot.scheduler.jobs.asyncio.sleep", new_callable=AsyncMock):
            await jm._preflight_check(event)
        assert client.connect.call_count == _PREFLIGHT_MAX_ATTEMPTS


class TestEnsureConnectedWithRetry:
    @pytest.mark.asyncio
    async def test_returns_true_when_already_connected(self, job_manager):
        jm, client, *_ = job_manager
        client.is_connected = True

        assert await jm._ensure_connected_with_retry() is True
        client.connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_reconnects_on_first_retry(self, job_manager):
        jm, client, *_ = job_manager
        client.is_connected = False

        assert await jm._ensure_connected_with_retry() is True
        client.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_retries_with_backoff_on_failure(self, job_manager):
        jm, client, *_ = job_manager
        client.is_connected = False
        from forex_bot.broker.exceptions import BrokerConnectionError
        client.connect = AsyncMock(
            side_effect=[BrokerConnectionError("fail"), BrokerConnectionError("fail"), None]
        )

        with patch("forex_bot.scheduler.jobs.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await jm._ensure_connected_with_retry()

        assert result is True
        assert client.connect.call_count == 3
        assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    async def test_returns_false_after_all_retries_exhausted(self, job_manager):
        jm, client, *_ = job_manager
        client.is_connected = False
        from forex_bot.broker.exceptions import BrokerConnectionError
        client.connect = AsyncMock(side_effect=BrokerConnectionError("fail"))

        with patch("forex_bot.scheduler.jobs.asyncio.sleep", new_callable=AsyncMock):
            result = await jm._ensure_connected_with_retry()

        assert result is False
        assert client.connect.call_count == _MAX_RETRIES


class TestPreEventHandler:
    @pytest.mark.asyncio
    async def test_executes_when_connected(self, job_manager, event):
        jm, client, pricing, engine, strategy = job_manager
        strategy.evaluate_pre_event = AsyncMock(return_value=[MagicMock()])

        await jm._pre_event_handler(event)

        pricing.get_snapshot.assert_called_once_with("EURUSD")
        strategy.evaluate_pre_event.assert_called_once()
        engine.execute_signals.assert_called_once()

    @pytest.mark.asyncio
    async def test_aborts_when_disconnected(self, job_manager, event):
        jm, client, pricing, engine, strategy = job_manager
        client.is_connected = False
        from forex_bot.broker.exceptions import BrokerConnectionError
        client.connect = AsyncMock(side_effect=BrokerConnectionError("fail"))

        with patch("forex_bot.scheduler.jobs.asyncio.sleep", new_callable=AsyncMock):
            await jm._pre_event_handler(event)

        pricing.get_snapshot.assert_not_called()
        strategy.evaluate_pre_event.assert_not_called()
        engine.execute_signals.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_and_alerts_when_too_close_to_event(self, job_manager, event):
        jm, client, pricing, engine, strategy = job_manager
        # Event fires in 30s — below the 90s min lead: too late to position.
        event.scheduled_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=30)
        jm._notifier = AsyncMock()
        strategy.evaluate_pre_event = AsyncMock(return_value=[MagicMock()])

        await jm._pre_event_handler(event)

        jm._notifier.notify_straddle_missed.assert_called_once()
        pricing.get_snapshot.assert_not_called()
        strategy.evaluate_pre_event.assert_not_called()
        engine.execute_signals.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_resting_straddle_already_on_ib(self, job_manager, event):
        jm, client, pricing, engine, strategy = job_manager
        # A resting straddle for this exact pair+event is already live on IB.
        resting = MagicMock()
        resting.order.ocaGroup = StraddleStrategy.oca_prefix("EURUSD", event) + "_42"
        client.get_open_orders = AsyncMock(return_value=[resting])
        strategy.evaluate_pre_event = AsyncMock(return_value=[MagicMock()])

        await jm._pre_event_handler(event)

        pricing.get_snapshot.assert_not_called()
        strategy.evaluate_pre_event.assert_not_called()
        engine.execute_signals.assert_not_called()


class TestPostEventHandler:
    @pytest.mark.asyncio
    async def test_executes_when_connected(self, job_manager, event):
        jm, client, pricing, engine, strategy = job_manager
        strategy.evaluate_post_event = AsyncMock(return_value=[MagicMock()])

        await jm._post_event_handler(event)

        pricing.get_snapshot.assert_called_once_with("EURUSD")
        strategy.evaluate_post_event.assert_called_once()
        engine.execute_signals.assert_called_once()

    @pytest.mark.asyncio
    async def test_aborts_when_disconnected(self, job_manager, event):
        jm, client, pricing, engine, strategy = job_manager
        client.is_connected = False
        from forex_bot.broker.exceptions import BrokerConnectionError
        client.connect = AsyncMock(side_effect=BrokerConnectionError("fail"))

        with patch("forex_bot.scheduler.jobs.asyncio.sleep", new_callable=AsyncMock):
            await jm._post_event_handler(event)

        pricing.get_snapshot.assert_not_called()
        strategy.evaluate_post_event.assert_not_called()
        engine.execute_signals.assert_not_called()


class TestScheduleEventJobs:
    def test_schedules_preflight_pre_and_post_jobs(self, job_manager, event):
        jm, *_ = job_manager
        event.scheduled_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2)

        jm.schedule_event_jobs(event, pre_minutes=30)

        scheduler = jm._scheduler
        assert scheduler.add_job.call_count == 4
        job_ids = [call.kwargs["id"] for call in scheduler.add_job.call_args_list]
        assert any("tws_ensure_" in jid for jid in job_ids)
        assert any("preflight_" in jid for jid in job_ids)
        assert any("pre_event_" in jid for jid in job_ids)
        assert any("post_event_" in jid for jid in job_ids)

    def test_late_start_still_schedules_catchup_pre_event(self, job_manager, event):
        jm, *_ = job_manager
        # Event fires in 10 min: the T-30 pre-event window (and the earlier
        # tws_ensure/preflight windows) have already passed, but the event has
        # not fired. Only the catch-up pre_event and post_event should schedule.
        event.scheduled_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=10)

        jm.schedule_event_jobs(event, pre_minutes=30)

        scheduler = jm._scheduler
        job_ids = [call.kwargs["id"] for call in scheduler.add_job.call_args_list]
        assert any("pre_event_" in jid for jid in job_ids)
        assert any("post_event_" in jid for jid in job_ids)
        # Past windows are not scheduled as jobs in the past.
        assert not any("tws_ensure_" in jid for jid in job_ids)
        assert not any("preflight_" in jid for jid in job_ids)
