from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import select, update

from forex_bot.data.database import get_session
from forex_bot.data.schemas import TradeRecord, OrderRecord
from forex_bot.models.orders import Order, Trade, OrderStatus

if TYPE_CHECKING:
    from forex_bot.notifications.telegram import TelegramNotifier


class TradeJournal:
    """Logs every order and trade to the database."""

    def __init__(self, notifier: TelegramNotifier | None = None):
        self._notifier = notifier

    async def log_order(self, order: Order) -> int:
        """Log an order and return its database ID."""
        async with get_session() as session:
            record = OrderRecord(
                ib_order_id=order.ib_order_id,
                instrument=order.instrument,
                side=order.side.value,
                order_type=order.order_type.value,
                quantity=order.quantity,
                price=order.price,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
                status=order.status.value,
                event_id=order.event_id,
                strategy=order.strategy,
            )
            session.add(record)
            await session.commit()
            logger.info(f"Logged order #{record.id}: {order.side} {order.quantity} {order.instrument}")
            return record.id

    async def update_order_status(self, order_id: int, status: OrderStatus, fill_price: float | None = None) -> None:
        """Update an order's status in the journal."""
        async with get_session() as session:
            values: dict = {"status": status.value}
            if fill_price is not None:
                values["fill_price"] = fill_price
                values["filled_at"] = datetime.utcnow()
            await session.execute(
                update(OrderRecord).where(OrderRecord.id == order_id).values(**values)
            )
            await session.commit()

    async def log_trade(self, trade: Trade) -> int:
        """Log a trade entry and return its database ID."""
        async with get_session() as session:
            record = TradeRecord(
                order_id=trade.order_id,
                instrument=trade.instrument,
                side=trade.side.value,
                quantity=trade.quantity,
                entry_price=trade.entry_price,
                stop_loss=trade.stop_loss,
                take_profit=trade.take_profit,
                event_id=trade.event_id,
                strategy=trade.strategy,
            )
            session.add(record)
            await session.commit()
            logger.info(f"Logged trade #{record.id}: {trade.side} {trade.quantity} {trade.instrument} @ {trade.entry_price}")
            return record.id

    async def close_trade(self, trade_id: int, exit_price: float, pnl: float, pnl_pips: float) -> None:
        """Record trade exit."""
        async with get_session() as session:
            await session.execute(
                update(TradeRecord)
                .where(TradeRecord.id == trade_id)
                .values(
                    exit_price=exit_price,
                    pnl=pnl,
                    pnl_pips=pnl_pips,
                    closed_at=datetime.utcnow(),
                )
            )
            await session.commit()
            logger.info(f"Closed trade #{trade_id}: exit={exit_price} pnl={pnl:.2f} ({pnl_pips:.1f} pips)")

        if self._notifier:
            # Fetch the full trade to send notification
            trades = await self.get_trades(limit=100)
            trade = next((t for t in trades if t.id == trade_id), None)
            if trade:
                daily_pnl = await self.get_daily_pnl()
                await self._notifier.notify_trade_closed(
                    trade=trade, daily_pnl=daily_pnl,
                )

    async def get_trades(self, strategy: str | None = None, limit: int = 50) -> list[Trade]:
        """Retrieve recent trades from the journal."""
        async with get_session() as session:
            query = select(TradeRecord).order_by(TradeRecord.opened_at.desc()).limit(limit)
            if strategy:
                query = query.where(TradeRecord.strategy == strategy)
            result = await session.execute(query)
            records = result.scalars().all()

        return [self._to_model(r) for r in records]

    async def get_daily_pnl(self) -> float:
        """Get total P&L for today."""
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        async with get_session() as session:
            result = await session.execute(
                select(TradeRecord).where(
                    TradeRecord.closed_at >= today,
                    TradeRecord.pnl.isnot(None),
                )
            )
            records = result.scalars().all()
        return sum(r.pnl for r in records if r.pnl is not None)

    @staticmethod
    def _to_model(record: TradeRecord) -> Trade:
        from forex_bot.models.orders import OrderSide
        return Trade(
            id=record.id,
            order_id=record.order_id,
            instrument=record.instrument,
            side=OrderSide(record.side),
            quantity=record.quantity,
            entry_price=record.entry_price,
            exit_price=record.exit_price,
            stop_loss=record.stop_loss,
            take_profit=record.take_profit,
            pnl=record.pnl,
            pnl_pips=record.pnl_pips,
            event_id=record.event_id,
            strategy=record.strategy,
            opened_at=record.opened_at,
            closed_at=record.closed_at,
        )
