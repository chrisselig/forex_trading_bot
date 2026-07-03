from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta

from loguru import logger
from ib_async import Trade as IBTrade

from forex_bot.broker.client import IBClient
from forex_bot.broker.contracts import get_pip_size
from forex_bot.broker.exceptions import DataError, ForexBotError, OrderError
from forex_bot.broker.orders import OrderService
from forex_bot.broker.pricing import PricingService
from forex_bot.config import get_settings
from forex_bot.data.trade_journal import TradeJournal
from forex_bot.models.orders import Order, OrderSide, OrderStatus, OrderType
from forex_bot.notifications.telegram import TelegramNotifier
from forex_bot.risk.circuit_breaker import CircuitBreaker

# ib_async leaves unset float fields at this sentinel (sys.float_info.max).
# No forex pair trades anywhere near this level, so anything implausibly
# large is "unset", not a real planned price.
_MAX_PLAUSIBLE_PRICE = 1e6

# How long to wait for a flatten (market) order to fill before alerting.
_FLATTEN_FILL_TIMEOUT_S = 30.0


def _planned_price(ib_order) -> float | None:
    """Extract the intended entry price from an IB order, if any.

    Market orders have no planned price; unset lmtPrice/auxPrice arrive as
    a huge float sentinel, never None.
    """
    for value in (ib_order.lmtPrice, ib_order.auxPrice):
        if value and 0 < value < _MAX_PLAUSIBLE_PRICE:
            return float(value)
    return None


