from __future__ import annotations

from datetime import datetime
from loguru import logger
from sqlalchemy import select

from forex_bot.data.database import get_session
from forex_bot.data.schemas import EventRecord, TradeRecord


class EventLog:
    """Tracks forecast vs actual vs trade outcome per event."""

    async def get_event_outcomes(self, limit: int = 50) -> list[dict]:
        """Get events with their associated trade outcomes."""
        async with get_session() as session:
            result = await session.execute(
                select(EventRecord)
                .where(EventRecord.actual.isnot(None))
                .order_by(EventRecord.scheduled_at.desc())
                .limit(limit)
            )
            events = result.scalars().all()

        outcomes = []
        for event in events:
            # Find trades associated with this event
            async with get_session() as session:
                trade_result = await session.execute(
                    select(TradeRecord).where(TradeRecord.event_id == event.id)
                )
                trades = trade_result.scalars().all()

            total_pnl = sum(t.pnl for t in trades if t.pnl is not None)
            outcomes.append({
                "event": event.title,
                "scheduled_at": event.scheduled_at,
                "forecast": event.forecast,
                "actual": event.actual,
                "previous": event.previous,
                "trade_count": len(trades),
                "total_pnl": total_pnl,
            })

        return outcomes
