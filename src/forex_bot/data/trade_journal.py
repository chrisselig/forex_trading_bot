from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import func, select, update

from forex_bot.data.database import get_session
from forex_bot.data.schemas import TradeRecord, OrderRecord
from forex_bot.data.turso_sync import TursoSyncer
from forex_bot.models.orders import Order, OrderSide, OrderStatus, Trade

if TYPE_CHECKING:
    from forex_bot.notifications.telegram import TelegramNotifier
    from forex_bot.reporting.alerts import AnomalyDetector


class TradeJournal:
    """Logs every order and trade to the database."""

    def __init__(
        self,
        notifier: TelegramNotifier | None = None,
        turso: TursoSyncer | None = None,
        anomaly_detector: AnomalyDetector | None = None,
        account_type: str = "paper",
    ):
        self._notifier = notifier
        self._turso = turso
        self._anomaly_detector = anomaly_detector
        self._account_type = account_type

    async def log_order(self, order: Order, entry_spread_pips: float | None = None) -> int:
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
                entry_spread_pips=entry_spread_pips,
                account_type=self._account_type,
            )
            session.add(record)
            await session.commit()
            spread_str = f" (spread={entry_spread_pips:.1f} pips)" if entry_spread_pips is not None else ""
            logger.info(f"Logged order #{record.id}: {order.side} {order.quantity} {order.instrument}{spread_str}")
            db_id = record.id

        if self._turso:
            await self._turso.push_order(
                order_id=db_id,
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
                entry_spread_pips=entry_spread_pips,
                created_at=datetime.utcnow(),
            )

        return db_id

    async def update_order_status(
        self,
        order_id: int,
        status: OrderStatus,
        fill_price: float | None = None,
        slippage_pips: float | None = None,
    ) -> None:
        """Update an order's status in the journal, keyed by database ID."""
        async with get_session() as session:
            values: dict = {"status": status.value}
            if fill_price is not None:
                values["fill_price"] = fill_price
                values["filled_at"] = datetime.utcnow()
            if slippage_pips is not None:
                values["slippage_pips"] = slippage_pips
            await session.execute(
                update(OrderRecord).where(OrderRecord.id == order_id).values(**values)
            )
            await session.commit()

        if self._turso:
            await self._turso.push_order_status(
                order_id=order_id,
                status=status.value,
                fill_price=fill_price,
                filled_at=datetime.utcnow() if fill_price is not None else None,
                slippage_pips=slippage_pips,
            )

    async def update_order_status_by_ib_id(
        self,
        ib_order_id: int,
        status: OrderStatus,
        fill_price: float | None = None,
        slippage_pips: float | None = None,
    ) -> int | None:
        """Update an order's status keyed by IB order ID.

        IB order IDs and database IDs are different ID spaces — callers that
        only know the IB order ID (fill events) must use this method, never
        update_order_status. Returns the database ID, or None if unknown.
        """
        async with get_session() as session:
            result = await session.execute(
                select(OrderRecord.id).where(OrderRecord.ib_order_id == ib_order_id)
            )
            db_id = result.scalar_one_or_none()
        if db_id is None:
            logger.warning(
                f"No journal order found for IB order #{ib_order_id} "
                f"(status update to {status.value} dropped)"
            )
            return None
        await self.update_order_status(db_id, status, fill_price, slippage_pips)
        return db_id

    async def update_commission(self, order_id: int, commission: float) -> None:
        """Accumulate commission on an order and its matching trade.

        IB may send multiple commission reports per order (partial fills),
        so we add to any existing value.
        """
        async with get_session() as session:
            # Accumulate on OrderRecord
            result = await session.execute(
                select(OrderRecord).where(OrderRecord.ib_order_id == order_id)
            )
            order_rec = result.scalar_one_or_none()
            if order_rec is not None:
                order_rec.commission = (order_rec.commission or 0.0) + commission
                db_order_id = order_rec.id
            else:
                db_order_id = None
                logger.debug(f"No order found for IB order #{order_id} (commission)")

            # Accumulate on TradeRecord (matched by order_id FK)
            if db_order_id is not None:
                trade_result = await session.execute(
                    select(TradeRecord).where(TradeRecord.order_id == db_order_id)
                )
                trade_rec = trade_result.scalar_one_or_none()
                if trade_rec is not None:
                    trade_rec.commission = (trade_rec.commission or 0.0) + commission

            await session.commit()
            logger.info(f"Commission for IB order #{order_id}: ${commission:.4f}")

        if self._turso and db_order_id is not None:
            total = (order_rec.commission or 0.0) if order_rec else commission
            await self._turso.push_commission(
                order_id=db_order_id, commission=total,
            )

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
                entry_spread_pips=trade.entry_spread_pips,
                event_id=trade.event_id,
                strategy=trade.strategy,
                account_type=self._account_type,
            )
            session.add(record)
            await session.commit()
            logger.info(f"Logged trade #{record.id}: {trade.side} {trade.quantity} {trade.instrument} @ {trade.entry_price} (spread={trade.entry_spread_pips:.1f} pips)" if trade.entry_spread_pips else f"Logged trade #{record.id}: {trade.side} {trade.quantity} {trade.instrument} @ {trade.entry_price}")
            db_id = record.id

        if self._turso:
            await self._turso.push_trade(
                trade_id=db_id,
                order_id=trade.order_id,
                instrument=trade.instrument,
                side=trade.side.value,
                quantity=trade.quantity,
                entry_price=trade.entry_price,
                stop_loss=trade.stop_loss,
                take_profit=trade.take_profit,
                entry_spread_pips=trade.entry_spread_pips,
                event_id=trade.event_id,
                strategy=trade.strategy,
                opened_at=datetime.utcnow(),
            )

        return db_id

    async def update_fill(self, order_id: int, fill_price: float, slippage_pips: float) -> None:
        """Update a trade's fill price and slippage after IB fill."""
        async with get_session() as session:
            result = await session.execute(
                select(TradeRecord).where(TradeRecord.order_id == order_id)
            )
            record = result.scalar_one_or_none()
            if record is None:
                logger.debug(f"No trade found for order #{order_id} (may be bracket child)")
                return
            record.fill_price = fill_price
            record.slippage_pips = slippage_pips
            await session.commit()
            logger.info(
                f"Trade #{record.id} filled at {fill_price} "
                f"(slippage={slippage_pips:+.1f} pips)"
            )

        if self._turso:
            await self._turso.push_trade_fill(
                order_id=order_id,
                fill_price=fill_price,
                slippage_pips=slippage_pips,
            )

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

        if self._turso:
            await self._turso.push_trade_close(
                trade_id=trade_id,
                exit_price=exit_price,
                pnl=pnl,
                pnl_pips=pnl_pips,
                closed_at=datetime.utcnow(),
            )

        if self._notifier or self._anomaly_detector:
            # Fetch the full trade for notification and anomaly checks
            trades = await self.get_trades(limit=100)
            trade = next((t for t in trades if t.id == trade_id), None)
            if trade:
                if self._notifier:
                    daily_pnl = await self.get_daily_pnl()
                    await self._notifier.notify_trade_closed(
                        trade=trade, daily_pnl=daily_pnl,
                    )
                if self._anomaly_detector:
                    await self._anomaly_detector.check_trade(trade)

    async def get_order_by_ib_id(self, ib_order_id: int) -> OrderRecord | None:
        """Fetch an order record by IB order ID (most recent if duplicated)."""
        async with get_session() as session:
            result = await session.execute(
                select(OrderRecord)
                .where(OrderRecord.ib_order_id == ib_order_id)
                .order_by(OrderRecord.id.desc())
            )
            return result.scalars().first()

    async def get_trade_by_order_db_id(self, db_order_id: int) -> Trade | None:
        """Fetch the trade opened for a given order (by database order ID)."""
        async with get_session() as session:
            result = await session.execute(
                select(TradeRecord)
                .where(TradeRecord.order_id == db_order_id)
                .order_by(TradeRecord.id.desc())
            )
            record = result.scalars().first()
        return self._to_model(record) if record else None

    async def open_trade_for_order(self, db_order_id: int) -> int | None:
        """Create the trade record for a filled entry order (idempotent).

        Returns the trade's database ID, or None if the order is unknown or
        has no usable entry price.
        """
        async with get_session() as session:
            existing = await session.execute(
                select(TradeRecord.id).where(TradeRecord.order_id == db_order_id)
            )
            trade_id = existing.scalars().first()
            if trade_id is not None:
                return trade_id
            result = await session.execute(
                select(OrderRecord).where(OrderRecord.id == db_order_id)
            )
            rec = result.scalar_one_or_none()

        if rec is None:
            logger.warning(f"Cannot open trade: no order record #{db_order_id}")
            return None
        entry_price = rec.fill_price or rec.price
        if entry_price is None:
            logger.warning(
                f"Cannot open trade for order #{db_order_id}: no fill or plan price"
            )
            return None

        trade = Trade(
            order_id=db_order_id,
            instrument=rec.instrument,
            side=OrderSide(rec.side),
            quantity=rec.quantity,
            entry_price=entry_price,
            stop_loss=rec.stop_loss,
            take_profit=rec.take_profit,
            entry_spread_pips=rec.entry_spread_pips,
            fill_price=rec.fill_price,
            slippage_pips=rec.slippage_pips,
            event_id=rec.event_id,
            strategy=rec.strategy or "",
        )
        trade_id = await self.log_trade(trade)
        if rec.fill_price is not None:
            await self.update_fill(
                db_order_id, rec.fill_price, rec.slippage_pips or 0.0
            )
        return trade_id

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
        return sum(
            (r.pnl or 0.0) - (r.commission or 0.0)
            for r in records if r.pnl is not None
        )

    # Statuses that represent a live exposure: working at the broker or a
    # filled entry whose position has not been closed yet.
    _OPEN_STATUSES = (
        OrderStatus.PENDING.value,
        OrderStatus.SUBMITTED.value,
        OrderStatus.FILLED.value,
    )

    async def count_open_by_strategy(self, strategy: str) -> int:
        """Count open orders for a specific strategy."""
        async with get_session() as session:
            result = await session.execute(
                select(func.count(OrderRecord.id)).where(
                    OrderRecord.strategy == strategy,
                    OrderRecord.status.in_(self._OPEN_STATUSES),
                )
            )
            return result.scalar_one()

    async def get_open_orders_by_strategy(self, strategy: str) -> list[OrderRecord]:
        """Get all open orders for a specific strategy."""
        async with get_session() as session:
            result = await session.execute(
                select(OrderRecord).where(
                    OrderRecord.strategy == strategy,
                    OrderRecord.status.in_(self._OPEN_STATUSES),
                )
            )
            return list(result.scalars().all())

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
            entry_spread_pips=record.entry_spread_pips,
            fill_price=record.fill_price,
            slippage_pips=record.slippage_pips,
            event_id=record.event_id,
            strategy=record.strategy,
            commission=record.commission,
            opened_at=record.opened_at,
            closed_at=record.closed_at,
        )