class PositionMonitor:
    """Monitors order fills in real time and closes the trade lifecycle loop.

    Responsibilities:
    - Entry fill (parentless order we journaled): record fill + open a trade.
    - Exit fill (TP/SL bracket child): close the trade, compute P&L, and feed
      the circuit breaker — this is the loss-based kill switch input.
    - Holding-time enforcement: flatten positions past max_holding_minutes.
    """

    def __init__(
        self,
        client: IBClient,
        journal: TradeJournal,
        circuit_breaker: CircuitBreaker,
        notifier: TelegramNotifier | None = None,
        pricing: PricingService | None = None,
    ):
        self._client = client
        self._journal = journal
        self._circuit_breaker = circuit_breaker
        self._notifier = notifier
        self._order_service = OrderService(client)
        self._pricing = pricing or PricingService(client)
        self._max_holding = get_settings().strategy.max_holding_minutes
        self._tracked_trades: dict[int, datetime] = {}  # ib order id -> tracked since
        self._excluded_order_ids: set[int] = set()
        self._bg_tasks: set[asyncio.Task] = set()
        self._running = False

    def exclude_from_holding_check(self, order_ids: set[int]) -> None:
        """Exclude order IDs from holding time checks (e.g., carry positions)."""
        self._excluded_order_ids |= order_ids
        if order_ids:
            logger.debug(f"Excluded {len(order_ids)} order(s) from holding checks")

    def start_monitoring(self) -> None:
        """Subscribe to IB order status events."""
        self._client.ib.orderStatusEvent += self._on_order_status
        self._client.ib.newOrderEvent += self._on_new_order
        self._client.ib.commissionReportEvent += self._on_commission_report
        self._running = True
        logger.info("Position monitor started")

    def stop_monitoring(self) -> None:
        """Unsubscribe from IB events."""
        self._client.ib.orderStatusEvent -= self._on_order_status
        self._client.ib.newOrderEvent -= self._on_new_order
        self._client.ib.commissionReportEvent -= self._on_commission_report
        self._running = False
        logger.info("Position monitor stopped")

    def _spawn(self, coro: Coroutine) -> None:
        """Run a coroutine in the background without losing its exceptions.

        A bare create_task can be garbage-collected mid-flight and swallows
        exceptions — every fire-and-forget here must go through this helper.
        """
        task = asyncio.get_event_loop().create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task) -> None:
        self._bg_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.opt(exception=task.exception()).error(
                "Position monitor background task failed"
            )

    def _on_order_status(self, trade: IBTrade) -> None:
        """Handle order status updates from IB (sync callback)."""
        status = trade.orderStatus.status
        order_id = trade.order.orderId
        parent_id = trade.order.parentId
        logger.debug(f"Order #{order_id} status: {status}")

        if status == "Filled":
            fill_price = trade.orderStatus.avgFillPrice
            logger.info(f"Order #{order_id} FILLED at {fill_price}")
            instrument = (
                trade.contract.pair()
                if hasattr(trade.contract, "pair")
                else str(trade.contract.symbol)
            )
            side = OrderSide.BUY if trade.order.action == "BUY" else OrderSide.SELL
            quantity = float(trade.order.totalQuantity)

            slippage_pips = None
            planned_price = _planned_price(trade.order)
            if planned_price is not None:
                pip_size = get_pip_size(instrument)
                raw_slip = (fill_price - planned_price) / pip_size
                # Positive slippage = unfavorable for buys, favorable for sells
                slippage_pips = raw_slip if side == OrderSide.BUY else -raw_slip
                logger.info(
                    f"Order #{order_id} slippage: {slippage_pips:+.1f} pips "
                    f"(planned={planned_price:.5f}, filled={fill_price:.5f})"
                )

            if parent_id:
                # Bracket child (TP or SL) filled -> the parent's position closed
                self._spawn(self._handle_exit_fill(parent_id, fill_price))
            else:
                self._spawn(
                    self._handle_entry_fill(order_id, fill_price, slippage_pips)
                )

            if self._notifier:
                self._spawn(
                    self._notifier.notify_order_filled(
                        order_id, instrument, side, fill_price, quantity
                    )
                )
        elif status in ("Cancelled", "ApiCancelled"):
            logger.info(f"Order #{order_id} CANCELLED")
            self._tracked_trades.pop(order_id, None)
            if not parent_id:
                self._spawn(
                    self._journal.update_order_status_by_ib_id(
                        order_id, OrderStatus.CANCELLED
                    )
                )
        elif status == "Inactive":
            # IB parks rejected orders as Inactive (margin, price, permissions).
            if parent_id:
                logger.critical(
                    f"Bracket child #{order_id} (parent #{parent_id}) went "
                    f"INACTIVE — the position may be missing its TP/SL. "
                    f"Inspect TWS immediately."
                )
            else:
                logger.error(f"Order #{order_id} went INACTIVE (likely rejected)")
                self._spawn(
                    self._journal.update_order_status_by_ib_id(
                        order_id, OrderStatus.REJECTED
                    )
                )

    async def _handle_entry_fill(
        self, ib_order_id: int, fill_price: float, slippage_pips: float | None
    ) -> None:
        """Persist an entry fill and open its trade record."""
        db_id = await self._journal.update_order_status_by_ib_id(
            ib_order_id, OrderStatus.FILLED,
            fill_price=fill_price,
            slippage_pips=slippage_pips,
        )
        if db_id is None:
            return  # not an order we placed (e.g. manual TWS order)
        await self._journal.open_trade_for_order(db_id)
        # Holding time counts from the fill, not from placement
        self._tracked_trades[ib_order_id] = datetime.now(UTC)

    async def _handle_exit_fill(self, parent_ib_id: int, exit_price: float) -> None:
        """Close the trade whose entry order was parent_ib_id and feed the breaker."""
        order_rec = await self._journal.get_order_by_ib_id(parent_ib_id)
        if order_rec is None:
            logger.debug(f"Exit fill for unknown parent IB order #{parent_ib_id}")
            return

        trade = await self._journal.get_trade_by_order_db_id(order_rec.id)
        if trade is None:
            # Entry fill event may have been missed (e.g. bot restart between
            # fill and event delivery) — reconstruct the trade, then close it.
            logger.warning(
                f"Exit fill for IB order #{parent_ib_id} with no trade record — "
                f"reconstructing entry retroactively"
            )
            await self._journal.open_trade_for_order(order_rec.id)
            trade = await self._journal.get_trade_by_order_db_id(order_rec.id)
            if trade is None:
                logger.error(
                    f"Cannot close trade for IB order #{parent_ib_id}: "
                    f"no entry price on record"
                )
                return
        if trade.closed_at is not None:
            return  # already closed (duplicate event)

        pip_size = get_pip_size(order_rec.instrument)
        entry_price = trade.fill_price or trade.entry_price
        diff = (
            exit_price - entry_price
            if trade.side == OrderSide.BUY
            else entry_price - exit_price
        )
        pnl_pips = diff / pip_size
        pnl_quote = diff * trade.quantity
        try:
            rate = await self._pricing.get_quote_to_cad_rate(order_rec.instrument)
        except DataError as e:
            logger.error(
                f"No quote-to-CAD rate for {order_rec.instrument}; recording "
                f"P&L in quote currency (rate=1.0): {e}"
            )
            rate = 1.0
        pnl_cad = pnl_quote * rate

        await self._journal.close_trade(trade.id, exit_price, pnl_cad, pnl_pips)
        await self._journal.update_order_status(order_rec.id, OrderStatus.CLOSED)
        self._tracked_trades.pop(parent_ib_id, None)

        # Feed the circuit breaker — this is the loss-based kill switch.
        balance = 0.0
        try:
            account = await self._client.get_account_summary()
            balance = account.net_liquidation
        except ForexBotError as e:
            logger.error(f"Account summary unavailable for circuit breaker: {e}")
        self._circuit_breaker.record_trade_result(pnl_cad, balance)

    def _on_commission_report(self, trade: IBTrade, fill, report) -> None:
        """Handle commission reports from IB (arrives after fills)."""
        order_id = trade.order.orderId
        commission = report.commission
        # IB sends 1e10 (MAX_DOUBLE) when commission is not yet known
        if commission is None or commission >= 1e9:
            return
        logger.info(f"Order #{order_id} commission: ${commission:.4f} {report.currency}")
        self._spawn(self._journal.update_commission(order_id, commission))

    def _on_new_order(self, trade: IBTrade) -> None:
        """Track new parent (entry) orders. Bracket children are not positions."""
        if trade.order.parentId:
            return
        order_id = trade.order.orderId
        self._tracked_trades[order_id] = datetime.now(UTC)
        logger.debug(f"Tracking new order #{order_id}")

    async def check_holding_times(self) -> list[int]:
        """Check for positions exceeding max holding time. Returns IB order IDs."""
        now = datetime.now(UTC)
        expired = []
        for order_id, tracked_since in list(self._tracked_trades.items()):
            if order_id in self._excluded_order_ids:
                continue
            if now - tracked_since > timedelta(minutes=self._max_holding):
                expired.append(order_id)
                logger.warning(
                    f"Order #{order_id} exceeded max holding time "
                    f"({self._max_holding} min)"
                )
        return expired

    async def close_expired_positions(self) -> None:
        """Flatten positions (and cancel stale entries) past max holding time."""
        expired = await self.check_holding_times()
        if not expired:
            return

        open_trades = await self._order_service.get_open_trades()
        open_by_id = {t.order.orderId: t for t in open_trades}
        for ib_id in expired:
            try:
                await self._close_expired(ib_id, open_by_id, open_trades)
            except (OrderError, DataError) as e:
                logger.error(f"Failed to close expired order #{ib_id}: {e}")

    async def _close_expired(
        self,
        ib_id: int,
        open_by_id: dict[int, IBTrade],
        open_trades: list[IBTrade],
    ) -> None:
        entry_trade = open_by_id.get(ib_id)
        if entry_trade is not None:
            # Entry order still working at IB (never filled) — cancel it.
            # Bracket children are cancelled by IB along with their parent.
            await self._order_service.cancel_order(entry_trade)
            self._tracked_trades.pop(ib_id, None)
            logger.info(f"Cancelled stale unfilled entry order #{ib_id}")
            return

        order_rec = await self._journal.get_order_by_ib_id(ib_id)
        if order_rec is None or order_rec.status != OrderStatus.FILLED.value:
            # Not a live position we know about — stop tracking it.
            self._tracked_trades.pop(ib_id, None)
            return

        # Live position: cancel its protective children, then flatten
        # immediately with a market order. The unprotected window is the
        # seconds between these two steps; failure to flatten is alerted
        # loudly and retried on the next monitoring cycle.
        for t in open_trades:
            if t.order.parentId == ib_id:
                await self._order_service.cancel_order(t)

        flatten_side = (
            OrderSide.SELL if order_rec.side == OrderSide.BUY.value else OrderSide.BUY
        )
        flatten = Order(
            instrument=order_rec.instrument,
            side=flatten_side,
            order_type=OrderType.MARKET,
            quantity=order_rec.quantity,
            strategy=order_rec.strategy or "",
        )
        logger.warning(
            f"Flattening expired position: {flatten_side} {order_rec.quantity} "
            f"{order_rec.instrument} (entry IB #{ib_id})"
        )
        ib_trade = await self._order_service.place_order(flatten)
        fill_price = await self._await_fill(ib_trade, _FLATTEN_FILL_TIMEOUT_S)
        if fill_price is None:
            logger.critical(
                f"Flatten order for {order_rec.instrument} (entry IB #{ib_id}) "
                f"did not fill within {_FLATTEN_FILL_TIMEOUT_S:.0f}s and its "
                f"protective orders were cancelled — POSITION MAY BE "
                f"UNPROTECTED. Will retry next cycle."
            )
            return  # stays tracked -> retried next monitoring cycle

        await self._handle_exit_fill(ib_id, fill_price)
        self._tracked_trades.pop(ib_id, None)
        logger.info(f"Closed expired position for entry IB #{ib_id} at {fill_price}")

    async def _await_fill(self, ib_trade: IBTrade, timeout: float) -> float | None:
        """Poll an order until filled; return avg fill price or None on timeout."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if ib_trade.orderStatus.status == "Filled":
                return ib_trade.orderStatus.avgFillPrice
            await asyncio.sleep(0.25)
        return None
