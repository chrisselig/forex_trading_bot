from __future__ import annotations

from datetime import UTC, datetime

from loguru import logger
from pydantic import BaseModel

from forex_bot.broker.client import IBClient
from forex_bot.broker.contracts import get_pip_size
from forex_bot.broker.exceptions import DataError, ForexBotError
from forex_bot.broker.orders import OrderService
from forex_bot.broker.pricing import PricingService
from forex_bot.config import get_settings
from forex_bot.data.trade_journal import TradeJournal
from forex_bot.execution.engine import ExecutionEngine
from forex_bot.execution.monitor import PositionMonitor
from forex_bot.models.orders import Order, OrderSide, OrderType
from forex_bot.notifications.telegram import TelegramNotifier
from forex_bot.strategy.signals import Signal


class MomentumScore(BaseModel):
    """Score for a single pair based on its trailing return."""

    pair: str
    trailing_return_pct: float  # signed return over the lookback window
    direction: OrderSide  # BUY if return > 0 (uptrend), SELL if < 0 (downtrend)
    lookback_months: int


class MomentumPosition(BaseModel):
    """Tracked momentum position."""

    pair: str
    side: OrderSide
    entry_price: float
    quantity: float
    stop_loss: float
    ib_order_id: int
    opened_at: datetime


class MomentumManager:
    """Schedule-driven time-series (absolute) momentum manager.

    For each pair in the basket it measures the trailing return over a
    configurable lookback window and trades the pair in the direction of that
    trend — long recent winners, short recent losers. Produces Signal objects
    and feeds them through the existing ExecutionEngine, preserving the
    mandatory risk pipeline.

    UNVALIDATED: no Monte Carlo walk-forward backs this yet. Disabled by
    default; enable only for paper-trade evaluation.
    """

    def __init__(
        self,
        client: IBClient,
        execution_engine: ExecutionEngine,
        journal: TradeJournal,
        pricing: PricingService,
        monitor: PositionMonitor,
        notifier: TelegramNotifier | None = None,
    ):
        self._client = client
        self._engine = execution_engine
        self._journal = journal
        self._pricing = pricing
        self._monitor = monitor
        self._notifier = notifier
        self._settings = get_settings().momentum
        self._positions: dict[str, MomentumPosition] = {}  # pair -> position

    async def restore_state(self) -> None:
        """Rebuild momentum positions from database on startup.

        Only orders with a real IB order ID and entry price are restored —
        fabricating placeholders (ib_order_id=0 matches every parentless IB
        order) would make later close/cancel logic dangerous.
        """
        orders = await self._journal.get_open_orders_by_strategy("momentum")
        for order in orders:
            entry_price = order.fill_price or order.price
            if not order.ib_order_id or entry_price is None:
                logger.warning(
                    f"Momentum: cannot restore {order.instrument} position from "
                    f"order #{order.id} (ib_order_id={order.ib_order_id}, "
                    f"price={entry_price}) — manage it manually in TWS"
                )
                continue
            self._positions[order.instrument] = MomentumPosition(
                pair=order.instrument,
                side=OrderSide(order.side),
                entry_price=entry_price,
                quantity=order.quantity,
                stop_loss=order.stop_loss or 0.0,
                ib_order_id=order.ib_order_id,
                opened_at=order.created_at,
            )
        if self._positions:
            logger.info(
                f"Restored {len(self._positions)} momentum position(s): {list(self._positions.keys())}"
            )

    def get_momentum_order_ids(self) -> set[int]:
        """Return IB order IDs for all active momentum positions."""
        return {p.ib_order_id for p in self._positions.values() if p.ib_order_id}

    def get_active_currencies(self) -> set[str]:
        """Return currencies held by momentum positions (for sweep exclusion)."""
        currencies: set[str] = set()
        for pair in self._positions:
            currencies.add(pair[:3])
            currencies.add(pair[3:])
        currencies.discard("CAD")  # Never exclude account currency
        return currencies

    async def rebalance(self) -> None:
        """Weekly rebalance entry point.

        1. Fetch trailing returns
        2. Score pairs by momentum, filter by threshold
        3. Close positions no longer in target set or with flipped direction
        4. Enter new positions
        """
        if not self._settings.enabled:
            logger.debug("Momentum strategy disabled, skipping rebalance")
            return

        if not self._client.is_connected:
            logger.warning("Momentum rebalance skipped: IB not connected")
            return

        logger.info("Starting momentum rebalance")

        returns = await self._fetch_returns()
        if not returns:
            logger.error("Momentum rebalance aborted: no trailing returns available")
            return

        scores = self._calculate_scores(returns)
        target_pairs = {s.pair for s in scores}
        target_directions = {s.pair: s.direction for s in scores}

        logger.info(
            f"Momentum targets: {[f'{s.pair} {s.direction} (ret={s.trailing_return_pct:+.1f}%)' for s in scores]}"
        )

        # Close positions no longer in target set or with flipped direction
        closed = []
        for pair in list(self._positions):
            pos = self._positions[pair]
            if pair not in target_pairs or target_directions.get(pair) != pos.side:
                reason = "direction flipped" if pair in target_pairs else "removed from target"
                await self._close_position(pair, pos, reason)
                closed.append(pair)

        # Enter new positions
        entered = []
        num_targets = len(scores)
        for score in scores:
            if score.pair in self._positions:
                logger.debug(f"Momentum: holding existing {score.pair} position")
                continue

            try:
                price = await self._pricing.get_snapshot(score.pair)
                account = await self._client.get_account_summary()
                quote_to_cad = await self._pricing.get_quote_to_cad_rate(score.pair)
                signal = self._build_entry_signal(
                    score, price.mid, account.net_liquidation, num_targets,
                    quote_to_cad=quote_to_cad,
                )

                order = await self._engine.execute_signal(signal)
                if order and order.ib_order_id:
                    self._positions[score.pair] = MomentumPosition(
                        pair=score.pair,
                        side=score.direction,
                        entry_price=price.mid,
                        quantity=signal.quantity,
                        stop_loss=signal.stop_loss or 0.0,
                        ib_order_id=order.ib_order_id,
                        opened_at=datetime.now(UTC),
                    )
                    self._monitor.exclude_from_holding_check({order.ib_order_id})
                    entered.append(score.pair)
                    logger.info(
                        f"Momentum: entered {score.direction} {score.pair} "
                        f"(ret={score.trailing_return_pct:+.1f}%)"
                    )
            except (ForexBotError, ValueError) as e:
                logger.error(f"Momentum: failed to enter {score.pair}: {e}")

        await self._send_rebalance_summary(scores, entered, closed)

    async def _fetch_returns(self) -> dict[str, float]:
        """Fetch the trailing return (percent) for each instrument.

        Uses daily MIDPOINT bars over the lookback window. A pair whose data
        cannot be fetched is skipped rather than aborting the whole rebalance.
        """
        returns: dict[str, float] = {}
        duration = f"{self._settings.lookback_months} M"

        for pair in self._settings.instruments:
            try:
                bars = await self._pricing.get_historical_bars(
                    pair, duration=duration, bar_size="1 day", what_to_show="MIDPOINT",
                )
            except DataError as e:
                logger.warning(f"Momentum: no historical data for {pair}: {e}")
                continue

            if len(bars) < 2 or bars[0].close <= 0:
                logger.warning(f"Momentum: insufficient/invalid bars for {pair} ({len(bars)})")
                continue

            trailing_return = (bars[-1].close / bars[0].close - 1) * 100
            returns[pair] = trailing_return

        return returns

    def _calculate_scores(self, returns: dict[str, float]) -> list[MomentumScore]:
        """Score each pair by trailing return, filter by threshold, rank, cap."""
        scores: list[MomentumScore] = []
        threshold = self._settings.min_return_pct

        for pair, ret in returns.items():
            if abs(ret) < threshold:
                logger.debug(
                    f"Momentum: {pair} return={ret:+.1f}% below threshold {threshold}%"
                )
                continue

            # Positive return → uptrend → BUY (long the winner)
            # Negative return → downtrend → SELL (short the loser)
            direction = OrderSide.BUY if ret > 0 else OrderSide.SELL

            scores.append(
                MomentumScore(
                    pair=pair,
                    trailing_return_pct=ret,
                    direction=direction,
                    lookback_months=self._settings.lookback_months,
                )
            )

        # Sort by absolute return descending (strongest trend first)
        scores.sort(key=lambda s: abs(s.trailing_return_pct), reverse=True)

        # Limit to max concurrent
        return scores[: self._settings.max_concurrent_momentum]

    def _build_entry_signal(
        self,
        score: MomentumScore,
        mid_price: float,
        nlv: float,
        num_targets: int,
        quote_to_cad: float = 1.0,
    ) -> Signal:
        """Build an entry signal for a momentum position.

        Mirrors the carry sizing: risk-budget position sizing with a
        percentage stop loss and no take-profit (positions exit on the next
        rebalance or via the stop). IDEALPRO accepts odd-lot orders below 25K
        units, so sizing uses the actual risk budget without a floor.
        """
        risk_pct = self._settings.max_risk_per_momentum_pct

        # Percentage-based stop loss
        sl_distance = mid_price * (self._settings.stop_loss_pct / 100)
        if score.direction == OrderSide.BUY:
            stop_loss = mid_price - sl_distance
        else:
            stop_loss = mid_price + sl_distance

        # Position sizing via risk budget (account for quote-to-CAD conversion).
        # 0.95 safety margin absorbs quote_to_cad drift between sizing and
        # risk validation, avoiding borderline rejections.
        pip_size = get_pip_size(score.pair)
        sl_pips = sl_distance / pip_size
        if sl_pips <= 0 or quote_to_cad <= 0:
            raise ValueError(
                f"Momentum sizing impossible for {score.pair}: "
                f"sl_pips={sl_pips}, quote_to_cad={quote_to_cad}"
            )
        risk_amount = nlv * (risk_pct / 100) * 0.95
        pip_value_cad = pip_size * quote_to_cad
        units = risk_amount / (sl_pips * pip_value_cad)
        units = max(round(units), 1)

        return Signal(
            instrument=score.pair,
            side=score.direction,
            order_type=OrderType.MARKET,
            quantity=units,
            price=mid_price,
            stop_loss=stop_loss,
            take_profit=None,  # No TP — hold for the trend, exit on rebalance
            strategy="momentum",
            reason=f"momentum ret={score.trailing_return_pct:+.1f}% ({score.lookback_months}M)",
        )

    async def _close_position(self, pair: str, position: MomentumPosition, reason: str) -> None:
        """Close an active momentum position.

        Ordering matters: flatten FIRST with a verified market order, then
        cancel the SL child. The reverse (cancel first) can strand a naked
        position if the flatten fails. On failure the position stays tracked
        and protected, and the next rebalance retries.
        """
        logger.info(f"Momentum: closing {pair} ({reason})")
        order_service = OrderService(self._client)

        reverse_side = OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY
        close_order = Order(
            instrument=pair,
            side=reverse_side,
            order_type=OrderType.MARKET,
            quantity=position.quantity,
            strategy="momentum",
        )
        try:
            ib_trade = await order_service.place_order(close_order)
            fill_price = await self._monitor.await_fill(ib_trade)
        except ForexBotError as e:
            logger.error(f"Momentum: failed to close {pair}, keeping position tracked: {e}")
            return

        if fill_price is None:
            logger.error(
                f"Momentum: close order for {pair} did not fill — position and its "
                f"stop loss remain in place, will retry next rebalance"
            )
            return

        # Position is flat — now remove the working SL child so it cannot
        # trigger later and open a fresh (reversed) position.
        try:
            open_trades = await order_service.get_open_trades()
            for trade in open_trades:
                if trade.order.parentId == position.ib_order_id:
                    await order_service.cancel_order(trade)
                    logger.info(f"Momentum: cancelled SL child for {pair}")
        except ForexBotError as e:
            logger.critical(
                f"Momentum: {pair} is flat but its SL child could not be "
                f"cancelled — a working stop order remains at IB and can "
                f"open a new position. Cancel it in TWS. Error: {e}"
            )

        # Record the close in the journal and feed the circuit breaker.
        await self._monitor.record_exit_fill(position.ib_order_id, fill_price)
        self._positions.pop(pair, None)
        logger.info(f"Momentum: closed {pair} via {reverse_side} {position.quantity} at {fill_price}")

    async def _send_rebalance_summary(
        self,
        scores: list[MomentumScore],
        entered: list[str],
        closed: list[str],
    ) -> None:
        """Send Telegram summary of rebalance results."""
        if not self._notifier:
            return

        lines = ["*MOMENTUM REBALANCE*\n"]

        if scores:
            lines.append("*Targets:*")
            for s in scores:
                status = "NEW" if s.pair in entered else "HELD"
                lines.append(
                    f"  {s.pair} {s.direction} ret={s.trailing_return_pct:+.1f}% [{status}]"
                )

        if closed:
            lines.append(f"\n*Closed:* {', '.join(closed)}")

        held = [p for p in self._positions if p not in entered]
        if held:
            lines.append(f"*Held:* {', '.join(held)}")

        lines.append(f"\n*Active momentum positions:* {len(self._positions)}")

        try:
            await self._notifier.send_raw("\n".join(lines))
        except Exception as e:
            logger.warning(f"Momentum rebalance notification failed: {e}")
