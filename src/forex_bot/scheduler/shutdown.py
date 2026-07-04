from __future__ import annotations

import asyncio
import signal
from loguru import logger

from forex_bot.broker.client import IBClient
from forex_bot.execution.monitor import PositionMonitor


class ShutdownHandler:
    """Handles graceful shutdown on SIGINT/SIGTERM."""

    def __init__(
        self,
        client: IBClient,
        scheduler,
        monitor: PositionMonitor,
        stop_event: asyncio.Event | None = None,
    ):
        self._client = client
        self._scheduler = scheduler
        self._monitor = monitor
        # Signals the orchestrator's run_forever loop to exit. Without it,
        # SIGTERM stopped the scheduler and disconnected IB but left the
        # process spinning forever as a zombie (the documented "kill -9"
        # workaround was this bug).
        self._stop_event = stop_event
        self._done = False

    def register(self) -> None:
        """Register signal handlers."""
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(self.shutdown()))
        logger.debug("Shutdown handlers registered")

    async def shutdown(self) -> None:
        """Graceful shutdown sequence (idempotent)."""
        if self._done:
            return
        self._done = True
        logger.info("Initiating graceful shutdown...")

        # 1. Stop scheduler
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

        # 2. Stop position monitoring
        self._monitor.stop_monitoring()

        # 3. Disconnect from IB
        await self._client.disconnect()

        # 4. Let run_forever exit so the process actually terminates
        if self._stop_event is not None:
            self._stop_event.set()

        logger.info("Shutdown complete")
