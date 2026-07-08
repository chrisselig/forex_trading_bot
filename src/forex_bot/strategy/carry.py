from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from loguru import logger
from pydantic import BaseModel

from forex_bot.broker.client import IBClient
from forex_bot.broker.exceptions import ForexBotError
from forex_bot.broker.contracts import get_pip_size
from forex_bot.broker.orders import OrderService
from forex_bot.broker.pricing import PricingService
from forex_bot.config import get_settings
from forex_bot.data.trade_journal import TradeJournal
from forex_bot.execution.engine import ExecutionEngine
from forex_bot.execution.monitor import PositionMonitor
from forex_bot.models.orders import Order, OrderSide, OrderType
from forex_bot.notifications.telegram import TelegramNotifier
from forex_bot.strategy.signals import Signal

# FRED series for central-bank policy rates.
#
# Uses the OECD "Immediate rates: less than 24 hours: call money / interbank
# rate" family (IRSTCI01*), which tracks each central bank's policy rate and is
# the correct proxy for the overnight carry roll (tom-next FX swap). Keeping a
# single methodology across all currencies means systematic biases cancel in the
# differential.
#
# NOTE: the previous IRSTCB01* ("central bank rates") series were discontinued by
# the OECD — AUD/NZD/MXN returned "series does not exist" and ZAR/JPY went stale
# in Dec 2023, which silently collapsed the tradeable universe to TRY-on-fallback.
# Verify any change here still returns recent observations before deploying.
FRED_RATE_SERIES: dict[str, str] = {
    "USD": "IRSTCI01USM156N",
    "ZAR": "IRSTCI01ZAM156N",
    "AUD": "IRSTCI01AUM156N",
    "JPY": "IRSTCI01JPM156N",
    "MXN": "IRSTCI01MXM156N",
    "TRY": "IRSTCI01TRM156N",
    # NZD immediate-rate series is stale (last obs 2024-12); the 3-month
    # interbank rate is the closest currently-updated proxy for the RBNZ OCR.
    "NZD": "IR3TIB01NZM156N",
}


class CarryScore(BaseModel):
    """Score for a single currency pair based on interest rate differential."""

    pair: str
    base_currency: str
    quote_currency: str
    base_rate: float
    quote_rate: float
    differential: float  # quote_rate - base_rate
    direction: OrderSide  # SELL if diff > 0, BUY if diff < 0
    rate_source: str  # "fred" or "fallback"


class CarryPosition(BaseModel):
    """Tracked carry position."""

    pair: str
    side: OrderSide
    entry_price: float
    quantity: float
    stop_loss: float
    ib_order_id: int
    opened_at: datetime


