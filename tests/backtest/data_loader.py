"""Load historical events and prices for backtesting."""

from __future__ import annotations

from datetime import datetime

from forex_bot.calendar.store import EventStore
from forex_bot.models.events import EconomicEvent
from forex_bot.models.market import Candle


class BacktestDataLoader:
    """Loads historical data for backtesting."""

    def __init__(self):
        self._event_store = EventStore()

    async def load_events(self, start: datetime, end: datetime) -> list[EconomicEvent]:
        """Load events from the database for a date range."""
        return await self._event_store.get_events_range(start, end)

    async def load_prices_from_db(
        self,
        instrument: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """Load price data from the database."""
        from sqlalchemy import select
        from forex_bot.data.database import get_session
        from forex_bot.data.schemas import CandleRecord

        async with get_session() as session:
            result = await session.execute(
                select(CandleRecord)
                .where(
                    CandleRecord.instrument == instrument,
                    CandleRecord.timestamp >= start,
                    CandleRecord.timestamp <= end,
                )
                .order_by(CandleRecord.timestamp)
            )
            records = result.scalars().all()

        return [
            Candle(
                instrument=r.instrument,
                timestamp=r.timestamp,
                open=r.open,
                high=r.high,
                low=r.low,
                close=r.close,
                volume=r.volume,
                timeframe=r.timeframe,
            )
            for r in records
        ]
