from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from loguru import logger

from forex_bot.broker.client import IBClient
from forex_bot.broker.pricing import PricingService
from forex_bot.calendar.store import EventStore
from forex_bot.config import EventTarget, Settings
from forex_bot.execution.engine import ExecutionEngine
from forex_bot.execution.monitor import PositionMonitor
from forex_bot.models.events import EconomicEvent
from forex_bot.notifications.telegram import TelegramNotifier
from forex_bot.strategy.registry import StrategyRegistry

# Retry configuration for event handlers
_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = [5, 15, 30]
_PREFLIGHT_MINUTES = 2
_PREFLIGHT_RETRY_INTERVAL = 15
_PREFLIGHT_MAX_ATTEMPTS = 8  # 2 minutes / 15 seconds


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
        notifier: TelegramNotifier | None = None,
    ):
        self._scheduler = scheduler
        self._engine = execution_engine
        self._pricing = pricing
        self._event_store = event_store
        self._registry = strategy_registry
        self._monitor = monitor
        self._client = client
        self._settings = settings
        self._notifier = notifier

    def _pairs_for_event(self, event: EconomicEvent) -> list[str]:
        """Return instruments to trade for this event.

        Uses target_pairs from the event if set, otherwise looks up the
        matching EventTarget in config. Falls back to all instruments.
        """
        all_instruments = self._settings.trading.instruments
        target_pairs = event.target_pairs or self._lookup_target_pairs(event)
        if target_pairs:
            pairs = [p for p in all_instruments if p in target_pairs]
            if not pairs:
                logger.warning(
                    f"No instrument overlap for {event.title}: "
                    f"target_pairs={target_pairs}, instruments={all_instruments}"
                )
            return pairs
        return all_instruments

    def _lookup_target_pairs(self, event: EconomicEvent) -> list[str]:
        """Look up target pairs from events config by matching event title."""
        title_lower = event.title.lower().strip()
        for target in self._settings.events.target_events:
            if target.name.lower() in title_lower:
                return target.pairs
            for alias in target.aliases:
                if alias.lower() in title_lower:
                    return target.pairs
        return []

    def schedule_event_jobs(self, event: EconomicEvent, pre_minutes: int) -> None:
        """Schedule pre-flight, pre-event, and post-event jobs for a specific event."""
        now = datetime.now(UTC).replace(tzinfo=None)

        # Pre-flight connection check (2 minutes before pre-event)
        pre_time = event.scheduled_at - timedelta(minutes=pre_minutes)
        preflight_time = pre_time - timedelta(minutes=_PREFLIGHT_MINUTES)
        if preflight_time > now:
            self._scheduler.add_job(
                self._preflight_check,
                DateTrigger(run_date=preflight_time),
                args=[event],
                id=f"preflight_{event.title}_{event.scheduled_at.isoformat()}",
                replace_existing=True,
            )
            logger.info(f"Scheduled pre-flight check for {event.title} at {preflight_time} UTC")

        # Pre-event job
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

    async def _preflight_check(self, event: EconomicEvent) -> None:
        """Verify IB connection before event handlers fire. Retry until connected."""
        logger.info(f"PRE-FLIGHT: Checking IB connection for {event.title}")

        for attempt in range(1, _PREFLIGHT_MAX_ATTEMPTS + 1):
            if self._client.is_connected:
                logger.info(f"PRE-FLIGHT: IB connected (attempt {attempt}). Ready for {event.title}")
                return
            logger.warning(
                f"PRE-FLIGHT: IB disconnected (attempt {attempt}/{_PREFLIGHT_MAX_ATTEMPTS}), "
                f"reconnecting for {event.title}..."
            )
            try:
                await self._client.connect()
                logger.info(f"PRE-FLIGHT: IB reconnected successfully for {event.title}")
                return
            except Exception as e:
                logger.error(f"PRE-FLIGHT: Reconnection attempt {attempt} failed: {e}")
                if attempt < _PREFLIGHT_MAX_ATTEMPTS:
                    await asyncio.sleep(_PREFLIGHT_RETRY_INTERVAL)

        logger.critical(
            f"PRE-FLIGHT FAILED: Could not connect to IB after {_PREFLIGHT_MAX_ATTEMPTS} attempts. "
            f"Event {event.title} at {event.scheduled_at} UTC may not trade!"
        )
        if self._notifier:
            await self._notifier.notify_preflight_failed(event)

    async def _ensure_connected_with_retry(self) -> bool:
        """Ensure IB is connected, retrying with backoff. Returns True if connected."""
        if self._client.is_connected:
            return True

        for attempt, backoff in enumerate(_RETRY_BACKOFF_SECONDS, 1):
            logger.warning(f"IB disconnected, retry {attempt}/{_MAX_RETRIES} (backoff {backoff}s)")
            try:
                await self._client.connect()
                logger.info(f"IB reconnected on retry {attempt}")
                return True
            except Exception as e:
                logger.error(f"IB reconnection retry {attempt} failed: {e}")
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(backoff)

        logger.error(f"IB reconnection failed after {_MAX_RETRIES} retries")
        return False

    async def _pre_event_handler(self, event: EconomicEvent) -> None:
        """Execute pre-event strategies."""
        logger.info(f"PRE-EVENT: {event.title} (scheduled {event.scheduled_at} UTC)")

        if self._notifier:
            pre_minutes = self._settings.strategy.pre_event_minutes
            await self._notifier.notify_event_upcoming(event, pre_minutes)

        if not await self._ensure_connected_with_retry():
            logger.error(f"PRE-EVENT ABORTED: No IB connection for {event.title}")
            return

        self._engine.set_current_event(event)
        pairs = self._pairs_for_event(event)
        for strategy in self._registry.all():
            for pair in pairs:
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

        if not await self._ensure_connected_with_retry():
            logger.error(f"POST-EVENT ABORTED: No IB connection for {event.title}")
            return

        # Re-fetch event to get actual values
        events = await self._event_store.get_events_range(
            event.scheduled_at - timedelta(minutes=1),
            event.scheduled_at + timedelta(minutes=1),
        )
        current_event = events[0] if events else event

        self._engine.set_current_event(current_event)
        pairs = self._pairs_for_event(current_event)
        for strategy in self._registry.all():
            for pair in pairs:
                try:
                    price = await self._pricing.get_snapshot(pair)
                    signals = await strategy.evaluate_post_event(current_event, price)
                    if signals:
                        await self._engine.execute_signals(signals)
                except Exception as e:
                    logger.error(f"Post-event error ({strategy.name}/{pair}): {e}")
