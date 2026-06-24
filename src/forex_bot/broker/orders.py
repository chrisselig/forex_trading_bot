from __future__ import annotations

from loguru import logger
from ib_async import IB, MarketOrder, LimitOrder, StopOrder, Trade as IBTrade

from forex_bot.broker.client import IBClient
from forex_bot.broker.contracts import make_forex_contract, round_to_tick
from forex_bot.broker.exceptions import OrderError
from forex_bot.models.orders import Order, OrderSide, OrderType


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

    async def place_order(self, order: Order) -> IBTrade:
        """Place a single order with IB."""
        await self._client.ensure_connected()
        contract = make_forex_contract(order.instrument)
        await self.ib.qualifyContractsAsync(contract)
        ib_order = self._create_ib_order(order)
        logger.info(f"Placing {order.order_type} {order.side} {order.quantity} {order.instrument}")

        try:
            trade = self.ib.placeOrder(contract, ib_order)
            order.ib_order_id = trade.order.orderId
            return trade
        except Exception as e:
            raise OrderError(f"Failed to place order: {e}") from e

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
        await self.ib.qualifyContractsAsync(contract)

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
            return trades
        except Exception as e:
            raise OrderError(f"Failed to place bracket order: {e}") from e

    async def place_order_with_stop(self, order: Order) -> IBTrade:
        """Place an order with an attached stop loss order."""
        if order.stop_loss is None:
            raise OrderError("Stop loss is required")
        await self._client.ensure_connected()
        contract = make_forex_contract(order.instrument)
        await self.ib.qualifyContractsAsync(contract)

        ib_order = self._create_ib_order(order)
        ib_order.transmit = False  # Hold until child is attached

        reverse_action = "SELL" if order.side == OrderSide.BUY else "BUY"
        sl_order = StopOrder(
            action=reverse_action,
            totalQuantity=order.quantity,
            stopPrice=order.stop_loss,
            parentId=0,  # Will be set after parent is placed
            transmit=True,
        )

        logger.info(
            f"Placing {order.order_type} {order.side} {order.quantity} {order.instrument} "
            f"with SL={order.stop_loss}"
        )

        try:
            parent_trade = self.ib.placeOrder(contract, ib_order)
            sl_order.parentId = parent_trade.order.orderId
            self.ib.placeOrder(contract, sl_order)
            return parent_trade
        except Exception as e:
            raise OrderError(f"Failed to place order with stop: {e}") from e

    async def cancel_order(self, ib_trade: IBTrade) -> None:
        """Cancel an open order."""
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
