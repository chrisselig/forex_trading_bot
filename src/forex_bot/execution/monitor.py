from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from loguru import logger
from ib_async import Trade as IBTrade

from forex_bot.broker.client import IBClient
from forex_bot.broker.contracts import get_pip_size
from forex_bot.broker.orders import OrderService
from forex_bot.config import get_settings
from forex_bot.data.trade_journal import TradeJournal
from forex_bot.models.orders import OrderStatus, OrderSide
from forex_bot.notifications.telegram import TelegramNotifier
from forex_bot.risk.circuit_breaker import CircuitBreaker


class PositionMonitor:
    """Monitors open positions and order fills in real-time."""

    def __init__(
        self,
        client: IBClient,
        journal: TradeJournal,
        circuit_breaker: CircuitBreaker,
        notifier: TelegramNotifier | None = None,
    ):
        self._client = client
        self._journal = journal
        self._circuit_breaker = circuit_breaker
        self._notifier = notifier
        self._order_service = OrderService(client)
        self._max_holding = get_settings().strategy.max_holding_minutes
        self._tracked_trades: dict[int, datetime] = {}  # order_id -> opened_at
        self._running = False

    def start_monitoring(self) -> None:
        """Subscribe to IB order status events."""
        self._client.ib.orderStatusEvent += self._on_order_status
        self._client.ib.newOrderEvent += self._on_new_order
        self._running = True
        logger.info("Position monitor started")

    def stop_monitoring(self) -> None:
        """Unsubscribe from IB events."""
        self._client.ib.orderStatusEvent -= self._on_order_status
        self._client.ib.newOrderEvent -= self._on_new_order
        self._running = False
        logger.info("Position monitor stopped")

    def _on_order_status(self, trade: IBTrade) -> None:
        """Handle order status updates from IB."""
        status = trade.orderStatus.status
        order_id = trade.order.orderId
        logger.debug(f"Order #{order_id} status: {status}")

        if status == "Filled":
            fill_price = trade.orderStatus.avgFillPrice
            logger.info(f"Order #{order_id} FILLED at {fill_price}")

            # Calculate slippage: fill_price vs planned entry price
            instrument = trade.contract.pair() if hasattr(trade.contract, 'pair') else str(trade.contract.symbol)
            side = OrderSide.BUY if trade.order.action == "BUY" else OrderSide.SELL
            quantity = float(trade.order.totalQuantity)
            planned_price = trade.order.lmtPrice or trade.order.auxPrice or None
            slippage_pips = None
            if planned_price and planned_price > 0:
                pip_size = get_pip_size(instrument)
                raw_slip = (fill_price - planned_price) / pip_size
                # Positive slippage = unfavorable for buys, favorable for sells
                slippage_pips = raw_slip if side == OrderSide.BUY else -raw_slip
                logger.info(
                    f"Order #{order_id} slippage: {slippage_pips:+.1f} pips "
                    f"(planned={planned_price:.5f}, filled={fill_price:.5f})"
                )

            # Persist fill price and slippage to database
            asyncio.get_event_loop().create_task(
                self._journal.update_order_status(
                    order_id, OrderStatus.FILLED,
                    fill_price=fill_price,
                    slippage_pips=slippage_pips,
                )
            )

            if self._notifier:
                asyncio.get_event_loop().create_task(
                    self._notifier.notify_order_filled(order_id, instrument, side, fill_price, quantity)
                )
        elif status == "Cancelled":
            logger.info(f"Order #{order_id} CANCELLED")

    def _on_new_order(self, trade: IBTrade) -> None:
        """Track new orders."""
        order_id = trade.order.orderId
        self._tracked_trades[order_id] = datetime.now(UTC)
        logger.debug(f"Tracking new order #{order_id}")

    async def check_holding_times(self) -> list[int]:
        """Check for positions exceeding max holding time. Returns order IDs to close."""
        now = datetime.now(UTC)
        expired = []
        for order_id, opened_at in list(self._tracked_trades.items()):
            if now - opened_at > timedelta(minutes=self._max_holding):
                expired.append(order_id)
                logger.warning(f"Order #{order_id} exceeded max holding time ({self._max_holding} min)")
        return expired

    async def close_expired_positions(self) -> None:
        """Close positions that have exceeded max holding time."""
        expired = await self.check_holding_times()
        if not expired:
            return

        open_trades = await self._order_service.get_open_trades()
        for trade in open_trades:
            if trade.order.orderId in expired:
                await self._order_service.cancel_order(trade)
                del self._tracked_trades[trade.order.orderId]
                logger.info(f"Closed expired order #{trade.order.orderId}")
