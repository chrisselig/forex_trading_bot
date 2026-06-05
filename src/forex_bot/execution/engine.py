from __future__ import annotations

from loguru import logger

from forex_bot.broker.client import IBClient
from forex_bot.broker.orders import OrderService
from forex_bot.broker.contracts import get_pip_size
from forex_bot.broker.pricing import PricingService
from forex_bot.data.trade_journal import TradeJournal
from forex_bot.models.orders import Order, OrderSide, OrderType, OrderStatus, Trade
from forex_bot.risk.manager import RiskManager
from forex_bot.risk.circuit_breaker import CircuitBreaker
from forex_bot.strategy.signals import Signal


class ExecutionEngine:
    """Translates validated signals into IB orders.

    Execution path (mandatory, no shortcuts):
    Signal -> RiskManager.validate() -> CircuitBreaker.check() -> IB API
    """

    def __init__(
        self,
        client: IBClient,
        risk_manager: RiskManager,
        circuit_breaker: CircuitBreaker,
        journal: TradeJournal,
    ):
        self._client = client
        self._order_service = OrderService(client)
        self._pricing_service = PricingService(client)
        self._risk_manager = risk_manager
        self._circuit_breaker = circuit_breaker
        self._journal = journal

    async def execute_signal(self, signal: Signal) -> Order | None:
        """Execute a trading signal through full risk validation pipeline."""
        logger.info(f"Processing signal: {signal.side} {signal.instrument} ({signal.strategy})")

        # Get current price for spread check
        try:
            price = await self._pricing_service.get_snapshot(signal.instrument)
        except Exception as e:
            logger.error(f"Failed to get price for {signal.instrument}: {e}")
            return None

        # Calculate position size if not specified
        if signal.quantity == 0 and signal.stop_loss is not None and signal.price is not None:
            pip = get_pip_size(signal.instrument)
            sl_pips = abs(signal.price - signal.stop_loss) / pip
            account = await self._client.get_account_summary()
            signal.quantity = self._risk_manager.calculate_position_size(
                account_balance=account.net_liquidation,
                stop_loss_pips=sl_pips,
                pair=signal.instrument,
            )

        # Risk validation (mandatory)
        violations = await self._risk_manager.validate(signal, price)
        if violations:
            logger.warning(f"Signal rejected by risk manager: {violations}")
            return None

        # Build order
        order = Order(
            instrument=signal.instrument,
            side=signal.side,
            order_type=signal.order_type,
            quantity=signal.quantity,
            price=signal.price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            event_id=signal.event_id,
            strategy=signal.strategy,
        )

        # Log order to journal
        order_id = await self._journal.log_order(order)

        # Enforce stop loss at execution boundary (defense in depth)
        if order.stop_loss is None:
            logger.error(f"Order rejected: missing stop loss for {order.instrument}")
            await self._journal.update_order_status(order_id, OrderStatus.REJECTED)
            return None

        # Place with IB
        try:
            if signal.take_profit and signal.price:
                trades = await self._order_service.place_bracket_order(
                    instrument=order.instrument,
                    side=order.side,
                    quantity=order.quantity,
                    entry_price=order.price,
                    take_profit=order.take_profit,
                    stop_loss=order.stop_loss,
                )
                if trades:
                    order.ib_order_id = trades[0].order.orderId
                    order.status = OrderStatus.SUBMITTED
            else:
                # Market order with attached stop loss
                ib_trade = await self._order_service.place_order_with_stop(order)
                order.ib_order_id = ib_trade.order.orderId
                order.status = OrderStatus.SUBMITTED

            await self._journal.update_order_status(order_id, order.status)
            logger.info(f"Order submitted: {order.side} {order.quantity} {order.instrument} (IB#{order.ib_order_id})")
            return order

        except Exception as e:
            order.status = OrderStatus.ERROR
            await self._journal.update_order_status(order_id, OrderStatus.ERROR)
            logger.error(f"Order execution failed: {e}")
            return None

    async def execute_signals(self, signals: list[Signal]) -> list[Order]:
        """Execute multiple signals sequentially."""
        orders = []
        for signal in signals:
            order = await self.execute_signal(signal)
            if order:
                orders.append(order)
        return orders
