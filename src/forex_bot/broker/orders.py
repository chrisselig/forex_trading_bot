from __future__ import annotations

import asyncio
import math

from loguru import logger
from ib_async import IB, MarketOrder, LimitOrder, StopOrder, Trade as IBTrade

from forex_bot.broker.client import IBClient
from forex_bot.broker.contracts import make_forex_contract, round_to_tick
from forex_bot.broker.exceptions import OrderError
from forex_bot.models.orders import Order, OrderSide, OrderType

# Contract qualification should answer in well under a second; a wedged TWS
# otherwise hangs the awaiting event job forever.
_QUALIFY_TIMEOUT_S = 15.0


class OrderService:
    """Handles order placement and management via IB."""

    def __init__(self, client: IBClient):
        self._client = client

    @property
    def ib(self) -> IB:
        return self._client.ib

    def _create_ib_order(self, order: Order):
        """Convert our Order model to an IB order object."""
        quantity = order.quantity
        action = order.side.value

        if order.order_type == OrderType.MARKET:
            return MarketOrder(action=action, totalQuantity=quantity)
        elif order.order_type == OrderType.LIMIT:
            if order.price is None:
                raise OrderError("Limit order requires a price")
            return LimitOrder(action=action, totalQuantity=quantity, lmtPrice=order.price)
        elif order.order_type == OrderType.STOP:
            if order.price is None:
                raise OrderError("Stop order requires a price")
            return StopOrder(action=action, totalQuantity=quantity, stopPrice=order.price)
        else:
            raise OrderError(f"Unsupported order type: {order.order_type}")

    async def _qualify(self, contract) -> None:
        """Qualify a contract with a hard timeout — a wedged TWS otherwise
        hangs the awaiting event job forever."""
        try:
            await asyncio.wait_for(
                self.ib.qualifyContractsAsync(contract), _QUALIFY_TIMEOUT_S
            )
        except TimeoutError as e:
            raise OrderError(f"Timed out qualifying contract {contract}") from e

    async def _verify_submission(
        self, trades: list[IBTrade], wait_s: float = 3.0
    ) -> None:
        """Verify IB accepted the just-placed orders.

        placeOrder() is non-blocking: rejections (tick size, margin,
        permissions) arrive asynchronously as Inactive/Cancelled status.
        Without this check a rejected SL child would go unnoticed and the
        entry could later fill with no protective stop.
        """
        ok_states = {"PreSubmitted", "Submitted", "Filled", "PendingSubmit"}
        deadline = asyncio.get_running_loop().time() + wait_s
        while True:
            rejected = [
                t for t in trades
                if t.orderStatus.status in ("Inactive", "Cancelled", "ApiCancelled")
            ]
            if rejected:
                details = "; ".join(
                    f"#{t.order.orderId} {t.orderStatus.status} "
                    + " | ".join(entry.message for entry in t.log if entry.message)
                    for t in rejected
                )
                raise OrderError(f"IB rejected order(s) after placement: {details}")
            settled = all(
                t.orderStatus.status in ("PreSubmitted", "Submitted", "Filled")
                for t in trades
            )
            if settled:
                return
            if asyncio.get_running_loop().time() >= deadline:
                pending = [
                    t.order.orderId
                    for t in trades
                    if t.orderStatus.status not in ok_states
                ]
                if pending:
                    logger.warning(
                        f"Orders {pending} not confirmed by IB within {wait_s:.0f}s "
                        f"— monitor for async rejection"
                    )
                return
            await asyncio.sleep(0.25)

    async def place_order(self, order: Order) -> IBTrade:
        """Place a single order with IB."""
        await self._client.ensure_connected()
        contract = make_forex_contract(order.instrument)
        await self._qualify(contract)
        ib_order = self._create_ib_order(order)
        logger.info(f"Placing {order.order_type} {order.side} {order.quantity} {order.instrument}")

        try:
            trade = self.ib.placeOrder(contract, ib_order)
            order.ib_order_id = trade.order.orderId
        except Exception as e:
            raise OrderError(f"Failed to place order: {e}") from e
        await self._verify_submission([trade])
        return trade

    async def whatif_init_margin(
        self,
        instrument: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        price: float | None = None,
    ) -> float | None:
        """Ask IB what initial margin a hypothetical order would require.

        Uses the whatIf order facility — nothing is placed. Returns the
        initial margin change in account currency (CAD), or None when the
        answer is unavailable (timeout, unparseable response, IB's
        Double.MAX_VALUE "unknown" sentinel). Callers must treat None as
        "unknown", never as zero.
        """
        await self._client.ensure_connected()
        contract = make_forex_contract(instrument)
        await self._qualify(contract)

        action = side.value
        if order_type == OrderType.STOP and price is not None:
            ib_order = StopOrder(
                action=action, totalQuantity=quantity,
                stopPrice=round_to_tick(price, instrument),
            )
        elif order_type == OrderType.LIMIT and price is not None:
            ib_order = LimitOrder(
                action=action, totalQuantity=quantity,
                lmtPrice=round_to_tick(price, instrument),
            )
        else:
            ib_order = MarketOrder(action=action, totalQuantity=quantity)

        try:
            state = await asyncio.wait_for(
                self.ib.whatIfOrderAsync(contract, ib_order), _QUALIFY_TIMEOUT_S
            )
            margin = float(state.initMarginChange)
        except (TimeoutError, ValueError, TypeError, ConnectionError, OSError) as e:
            logger.warning(f"whatIf margin query failed for {instrument}: {e}")
            return None
        # IB reports "unknown" as Double.MAX_VALUE (~1.8e308)
        if not math.isfinite(margin) or margin >= 1e300:
            logger.warning(f"whatIf margin for {instrument} unavailable (got {margin})")
            return None
        return margin

    async def place_bracket_order(
        self,
        instrument: str,
        side: OrderSide,
        quantity: float,
        entry_price: float,
        take_profit: float,
        stop_loss: float,
        oca_group: str = "",
        order_type: OrderType = OrderType.STOP,
    ) -> list[IBTrade]:
        """Place a bracket order (entry + TP + SL) with IB.

        The entry order type is determined by order_type:
        - STOP (default): StopOrder entry — triggers when price reaches the level.
          Used for straddles where we want breakout entries.
        - LIMIT: LimitOrder entry — fills at the price or better.

        If oca_group is set, the parent entry order joins an OCA group so
        that when one straddle leg fills, IB cancels the other leg's entry.
        OCA type 1 = cancel remaining orders on first fill.
        """
        await self._client.ensure_connected()
        contract = make_forex_contract(instrument)
        await self._qualify(contract)

        # Round all prices to IB's minimum tick size
        entry_price = round_to_tick(entry_price, instrument)
        take_profit = round_to_tick(take_profit, instrument)
        stop_loss = round_to_tick(stop_loss, instrument)

        action = side.value
        reverse_action = "SELL" if action == "BUY" else "BUY"

        # Build parent entry order (stop or limit based on order_type)
        if order_type == OrderType.STOP:
            parent = StopOrder(
                action=action,
                totalQuantity=quantity,
                stopPrice=entry_price,
                orderId=self.ib.client.getReqId(),
                transmit=False,
                tif="GTC",
            )
        else:
            parent = LimitOrder(
                action=action,
                totalQuantity=quantity,
                lmtPrice=entry_price,
                orderId=self.ib.client.getReqId(),
                transmit=False,
                tif="GTC",
            )

        # Take-profit child (limit)
        tp_order = LimitOrder(
            action=reverse_action,
            totalQuantity=quantity,
            lmtPrice=take_profit,
            orderId=self.ib.client.getReqId(),
            transmit=False,
            parentId=parent.orderId,
            tif="GTC",
        )

        # Stop-loss child (stop)
        sl_order = StopOrder(
            action=reverse_action,
            totalQuantity=quantity,
            stopPrice=stop_loss,
            orderId=self.ib.client.getReqId(),
            transmit=True,
            parentId=parent.orderId,
            tif="GTC",
        )

        # Set OCA group on the parent (entry) order only.
        # TP and SL are children — they auto-cancel when the parent is cancelled.
        if oca_group:
            parent.ocaGroup = oca_group
            parent.ocaType = 1  # Cancel all remaining on fill

        entry_type = "STP" if order_type == OrderType.STOP else "LMT"
        logger.info(
            f"Placing bracket {side} {quantity} {instrument} "
            f"entry({entry_type})={entry_price} tp={take_profit} sl={stop_loss}"
            f"{f' OCA={oca_group}' if oca_group else ''}"
        )

        trades = []
        try:
            for o in (parent, tp_order, sl_order):
                trade = self.ib.placeOrder(contract, o)
                trades.append(trade)
        except Exception as e:
            raise OrderError(f"Failed to place bracket order: {e}") from e
        await self._verify_submission(trades)
        return trades

    async def place_order_with_stop(self, order: Order) -> IBTrade:
        """Place an order with an attached stop loss (and optional take profit).

        Transmit chain: parent (transmit=False) -> optional TP child
        (transmit=False) -> SL child (transmit=True). IB holds the whole
        group until the SL is delivered, so a mid-sequence failure cannot
        leave an active entry without its stop. Children of the same parent
        are OCA'd by IB automatically.
        """
        if order.stop_loss is None:
            raise OrderError("Stop loss is required")
        await self._client.ensure_connected()
        contract = make_forex_contract(order.instrument)
        await self._qualify(contract)

        ib_order = self._create_ib_order(order)
        ib_order.transmit = False  # Hold until children are attached
        ib_order.tif = "GTC"

        # Round child prices to IB's minimum tick size
        sl_price = round_to_tick(order.stop_loss, order.instrument)

        reverse_action = "SELL" if order.side == OrderSide.BUY else "BUY"
        children = []
        if order.take_profit is not None:
            # Previously a TP on a non-bracket order was silently dropped
            tp_price = round_to_tick(order.take_profit, order.instrument)
            children.append(
                LimitOrder(
                    action=reverse_action,
                    totalQuantity=order.quantity,
                    lmtPrice=tp_price,
                    parentId=0,  # Set after parent is placed
                    transmit=False,
                    tif="GTC",
                )
            )
        children.append(
            StopOrder(
                action=reverse_action,
                totalQuantity=order.quantity,
                stopPrice=sl_price,
                parentId=0,  # Set after parent is placed
                transmit=True,  # Last in chain transmits the whole group
                tif="GTC",
            )
        )

        logger.info(
            f"Placing {order.order_type} {order.side} {order.quantity} {order.instrument} "
            f"with SL={order.stop_loss}"
            + (f" TP={order.take_profit}" if order.take_profit is not None else "")
        )

        try:
            parent_trade = self.ib.placeOrder(contract, ib_order)
            order.ib_order_id = parent_trade.order.orderId
            trades = [parent_trade]
            for child in children:
                child.parentId = parent_trade.order.orderId
                trades.append(self.ib.placeOrder(contract, child))
        except Exception as e:
            raise OrderError(f"Failed to place order with stop: {e}") from e
        await self._verify_submission(trades)
        return parent_trade

    async def cancel_order(self, ib_trade: IBTrade) -> None:
        """Cancel an open order."""
        await self._client.ensure_connected()
        logger.info(f"Cancelling order {ib_trade.order.orderId}")
        self.ib.cancelOrder(ib_trade.order)

    async def cancel_all_orders(self) -> None:
        """Cancel all open orders."""
        await self._client.ensure_connected()
        self.ib.reqGlobalCancel()
        logger.warning("Cancelled all open orders")

    async def get_open_trades(self) -> list[IBTrade]:
        """Get all open trades from IB."""
        return self.ib.openTrades()
