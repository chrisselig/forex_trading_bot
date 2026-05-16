from __future__ import annotations

from loguru import logger
from ib_async import IB, MarketOrder, LimitOrder, StopOrder, Trade as IBTrade

from forex_bot.broker.client import IBClient
from forex_bot.broker.contracts import make_forex_contract
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
        self.ib.qualifyContracts(contract)
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
    ) -> list[IBTrade]:
        """Place a bracket order (entry + TP + SL) with IB."""
        await self._client.ensure_connected()
        contract = make_forex_contract(instrument)
        self.ib.qualifyContracts(contract)

        action = side.value
        bracket = self.ib.bracketOrder(
            action=action,
            quantity=quantity,
            limitPrice=entry_price,
            takeProfitPrice=take_profit,
            stopLossPrice=stop_loss,
        )

        logger.info(
            f"Placing bracket {side} {quantity} {instrument} "
            f"entry={entry_price} tp={take_profit} sl={stop_loss}"
        )

        trades = []
        try:
            for o in bracket:
                trade = self.ib.placeOrder(contract, o)
                trades.append(trade)
            return trades
        except Exception as e:
            raise OrderError(f"Failed to place bracket order: {e}") from e

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
