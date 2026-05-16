from __future__ import annotations

import asyncio
import signal
from loguru import logger

from forex_bot.broker.client import IBClient
from forex_bot.execution.monitor import PositionMonitor


class ShutdownHandler:
    """Handles graceful shutdown on SIGINT/SIGTERM."""

    def __init__(self, client: IBClient, scheduler, monitor: PositionMonitor):
        self._client = client
        self._scheduler = scheduler
        self._monitor = monitor

    def register(self) -> None:
        """Register signal handlers."""
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(self.shutdown()))
        logger.debug("Shutdown handlers registered")

    async def shutdown(self) -> None:
        """Graceful shutdown sequence."""
        logger.info("Initiating graceful shutdown...")

        # 1. Stop scheduler
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

        # 2. Stop position monitoring
        self._monitor.stop_monitoring()

        # 3. Disconnect from IB
        await self._client.disconnect()

        logger.info("Shutdown complete")
