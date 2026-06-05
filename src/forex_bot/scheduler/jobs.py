from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from loguru import logger

from forex_bot.broker.client import IBClient
from forex_bot.broker.pricing import PricingService
from forex_bot.calendar.store import EventStore
from forex_bot.config import Settings
from forex_bot.execution.engine import ExecutionEngine
from forex_bot.execution.monitor import PositionMonitor
from forex_bot.models.events import EconomicEvent
from forex_bot.strategy.registry import StrategyRegistry


class JobManager:
    """Creates and manages event-driven jobs."""

    def __init__(
        self,
        scheduler: AsyncIOScheduler,
        execution_engine: ExecutionEngine,
        pricing: PricingService,
        event_store: EventStore,
        strategy_registry: StrategyRegistry,
        monitor: PositionMonitor,
        client: IBClient,
        settings: Settings,
    ):
        self._scheduler = scheduler
        self._engine = execution_engine
        self._pricing = pricing
        self._event_store = event_store
        self._registry = strategy_registry
        self._monitor = monitor
        self._client = client
        self._settings = settings

    def schedule_event_jobs(self, event: EconomicEvent, pre_minutes: int) -> None:
        """Schedule pre-event and post-event jobs for a specific event."""
        now = datetime.now(UTC)

        # Pre-event job
        pre_time = event.scheduled_at - timedelta(minutes=pre_minutes)
        if pre_time > now:
            self._scheduler.add_job(
                self._pre_event_handler,
                DateTrigger(run_date=pre_time),
                args=[event],
                id=f"pre_event_{event.title}_{event.scheduled_at.isoformat()}",
                replace_existing=True,
            )
            logger.info(f"Scheduled pre-event job for {event.title} at {pre_time} UTC")

        # Post-event job (event time + small delay for data release)
        post_delay = self._settings.strategy.surprise_entry_delay_seconds
        post_time = event.scheduled_at + timedelta(seconds=post_delay)
        if post_time > now:
            self._scheduler.add_job(
                self._post_event_handler,
                DateTrigger(run_date=post_time),
                args=[event],
                id=f"post_event_{event.title}_{event.scheduled_at.isoformat()}",
                replace_existing=True,
            )
            logger.info(f"Scheduled post-event job for {event.title} at {post_time} UTC")

    async def _pre_event_handler(self, event: EconomicEvent) -> None:
        """Execute pre-event strategies."""
        logger.info(f"PRE-EVENT: {event.title} (scheduled {event.scheduled_at} UTC)")

        for strategy in self._registry.all():
            for pair in self._settings.trading.instruments:
                try:
                    price = await self._pricing.get_snapshot(pair)
                    signals = await strategy.evaluate_pre_event(event, price)
                    if signals:
                        await self._engine.execute_signals(signals)
                except Exception as e:
                    logger.error(f"Pre-event error ({strategy.name}/{pair}): {e}")

    async def _post_event_handler(self, event: EconomicEvent) -> None:
        """Execute post-event strategies."""
        logger.info(f"POST-EVENT: {event.title} (scheduled {event.scheduled_at} UTC)")

        # Re-fetch event to get actual values
        events = await self._event_store.get_events_range(
            event.scheduled_at - timedelta(minutes=1),
            event.scheduled_at + timedelta(minutes=1),
        )
        current_event = events[0] if events else event

        for strategy in self._registry.all():
            for pair in self._settings.trading.instruments:
                try:
                    price = await self._pricing.get_snapshot(pair)
                    signals = await strategy.evaluate_post_event(current_event, price)
                    if signals:
                        await self._engine.execute_signals(signals)
                except Exception as e:
                    logger.error(f"Post-event error ({strategy.name}/{pair}): {e}")
