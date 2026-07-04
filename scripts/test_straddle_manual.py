"""Manual straddle trigger for testing — places real paper orders via IB."""
from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

from loguru import logger

from forex_bot.broker.client import IBClient
from forex_bot.broker.pricing import PricingService
from forex_bot.config import get_settings
from forex_bot.execution.engine import ExecutionEngine
from forex_bot.models.events import EconomicEvent, EventImpact
from forex_bot.data.trade_journal import TradeJournal
from forex_bot.risk.circuit_breaker import CircuitBreaker
from forex_bot.risk.manager import RiskManager
from forex_bot.strategy.straddle import StraddleStrategy


async def main() -> None:
    pair = sys.argv[1] if len(sys.argv) > 1 else "AUDUSD"
    settings = get_settings()

    # Create a fake event for testing
    event = EconomicEvent(
        title="Manual Test Event",
        country="USD",
        impact=EventImpact.HIGH,
        scheduled_at=datetime.now(UTC).replace(tzinfo=None),
        target_pairs=[pair],
    )

    client = IBClient(client_id=99)  # Use different clientId from running bot
    try:
        await client.connect()
        logger.info(f"Connected to IB on port {settings.broker.port}")

        pricing = PricingService(client)
        circuit_breaker = CircuitBreaker()
        journal = TradeJournal()
        risk_mgr = RiskManager(client, circuit_breaker, journal)
        engine = ExecutionEngine(client, risk_mgr, settings, journal)
        engine.set_current_event(event)
        strategy = StraddleStrategy()

        price = await pricing.get_snapshot(pair)
        from forex_bot.broker.contracts import get_pip_size
        spread = price.spread_pips(get_pip_size(pair))
        logger.info(f"{pair} mid={price.mid}, bid={price.bid}, ask={price.ask}, spread={spread:.1f} pips")

        signals = await strategy.evaluate_pre_event(event, price)
        logger.info(f"Generated {len(signals)} signals")

        for sig in signals:
            logger.info(f"  {sig.side} {sig.instrument}: {sig}")

        if signals:
            await engine.execute_signals(signals)
            logger.info("Signals submitted to execution engine")
        else:
            logger.warning("No signals generated")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
