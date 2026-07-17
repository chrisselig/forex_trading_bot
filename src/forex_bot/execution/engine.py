from __future__ import annotations

import math

from loguru import logger

from forex_bot.broker.client import IBClient
from forex_bot.config import get_settings
from forex_bot.broker.exceptions import DataError, OrderError
from forex_bot.broker.orders import OrderService
from forex_bot.broker.contracts import get_pip_size
from forex_bot.broker.pricing import PricingService
from forex_bot.data.trade_journal import TradeJournal
from forex_bot.models.events import EconomicEvent
from forex_bot.models.orders import Order, OrderStatus
from forex_bot.notifications.telegram import TelegramNotifier
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
        notifier: TelegramNotifier | None = None,
    ):
        self._client = client
        self._order_service = OrderService(client)
        self._pricing_service = PricingService(client)
        self._risk_manager = risk_manager
        self._circuit_breaker = circuit_breaker
        self._journal = journal
        self._notifier = notifier
        self._current_event: EconomicEvent | None = None

    def set_current_event(self, event: EconomicEvent | None) -> None:
        """Set the current economic event context for notifications."""
        self._current_event = event

    async def execute_signal(
        self, signal: Signal, event: EconomicEvent | None = None
    ) -> Order | None:
        """Execute a trading signal through full risk validation pipeline."""
        logger.info(f"Processing signal: {signal.side} {signal.instrument} ({signal.strategy})")
        # Never mutate the caller's signal — a retried signal must be re-sized
        # against fresh account/rate data, not carry stale quantities.
        signal = signal.model_copy()
        event = event or self._current_event

        # Get current price for spread check
        try:
            price = await self._pricing_service.get_snapshot(signal.instrument)
        except DataError as e:
            logger.error(f"Failed to get price for {signal.instrument}: {e}")
            return None

        # Quote currency conversion rate for correct position sizing.
        # Fail closed: sizing with a guessed rate can oversize by ~40%.
        try:
            quote_to_cad = await self._pricing_service.get_quote_to_cad_rate(signal.instrument)
        except DataError as e:
            logger.error(
                f"Signal rejected: no quote-to-CAD rate for {signal.instrument}: {e}"
            )
            if self._notifier:
                await self._notifier.notify_signal_rejected(
                    signal.instrument, signal.strategy,
                    [f"No quote-to-CAD rate available: {e}"], event,
                )
            return None
        logger.info(f"Quote-to-CAD rate for {signal.instrument}: {quote_to_cad:.6f}")

        # Calculate position size if not specified
        if signal.quantity == 0 and signal.stop_loss is not None and signal.price is not None:
            pip = get_pip_size(signal.instrument)
            sl_pips = abs(signal.price - signal.stop_loss) / pip
            account = await self._client.get_account_summary()
            try:
                signal.quantity = self._risk_manager.calculate_position_size(
                    account_balance=account.net_liquidation,
                    stop_loss_pips=sl_pips,
                    pair=signal.instrument,
                    quote_to_cad=quote_to_cad,
                )
            except ValueError as e:
                logger.error(f"Signal rejected: {e}")
                return None

        # Margin feasibility cap. Risk-based sizing ignores margin, so exotic
        # pairs can demand orders whose initial margin dwarfs the account
        # (2.5M USDTRY ≈ $1M CAD margin on a $5K account) — IB rejects those
        # with Error 201 at submission. Scale down to fit instead of losing
        # the trade.
        margin_error = await self._apply_margin_cap(signal)
        if margin_error:
            logger.warning(f"Signal rejected by margin cap: {margin_error}")
            if self._notifier:
                await self._notifier.notify_signal_rejected(
                    signal.instrument, signal.strategy, [margin_error], event,
                )
            return None

        # Risk validation (mandatory)
        violations = await self._risk_manager.validate(signal, price, quote_to_cad=quote_to_cad)
        if violations:
            logger.warning(f"Signal rejected by risk manager: {violations}")
            if self._notifier:
                await self._notifier.notify_signal_rejected(
                    signal.instrument, signal.strategy, violations, event,
                )
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
            oca_group=signal.oca_group,
        )

        # Capture spread at submission time for slippage tracking
        pip_size = get_pip_size(signal.instrument)
        entry_spread_pips = price.spread_pips(pip_size)

        # Log order to journal with spread at submission
        order_id = await self._journal.log_order(order, entry_spread_pips=entry_spread_pips)

        # Enforce stop loss at execution boundary (defense in depth)
        if order.stop_loss is None:
            logger.error(f"Order rejected: missing stop loss for {order.instrument}")
            await self._journal.update_order_status(order_id, OrderStatus.REJECTED)
            return None

        # Place with IB
        try:
            if signal.take_profit is not None and signal.price is not None:
                trades = await self._order_service.place_bracket_order(
                    instrument=order.instrument,
                    side=order.side,
                    quantity=order.quantity,
                    entry_price=order.price,
                    take_profit=order.take_profit,
                    stop_loss=order.stop_loss,
                    oca_group=order.oca_group,
                    order_type=order.order_type,
                )
                if trades:
                    order.ib_order_id = trades[0].order.orderId
                    order.status = OrderStatus.SUBMITTED
            else:
                # Market order with attached stop loss
                ib_trade = await self._order_service.place_order_with_stop(order)
                order.ib_order_id = ib_trade.order.orderId
                order.status = OrderStatus.SUBMITTED

            await self._journal.update_order_status(
                order_id, order.status, ib_order_id=order.ib_order_id
            )
            logger.info(f"Order submitted: {order.side} {order.quantity} {order.instrument} (IB#{order.ib_order_id})")

            if self._notifier:
                account = await self._client.get_account_summary()
                await self._notifier.notify_trade_opened(
                    order=order,
                    event=event,
                    account=account,
                    spread_pips=entry_spread_pips,
                )

            return order

        except OrderError as e:
            order.status = OrderStatus.ERROR
            await self._journal.update_order_status(order_id, OrderStatus.ERROR)
            logger.error(f"Order execution failed: {e}")
            if self._notifier:
                await self._notifier.notify_signal_rejected(
                    signal.instrument, signal.strategy,
                    [f"Order execution failed: {e}"], event,
                )
            return None

    # Absorbs margin drift between the whatIf query and execution (price moves,
    # other legs filling) so the scaled order doesn't land exactly at the cap.
    _MARGIN_SAFETY = 0.95

    async def _apply_margin_cap(self, signal: Signal) -> str | None:
        """Scale signal quantity so its initial margin fits available funds.

        Mutates signal.quantity in place when scaling is needed. Returns a
        rejection reason when the order cannot fit at any size, else None.
        whatIf being unavailable is not a rejection — IB's own submission
        check remains the backstop, so a whatIf outage must not turn into
        lost trades.
        """
        max_pct = get_settings().risk.max_margin_pct_per_trade
        margin = await self._order_service.whatif_init_margin(
            instrument=signal.instrument,
            side=signal.side,
            quantity=signal.quantity,
            order_type=signal.order_type,
            price=signal.price,
        )
        if margin is None:
            logger.warning(
                f"whatIf margin unavailable for {signal.instrument} — "
                f"placing at risk-sized quantity {signal.quantity:,.0f}"
            )
            return None
        if margin <= 0:
            return None  # Order reduces or frees margin — no cap needed

        account = await self._client.get_account_summary()
        cap = account.available_funds * max_pct / 100
        if cap <= 0:
            return (
                f"No available funds for margin "
                f"(AvailableFunds={account.available_funds:,.2f} CAD)"
            )
        if margin <= cap:
            return None

        # Margin scales ~linearly with quantity for forex
        scaled = math.floor(signal.quantity * (cap / margin) * self._MARGIN_SAFETY)
        if scaled < 1:
            return (
                f"Cannot fit margin: {signal.quantity:,.0f} units need "
                f"{margin:,.0f} CAD initial margin, cap is {cap:,.0f} CAD "
                f"({max_pct}% of AvailableFunds {account.available_funds:,.2f})"
            )
        logger.warning(
            f"Margin cap: {signal.instrument} {signal.quantity:,.0f} -> "
            f"{scaled:,} units (initial margin {margin:,.0f} CAD exceeds cap "
            f"{cap:,.0f} CAD = {max_pct}% of AvailableFunds "
            f"{account.available_funds:,.2f})"
        )
        signal.quantity = float(scaled)
        return None

    async def execute_signals(
        self, signals: list[Signal], event: EconomicEvent | None = None
    ) -> list[Order]:
        """Execute multiple signals sequentially."""
        orders = []
        for signal in signals:
            order = await self.execute_signal(signal, event=event)
            if order:
                orders.append(order)
        return orders