class CarryManager:
    """Schedule-driven carry trade manager.

    Exploits the forward premium puzzle by holding long positions in
    high-yield currencies and short positions in low-yield currencies.
    Produces Signal objects and feeds them through the existing
    ExecutionEngine, preserving the mandatory risk pipeline.
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
        self._settings = get_settings().carry
        self._positions: dict[str, CarryPosition] = {}  # pair -> position

    async def restore_state(self) -> None:
        """Rebuild carry positions from database on startup.

        Only orders with a real IB order ID and entry price are restored —
        fabricating placeholders (ib_order_id=0 matches every parentless IB
        order) would make later close/cancel logic dangerous.
        """
        orders = await self._journal.get_open_orders_by_strategy("carry")
        for order in orders:
            entry_price = order.fill_price or order.price
            if not order.ib_order_id or entry_price is None:
                logger.warning(
                    f"Carry: cannot restore {order.instrument} position from "
                    f"order #{order.id} (ib_order_id={order.ib_order_id}, "
                    f"price={entry_price}) — manage it manually in TWS"
                )
                continue
            self._positions[order.instrument] = CarryPosition(
                pair=order.instrument,
                side=OrderSide(order.side),
                entry_price=entry_price,
                quantity=order.quantity,
                stop_loss=order.stop_loss or 0.0,
                ib_order_id=order.ib_order_id,
                opened_at=order.created_at,
            )
        if self._positions:
            logger.info(f"Restored {len(self._positions)} carry position(s): {list(self._positions.keys())}")

    def get_carry_order_ids(self) -> set[int]:
        """Return IB order IDs for all active carry positions."""
        return {p.ib_order_id for p in self._positions.values() if p.ib_order_id}

    def get_active_currencies(self) -> set[str]:
        """Return currencies held by carry positions (for sweep exclusion)."""
        currencies: set[str] = set()
        for pair in self._positions:
            currencies.add(pair[:3])
            currencies.add(pair[3:])
        currencies.discard("CAD")  # Never exclude account currency
        return currencies

    async def rebalance(self) -> None:
        """Weekly rebalance entry point.

        1. Fetch interest rates
        2. Score pairs by differential
        3. Close positions no longer in target set
        4. Enter new positions
        """
        if not self._settings.enabled:
            logger.debug("Carry strategy disabled, skipping rebalance")
            return

        if not self._client.is_connected:
            logger.warning("Carry rebalance skipped: IB not connected")
            return

        logger.info("Starting carry rebalance")

        # Fetch rates and score
        rates = await self._fetch_rates()
        if not rates:
            logger.error("Carry rebalance aborted: no interest rates available")
            return

        scores = self._calculate_scores(rates)
        target_pairs = {s.pair for s in scores}
        target_directions = {s.pair: s.direction for s in scores}

        logger.info(f"Carry targets: {[f'{s.pair} {s.direction} (diff={s.differential:+.1f}%)' for s in scores]}")

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
                logger.debug(f"Carry: holding existing {score.pair} position")
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
                    self._positions[score.pair] = CarryPosition(
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
                    logger.info(f"Carry: entered {score.direction} {score.pair} (diff={score.differential:+.1f}%)")
            except (ForexBotError, ValueError) as e:
                logger.error(f"Carry: failed to enter {score.pair}: {e}")

        await self._send_rebalance_summary(scores, entered, closed)

    async def _fetch_rates(self) -> dict[str, float]:
        """Fetch interest rates from FRED with fallback to config values."""
        rates: dict[str, float] = {}
        fallback = self._settings.fallback_rates

        # Collect all currencies needed
        currencies: set[str] = set()
        for pair in self._settings.instruments:
            currencies.add(pair[:3])
            currencies.add(pair[3:])

        for ccy in currencies:
            series_id = FRED_RATE_SERIES.get(ccy)
            if series_id:
                try:
                    rate = await self._fetch_fred_rate(series_id)
                    if rate is not None:
                        rates[ccy] = rate
                        continue
                except Exception as e:
                    logger.warning(f"FRED fetch failed for {ccy} ({series_id}): {e}")

            # Fallback
            if ccy in fallback:
                rates[ccy] = fallback[ccy]
                logger.info(f"Using fallback rate for {ccy}: {fallback[ccy]}%")
            else:
                logger.warning(f"No rate available for {ccy} (no FRED series, no fallback)")

        return rates

    async def _fetch_fred_rate(self, series_id: str) -> float | None:
        """Fetch the latest value from a FRED series.

        fredapi is synchronous (requests-based) — run it in a thread so a
        slow FRED response cannot freeze the event loop.
        """
        try:
            from forex_bot.calendar.fred_client import FredClient

            fred = FredClient()
            data = await asyncio.to_thread(fred.get_series, series_id)
            if data:
                latest = data[-1]
                age_days = (datetime.now() - latest["date"]).days
                # OECD monthly series are stamped first-of-month and published
                # with a 1-2 month lag, so ~90 days of "age" is normal for fresh
                # data. Warn only past 120 days to flag a genuinely stalled
                # series (the discontinued IRSTCB01* ones ran 900+ days stale).
                if age_days > 120:
                    logger.warning(f"FRED {series_id} data is {age_days} days old")
                return latest["value"]
        except (ImportError, ValueError) as e:
            logger.warning(f"FRED unavailable for {series_id}: {e}")
        return None

    def _calculate_scores(self, rates: dict[str, float]) -> list[CarryScore]:
        """Score each pair by interest rate differential, filter by threshold."""
        scores: list[CarryScore] = []
        threshold = self._settings.min_differential_pct

        for pair in self._settings.instruments:
            base = pair[:3]
            quote = pair[3:]

            if base not in rates or quote not in rates:
                logger.debug(f"Carry: skipping {pair} — missing rate for {base if base not in rates else quote}")
                continue

            differential = rates[quote] - rates[base]
            abs_diff = abs(differential)

            if abs_diff < threshold:
                logger.debug(f"Carry: {pair} diff={differential:+.1f}% below threshold {threshold}%")
                continue

            # Positive diff → SELL pair (short base, long quote, earn quote interest)
            # Negative diff → BUY pair (long base, short quote, earn base interest)
            direction = OrderSide.SELL if differential > 0 else OrderSide.BUY
            source = "fred"
            if base in self._settings.fallback_rates or quote in self._settings.fallback_rates:
                source = "fallback"

            scores.append(
                CarryScore(
                    pair=pair,
                    base_currency=base,
                    quote_currency=quote,
                    base_rate=rates[base],
                    quote_rate=rates[quote],
                    differential=differential,
                    direction=direction,
                    rate_source=source,
                )
            )

        # Sort by absolute differential descending (strongest carry first)
        scores.sort(key=lambda s: abs(s.differential), reverse=True)

        # Limit to max concurrent
        return scores[: self._settings.max_concurrent_carry]

    def _build_entry_signal(
        self,
        score: CarryScore,
        mid_price: float,
        nlv: float,
        num_targets: int,
        quote_to_cad: float = 1.0,
    ) -> Signal:
        """Build an entry signal for a carry position.

        IDEALPRO accepts odd-lot orders below 25K units (routed as
        currency conversions), so position sizing uses actual risk
        budget without any artificial floor.
        """
        # Size to max risk per carry position (what the risk validator enforces)
        risk_pct = self._settings.max_risk_per_carry_pct

        # Wide stop loss for carry (percentage-based)
        sl_distance = mid_price * (self._settings.stop_loss_pct / 100)
        if score.direction == OrderSide.BUY:
            stop_loss = mid_price - sl_distance
        else:
            stop_loss = mid_price + sl_distance

        # Position sizing via risk budget (account for quote-to-CAD conversion)
        # 0.95 safety margin: quote_to_cad can shift between sizing and
        # risk validation, so leave headroom to avoid borderline rejections.
        pip_size = get_pip_size(score.pair)
        sl_pips = sl_distance / pip_size
        if sl_pips <= 0 or quote_to_cad <= 0:
            raise ValueError(
                f"Carry sizing impossible for {score.pair}: "
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
            take_profit=None,  # No TP for carry — hold for interest
            strategy="carry",
            reason=f"carry diff={score.differential:+.1f}% ({score.rate_source})",
        )

    async def _close_position(self, pair: str, position: CarryPosition, reason: str) -> None:
        """Close an active carry position.

        Ordering matters: flatten FIRST with a verified market order, then
        cancel the SL child. The reverse (cancel first) can strand a naked
        position if the flatten fails. On failure the position stays tracked
        and protected, and the next rebalance retries.
        """
        logger.info(f"Carry: closing {pair} ({reason})")
        order_service = OrderService(self._client)

        reverse_side = OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY
        close_order = Order(
            instrument=pair,
            side=reverse_side,
            order_type=OrderType.MARKET,
            quantity=position.quantity,
            strategy="carry",
        )
        try:
            ib_trade = await order_service.place_order(close_order)
            fill_price = await self._monitor.await_fill(ib_trade)
        except ForexBotError as e:
            logger.error(f"Carry: failed to close {pair}, keeping position tracked: {e}")
            return

        if fill_price is None:
            logger.error(
                f"Carry: close order for {pair} did not fill — position and its "
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
                    logger.info(f"Carry: cancelled SL child for {pair}")
        except ForexBotError as e:
            logger.critical(
                f"Carry: {pair} is flat but its SL child could not be "
                f"cancelled — a working stop order remains at IB and can "
                f"open a new position. Cancel it in TWS. Error: {e}"
            )

        # Record the close in the journal and feed the circuit breaker.
        await self._monitor.record_exit_fill(position.ib_order_id, fill_price)
        self._positions.pop(pair, None)
        logger.info(f"Carry: closed {pair} via {reverse_side} {position.quantity} at {fill_price}")

    async def _send_rebalance_summary(
        self,
        scores: list[CarryScore],
        entered: list[str],
        closed: list[str],
    ) -> None:
        """Send Telegram summary of rebalance results."""
        if not self._notifier:
            return

        lines = ["*CARRY REBALANCE*\n"]

        if scores:
            lines.append("*Targets:*")
            for s in scores:
                status = "NEW" if s.pair in entered else "HELD"
                lines.append(
                    f"  {s.pair} {s.direction} diff={s.differential:+.1f}% [{status}]"
                )

        if closed:
            lines.append(f"\n*Closed:* {', '.join(closed)}")

        held = [p for p in self._positions if p not in entered]
        if held:
            lines.append(f"*Held:* {', '.join(held)}")

        lines.append(f"\n*Active carry positions:* {len(self._positions)}")

        try:
            await self._notifier.send_raw("\n".join(lines))
        except Exception as e:
            logger.warning(f"Carry rebalance notification failed: {e}")
