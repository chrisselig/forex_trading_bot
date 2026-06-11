from __future__ import annotations

import asyncio
import signal
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from forex_bot.broker.client import IBClient
from forex_bot.broker.pricing import PricingService
from forex_bot.calendar.export import export_calendar_json
from forex_bot.calendar.scraper import ForexFactoryScraper
from forex_bot.calendar.parser import EventParser
from forex_bot.calendar.static import load_static_events, validate_static_calendar
from forex_bot.calendar.store import EventStore
from forex_bot.config import get_settings
from forex_bot.broker.sweep import sweep_to_cad
from forex_bot.data.database import init_db
from forex_bot.data.dukascopy import download_new_event_data
from forex_bot.data.trade_journal import TradeJournal
from forex_bot.execution.engine import ExecutionEngine
from forex_bot.execution.monitor import PositionMonitor
from forex_bot.execution.reconciler import Reconciler
from forex_bot.models.events import EconomicEvent
from forex_bot.notifications.telegram import TelegramNotifier
from forex_bot.risk.circuit_breaker import CircuitBreaker
from forex_bot.risk.manager import RiskManager
from forex_bot.scheduler.jobs import JobManager
from forex_bot.scheduler.shutdown import ShutdownHandler
from forex_bot.strategy.registry import create_default_registry


