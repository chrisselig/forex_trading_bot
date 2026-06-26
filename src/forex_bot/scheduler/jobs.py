from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from loguru import logger

from forex_bot.broker.client import IBClient
from forex_bot.broker.pricing import PricingService
from forex_bot.broker.tws_launcher import ensure_tws_running, is_tws_listening
from forex_bot.calendar.scraper import ForexFactoryScraper
from forex_bot.calendar.store import EventStore
from forex_bot.config import Settings
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
_ACTUAL_POLL_INTERVAL_MINUTES = 10
_ACTUAL_POLL_MAX_ATTEMPTS = 12  # 12 × 10 min = 2 hours
_TWS_ENSURE_MINUTES = 10  # cold-start check fires this many minutes before preflight


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
        scraper: ForexFactoryScraper | None = None,
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
        self._scraper = scraper
        # Track (pair, event_time) combos to prevent duplicate straddles
        # when multiple events fire at the same scheduled time
        self._straddle_placed: set[tuple[str, datetime]] = set()

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
        """Look up target pairs from events config by matching event title.

        Respects country validation: a target with a country set will only
        match events from the same country (prevents cross-country collisions).
        """
        title_lower = event.title.lower().strip()
        for target in self._settings.events.target_events:
            # Skip if target is country-specific and event is from a different country
            if target.country and target.country != event.country:
                continue
            if title_lower == target.name.lower().strip():
                return target.pairs
            for alias in target.aliases:
                if title_lower == alias.lower().strip():
                    return target.pairs
        return []

    def schedule_event_jobs(self, event: EconomicEvent, pre_minutes: int) -> None:
        """Schedule pre-flight, pre-event, and post-event jobs for a specific event."""
        now = datetime.now(UTC).replace(tzinfo=None)

        # TWS cold-start check (10 minutes before preflight = 42 min before event)
        pre_time = event.scheduled_at - timedelta(minutes=pre_minutes)
        preflight_time = pre_time - timedelta(minutes=_PREFLIGHT_MINUTES)
        tws_ensure_time = preflight_time - timedelta(minutes=_TWS_ENSURE_MINUTES)
        if tws_ensure_time > now:
            self._scheduler.add_job(
                self._tws_ensure,
                DateTrigger(run_date=tws_ensure_time, timezone="UTC"),
                args=[event],
                id=f"tws_ensure_{event.title}_{event.scheduled_at.isoformat()}",
                replace_existing=True,
            )
            logger.info(f"Scheduled TWS ensure for {event.title} at {tws_ensure_time} UTC")

        # Pre-flight connection check (2 minutes before pre-event)
        if preflight_time > now:
            self._scheduler.add_job(
                self._preflight_check,
                DateTrigger(run_date=preflight_time, timezone="UTC"),
                args=[event],
                id=f"preflight_{event.title}_{event.scheduled_at.isoformat()}",
                replace_existing=True,
            )
            logger.info(f"Scheduled pre-flight check for {event.title} at {preflight_time} UTC")

        # Pre-event job
        if pre_time > now:
            self._scheduler.add_job(
                self._pre_event_handler,
                DateTrigger(run_date=pre_time, timezone="UTC"),
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
                DateTrigger(run_date=post_time, timezone="UTC"),
                args=[event],
                id=f"post_event_{event.title}_{event.scheduled_at.isoformat()}",
                replace_existing=True,
            )
            logger.info(f"Scheduled post-event job for {event.title} at {post_time} UTC")

    async def _tws_ensure(self, event: EconomicEvent) -> None:
        """Check if TWS is listening; cold-start it if not.

        Fires ~42 min before event time to give TWS enough time to initialize
        before the preflight check runs.
        """
        port = self._settings.broker.port
        if is_tws_listening(port):
            logger.info(f"TWS_ENSURE: TWS already listening on port {port} for {event.title}")
            return

        logger.warning(
            f"TWS_ENSURE: TWS not listening on port {port} before {event.title} — "
            f"initiating cold-start"
        )
        if self._notifier:
            await self._notifier.send_raw(
                f"*TWS COLD-START*\n\n"
                f"TWS is down before *{event.title}*\n"
                f"Attempting cold-start on port `{port}`...\n\n"
                f"_{TelegramNotifier._fmt_et(datetime.now(UTC))}_"
            )

        success = await ensure_tws_running(port)
        if success:
            logger.info(f"TWS_ENSURE: Cold-start successful for {event.title}")
            if self._notifier:
                await self._notifier.send_raw(
                    f"*TWS COLD-START OK*\n\n"
                    f"TWS is back up on port `{port}` for *{event.title}*"
                )
        else:
            logger.critical(
                f"TWS_ENSURE: Cold-start FAILED for {event.title} on port {port}"
            )
            if self._notifier:
                await self._notifier.send_raw(
                    f"*TWS COLD-START FAILED*\n\n"
                    f"Could not restart TWS on port `{port}` for *{event.title}*\n"
                    f"*Preflight may also fail!*"
                )

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

        # Last resort: try cold-starting TWS in case it's completely dead
        port = self._settings.broker.port
        if not is_tws_listening(port):
            logger.warning(
                f"PRE-FLIGHT: TWS not listening on port {port}, attempting cold-start as last resort"
            )
            started = await ensure_tws_running(port)
            if started:
                try:
                    await self._client.connect()
                    logger.info(f"PRE-FLIGHT: IB connected after cold-start for {event.title}")
                    return
                except Exception as e:
                    logger.error(f"PRE-FLIGHT: Connect after cold-start failed: {e}")

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
        # Prune stale dedup keys (older than 24h)
        cutoff = datetime.now(UTC) - timedelta(hours=24)
        self._straddle_placed = {k for k in self._straddle_placed if k[1] > cutoff}

        pairs = self._pairs_for_event(event)
        for strategy in self._registry.all():
            for pair in pairs:
                # Deduplicate: skip if we already placed a straddle for this
                # pair at this event time (multiple events can fire simultaneously)
                dedup_key = (pair, event.scheduled_at)
                if strategy.name == "straddle" and dedup_key in self._straddle_placed:
                    logger.info(
                        f"Skipping duplicate straddle for {pair} at {event.scheduled_at} "
                        f"(already placed for earlier event)"
                    )
                    continue
                try:
                    price = await self._pricing.get_snapshot(pair)
                    signals = await strategy.evaluate_pre_event(event, price)
                    if signals:
                        await self._engine.execute_signals(signals)
                        if strategy.name == "straddle":
                            self._straddle_placed.add(dedup_key)
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

        # Schedule actual value polling if scraper is available
        if self._scraper:
            self._schedule_actual_poll(event)

    def _schedule_actual_poll(self, event: EconomicEvent) -> None:
        """Schedule recurring poll for the event's actual value."""
        poll_time = datetime.now(UTC).replace(tzinfo=None) + timedelta(
            minutes=_ACTUAL_POLL_INTERVAL_MINUTES
        )
        job_id = f"poll_actual_{event.title}_{event.scheduled_at.isoformat()}"
        self._scheduler.add_job(
            self._poll_actual,
            DateTrigger(run_date=poll_time, timezone="UTC"),
            args=[event, 1],
            id=job_id,
            replace_existing=True,
        )
        logger.info(f"Scheduled actual polling for {event.title} (attempt 1/{_ACTUAL_POLL_MAX_ATTEMPTS})")

    async def _poll_actual(self, event: EconomicEvent, attempt: int) -> None:
        """Poll Forex Factory for the event's actual value."""
        logger.info(f"Polling actual for {event.title} (attempt {attempt}/{_ACTUAL_POLL_MAX_ATTEMPTS})")

        try:
            ff_events = await self._scraper.fetch_week(date=event.scheduled_at)
            updated = await self._event_store.update_actuals(ff_events)

            # Check if our target event now has an actual
            refreshed = await self._event_store.get_events_range(
                event.scheduled_at - timedelta(minutes=1),
                event.scheduled_at + timedelta(minutes=1),
            )
            target = next((e for e in refreshed if e.title == event.title), None)

            if target and target.has_actual:
                logger.info(
                    f"Actual found for {event.title}: {target.actual} "
                    f"(attempt {attempt}/{_ACTUAL_POLL_MAX_ATTEMPTS})"
                )
                return  # Done — no more polling

            if updated:
                logger.info(f"Updated {updated} actuals, but {event.title} still missing")

        except Exception as e:
            logger.error(f"Actual poll failed for {event.title}: {e}")

        # Schedule next attempt if not exhausted
        if attempt < _ACTUAL_POLL_MAX_ATTEMPTS:
            next_time = datetime.now(UTC).replace(tzinfo=None) + timedelta(
                minutes=_ACTUAL_POLL_INTERVAL_MINUTES
            )
            job_id = f"poll_actual_{event.title}_{event.scheduled_at.isoformat()}"
            self._scheduler.add_job(
                self._poll_actual,
                DateTrigger(run_date=next_time, timezone="UTC"),
                args=[event, attempt + 1],
                id=job_id,
                replace_existing=True,
            )
        else:
            logger.warning(
                f"Actual polling exhausted for {event.title} after {_ACTUAL_POLL_MAX_ATTEMPTS} attempts"
            )