class Orchestrator:
    """Main orchestrator: startup, scheduling, and event coordination."""

    def __init__(self):
        self._settings = get_settings()
        self._client = IBClient()
        self._scheduler = AsyncIOScheduler(timezone="UTC")

        # Telegram notifications
        tg = self._settings.telegram
        self._notifier = TelegramNotifier(
            bot_token=tg.bot_token,
            chat_id=tg.chat_id,
            enabled=tg.enabled,
        )

        self._circuit_breaker = CircuitBreaker(
            max_daily_drawdown_pct=self._settings.risk.max_daily_drawdown_pct,
            notifier=self._notifier,
        )
        self._journal = TradeJournal(notifier=self._notifier)
        self._risk_manager = RiskManager(self._client, self._circuit_breaker, self._journal)
        self._execution_engine = ExecutionEngine(
            self._client, self._risk_manager, self._circuit_breaker, self._journal,
            notifier=self._notifier,
        )
        self._monitor = PositionMonitor(
            self._client, self._journal, self._circuit_breaker,
            notifier=self._notifier,
        )
        self._reconciler = Reconciler(self._client)
        self._pricing = PricingService(self._client)
        self._scraper = ForexFactoryScraper()
        self._parser = EventParser()
        self._event_store = EventStore()
        self._strategy_registry = create_default_registry()
        self._job_manager = JobManager(
            scheduler=self._scheduler,
            execution_engine=self._execution_engine,
            pricing=self._pricing,
            event_store=self._event_store,
            strategy_registry=self._strategy_registry,
            monitor=self._monitor,
            client=self._client,
            settings=self._settings,
            notifier=self._notifier,
        )
        self._shutdown_handler = ShutdownHandler(self._client, self._scheduler, self._monitor)
        self._running = False

    async def start(self) -> None:
        """Full startup sequence."""
        logger.info("Starting Forex Trading Bot...")

        # 1. Initialize database
        await init_db()

        # 2. Connect to IB
        await self._client.connect()

        # 3. Reconcile state
        state = await self._reconciler.reconcile()
        logger.info(f"Account NLV: ${state['net_liquidation']:,.2f}")

        # 4. Start position monitoring
        self._monitor.start_monitoring()

        # 5. Validate static calendar against master event list
        missing = validate_static_calendar()
        if missing:
            await self._notifier.send_raw(
                f"*STATIC CALENDAR WARNING*\n\n"
                f"{len(missing)} event(s) missing from static\\_events.yaml "
                f"(next {30} days):\n\n"
                + "\n".join(f"• {m}" for m in missing)
                + "\n\n_Update config/static\\_events.yaml to avoid missed trades._"
            )

        # 6. Refresh calendar
        await self._refresh_calendar()

        # 7. Schedule recurring jobs
        self._schedule_recurring_jobs()

        # 8. Schedule upcoming event jobs
        await self._schedule_event_jobs()

        # 9. Register shutdown handlers
        self._shutdown_handler.register()

        # 10. Start scheduler
        self._scheduler.start()
        self._running = True
        logger.info("Forex Trading Bot is running. Press Ctrl+C to stop.")

        # 11. Send startup notification
        try:
            account = await self._client.get_account_summary()
            await self._notifier.notify_bot_started(account)
        except Exception as e:
            logger.warning(f"Startup notification failed: {e}")

    async def _refresh_calendar(self) -> None:
        """Fetch and store upcoming events from Forex Factory + static calendar."""
        try:
            # Forex Factory events (USD, JPY majors)
            events = await self._scraper.fetch_week()
            filtered = self._parser.filter_events(events)
            await self._event_store.save_events(filtered)
            await self._event_store.update_actuals(events)

            # Static events (SARB, TCMB, SA CPI, BOJ — not on Forex Factory)
            static = load_static_events()
            static_filtered = self._parser.filter_events(static)
            await self._event_store.save_events(static_filtered)

            total = len(filtered) + len(static_filtered)
            logger.info(
                f"Calendar refreshed: {len(filtered)} FF + {len(static_filtered)} static = {total} events"
            )

            # Export calendar JSON for web dashboard
            await self._export_calendar()
        except Exception as e:
            logger.error(f"Calendar refresh failed: {e}")

    async def _export_calendar(self) -> None:
        """Export tradeable events calendar JSON for the web dashboard."""
        try:
            await export_calendar_json()
        except Exception as e:
            logger.error(f"Calendar export failed: {e}")

    def _schedule_recurring_jobs(self) -> None:
        """Set up periodic jobs."""
        # Calendar refresh every 6 hours
        self._scheduler.add_job(
            self._refresh_calendar,
            IntervalTrigger(hours=6),
            id="calendar_refresh",
            replace_existing=True,
        )

        # Health check every 5 minutes
        self._scheduler.add_job(
            self._health_check,
            IntervalTrigger(minutes=5),
            id="health_check",
            replace_existing=True,
        )

        # Check expired positions every minute
        self._scheduler.add_job(
            self._monitor.close_expired_positions,
            IntervalTrigger(minutes=1),
            id="check_expired",
            replace_existing=True,
        )

        # Daily circuit breaker reset at 00:00 UTC
        self._scheduler.add_job(
            self._circuit_breaker.reset_daily,
            CronTrigger(hour=0, minute=0),
            id="daily_cb_reset",
            replace_existing=True,
        )

        # Nightly currency sweep at 03:30 UTC (10:30 PM ET)
        self._scheduler.add_job(
            self._nightly_currency_sweep,
            CronTrigger(hour=3, minute=30),
            id="nightly_currency_sweep",
            replace_existing=True,
        )

        # Nightly Dukascopy data download at 04:00 UTC (11 PM ET)
        self._scheduler.add_job(
            self._nightly_data_download,
            CronTrigger(hour=4, minute=0),
            id="nightly_dukascopy_download",
            replace_existing=True,
        )

        logger.info("Recurring jobs scheduled")

    async def _schedule_event_jobs(self) -> None:
        """Schedule pre/post event jobs for upcoming events."""
        events = await self._event_store.get_upcoming(within_hours=24)
        pre_minutes = self._settings.strategy.pre_event_minutes

        for event in events:
            self._job_manager.schedule_event_jobs(event, pre_minutes)

        logger.info(f"Scheduled jobs for {len(events)} upcoming events")

    async def _nightly_currency_sweep(self) -> None:
        """Sweep residual non-CAD cash balances back to CAD."""
        try:
            if not self._client.is_connected:
                logger.warning("Currency sweep skipped: IB not connected")
                return
            results = await sweep_to_cad(self._client)
            if results:
                logger.info(f"Currency sweep completed: {len(results)} conversion(s)")
        except Exception as e:
            logger.error(f"Currency sweep failed: {e}")

    async def _nightly_data_download(self) -> None:
        """Download Dukascopy 1-min data for any new events."""
        try:
            await download_new_event_data()
        except Exception as e:
            logger.error(f"Nightly Dukascopy download failed: {e}")

    async def _health_check(self) -> None:
        """Verify IB connection and reconnect if needed."""
        if not self._client.is_connected:
            logger.warning("IB connection lost during health check")
            await self._notifier.notify_connection_lost()
            try:
                await self._client.connect()
                logger.info("IB reconnection successful")
                await self._notifier.notify_connection_restored()
                await self._refresh_calendar()
                await self._schedule_event_jobs()
                logger.info("Event jobs re-scheduled after reconnect")
            except Exception as e:
                logger.error(f"IB reconnection failed: {e}")

    async def run_forever(self) -> None:
        """Start and run until interrupted."""
        await self.start()
        try:
            while self._running:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutdown signal received")
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        await self._notifier.notify_bot_stopped()
        await self._shutdown_handler.shutdown()
        logger.info("Forex Trading Bot stopped.")
