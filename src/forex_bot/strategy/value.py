from __future__ import annotations

import asyncio
import statistics
from datetime import UTC, datetime, timedelta

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

# FRED CPI (price-index) series per currency, used to build the real exchange
# rate. OECD "all items" indices; a few (AUD, NZD) are quarterly — handled by
# month intersection when aligning with monthly prices.
CPI_SERIES: dict[str, str] = {
    "USD": "CPIAUCSL",
    "EUR": "CP0000EZ19M086NEST",
    "GBP": "GBRCPIALLMINMEI",
    "JPY": "JPNCPIALLMINMEI",
    "CAD": "CANCPIALLMINMEI",
    "AUD": "AUSCPIALLQINMEI",
    "NZD": "NZLCPIALLQINMEI",
    "CHF": "CHECPIALLMINMEI",
}

MIN_MONTHS = 24  # minimum aligned observations to trust a z-score


class ValueScore(BaseModel):
    """PPP mis-valuation score for a pair, from the real exchange rate z-score."""

    pair: str
    real_exchange_rate: float
    mean_rer: float
    z_score: float  # >0: base overvalued in real terms; <0: undervalued
    deviation_pct: float  # current RER vs long-run mean
    direction: OrderSide  # SELL if overvalued (z>0), BUY if undervalued (z<0)


class ValuePosition(BaseModel):
    """Tracked value position."""

    pair: str
    side: OrderSide
    entry_price: float
    quantity: float
    stop_loss: float
    ib_order_id: int
    opened_at: datetime


class ValueManager:
    """Schedule-driven value / PPP manager.

    Monthly, it computes each pair's real exchange rate (nominal price scaled by
    relative CPI), measures how far it sits from its long-run mean as a z-score,
    and takes the most mis-valued pairs: long the undervalued, short the
    overvalued, betting on reversion toward PPP. Signals go through the existing
    ExecutionEngine, preserving the mandatory risk pipeline.

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
        self._settings = get_settings().value
        self._positions: dict[str, ValuePosition] = {}  # pair -> position

    async def restore_state(self) -> None:
        """Rebuild value positions from database on startup.

        Only orders with a real IB order ID and entry price are restored —
        fabricating placeholders (ib_order_id=0 matches every parentless IB
        order) would make later close/cancel logic dangerous.
        """
        orders = await self._journal.get_open_orders_by_strategy("value")
        for order in orders:
            entry_price = order.fill_price or order.price
            if not order.ib_order_id or entry_price is None:
                logger.warning(
                    f"Value: cannot restore {order.instrument} position from "
                    f"order #{order.id} (ib_order_id={order.ib_order_id}, "
                    f"price={entry_price}) — manage it manually in TWS"
                )
                continue
            self._positions[order.instrument] = ValuePosition(
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
                f"Restored {len(self._positions)} value position(s): {list(self._positions.keys())}"
            )

    def get_value_order_ids(self) -> set[int]:
        """Return IB order IDs for all active value positions."""
        return {p.ib_order_id for p in self._positions.values() if p.ib_order_id}

    def get_active_currencies(self) -> set[str]:
        """Return currencies held by value positions (for sweep exclusion)."""
        currencies: set[str] = set()
        for pair in self._positions:
            currencies.add(pair[:3])
            currencies.add(pair[3:])
        currencies.discard("CAD")  # Never exclude account currency
        return currencies

    async def rebalance(self) -> None:
        """Monthly rebalance entry point.

        1. Compute PPP valuations (real-exchange-rate z-scores)
        2. Rank by |z|, keep the most mis-valued above threshold
        3. Close positions no longer in target or with flipped direction
        4. Enter new positions
        """
        if not self._settings.enabled:
            logger.debug("Value strategy disabled, skipping rebalance")
            return

        if not self._client.is_connected:
            logger.warning("Value rebalance skipped: IB not connected")
            return

        logger.info("Starting value rebalance")

        scores = await self._compute_valuations()
        if not scores:
            logger.info("Value rebalance: no pairs mis-valued beyond threshold")

        target_pairs = {s.pair for s in scores}
        target_directions = {s.pair: s.direction for s in scores}

        logger.info(
            f"Value targets: {[f'{s.pair} {s.direction} z={s.z_score:+.2f}' for s in scores]}"
        )

        # Close positions no longer targeted or whose direction flipped
        closed = []
        for pair in list(self._positions):
            pos = self._positions[pair]
            if pair not in target_pairs or target_directions.get(pair) != pos.side:
                reason = "direction flipped" if pair in target_pairs else "reverted to fair value"
                await self._close_position(pair, pos, reason)
                closed.append(pair)

        # Enter new positions
        entered = []
        num_targets = len(scores)
        for score in scores:
            if score.pair in self._positions:
                logger.debug(f"Value: holding existing {score.pair} position")
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
                    self._positions[score.pair] = ValuePosition(
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
                        f"Value: entered {score.direction} {score.pair} "
                        f"(z={score.z_score:+.2f}, dev={score.deviation_pct:+.1f}%)"
                    )
            except (ForexBotError, ValueError) as e:
                logger.error(f"Value: failed to enter {score.pair}: {e}")

        await self._send_rebalance_summary(scores, entered, closed)

    async def _compute_valuations(self) -> list[ValueScore]:
        """Compute real-exchange-rate z-scores for each pair; rank and cap."""
        scores: list[ValueScore] = []
        threshold = self._settings.z_threshold

        for pair in self._settings.instruments:
            base, quote = pair[:3], pair[3:]
            cpi_base = await self._fetch_cpi(base)
            cpi_quote = await self._fetch_cpi(quote)
            if not cpi_base or not cpi_quote:
                logger.warning(f"Value: missing CPI for {pair}, skipping")
                continue

            nominal = await self._fetch_monthly_nominal(pair)
            if not nominal:
                continue

            # Real exchange rate q = S * CPI_base / CPI_quote over common months
            common = sorted(set(nominal) & set(cpi_base) & set(cpi_quote))
            q = [nominal[ym] * cpi_base[ym] / cpi_quote[ym] for ym in common]
            if len(q) < MIN_MONTHS:
                logger.warning(f"Value: insufficient aligned history for {pair} ({len(q)})")
                continue

            mean_q = statistics.fmean(q)
            std_q = statistics.pstdev(q)
            if std_q <= 0 or mean_q <= 0:
                continue

            z = (q[-1] - mean_q) / std_q
            if abs(z) < threshold:
                logger.debug(f"Value: {pair} z={z:+.2f} within threshold {threshold}")
                continue

            # z > 0: base overvalued in real terms -> expect base to fall -> SELL pair
            # z < 0: base undervalued -> BUY pair
            direction = OrderSide.SELL if z > 0 else OrderSide.BUY
            scores.append(
                ValueScore(
                    pair=pair,
                    real_exchange_rate=q[-1],
                    mean_rer=mean_q,
                    z_score=z,
                    deviation_pct=(q[-1] / mean_q - 1) * 100,
                    direction=direction,
                )
            )

        scores.sort(key=lambda s: abs(s.z_score), reverse=True)
        return scores[: self._settings.max_concurrent_value]

    async def _fetch_cpi(self, currency: str) -> dict[tuple[int, int], float] | None:
        """Fetch a currency's CPI history as {(year, month): value} from FRED."""
        series_id = CPI_SERIES.get(currency)
        if not series_id:
            logger.warning(f"Value: no CPI series mapped for {currency}")
            return None
        try:
            from forex_bot.calendar.fred_client import FredClient

            fred = FredClient()
            start = datetime.now() - timedelta(days=365 * (self._settings.lookback_years + 1))
            data = await asyncio.to_thread(fred.get_series, series_id, start)
        except (ImportError, ValueError) as e:
            logger.warning(f"Value: FRED CPI unavailable for {currency}: {e}")
            return None
        return {(d["date"].year, d["date"].month): d["value"] for d in data}

    async def _fetch_monthly_nominal(self, pair: str) -> dict[tuple[int, int], float] | None:
        """Fetch monthly nominal close as {(year, month): price} from IB."""
        try:
            bars = await self._pricing.get_historical_bars(
                pair,
                duration=f"{self._settings.lookback_years} Y",
                bar_size="1 month",
                what_to_show="MIDPOINT",
            )
        except DataError as e:
            logger.warning(f"Value: no price history for {pair}: {e}")
            return None
        return {(b.timestamp.year, b.timestamp.month): b.close for b in bars if b.close > 0}

    def _build_entry_signal(
        self,
        score: ValueScore,
        mid_price: float,
        nlv: float,
        num_targets: int,
        quote_to_cad: float = 1.0,
    ) -> Signal:
        """Build an entry signal for a value position.

        Risk-budget position sizing with a wide percentage stop (value positions
        are held for months while the real exchange rate reverts) and no
        take-profit — the exit is the next rebalance once the pair reverts.
        """
        risk_pct = self._settings.max_risk_per_value_pct

        sl_distance = mid_price * (self._settings.stop_loss_pct / 100)
        if score.direction == OrderSide.BUY:
            stop_loss = mid_price - sl_distance
        else:
            stop_loss = mid_price + sl_distance

        # Risk-budget sizing (account for quote-to-CAD). 0.95 margin absorbs
        # quote_to_cad drift between sizing and risk validation.
        pip_size = get_pip_size(score.pair)
        sl_pips = sl_distance / pip_size
        if sl_pips <= 0 or quote_to_cad <= 0:
            raise ValueError(
                f"Value sizing impossible for {score.pair}: "
                f"sl_pips={sl_pips}, quote_to_cad={quote_to_cad}"
            )
        risk_amount = nlv * (risk_pct / 100) * 0.95
        pip_value_cad = pip_size * quote_to_cad
        units = max(round(risk_amount / (sl_pips * pip_value_cad)), 1)

        return Signal(
            instrument=score.pair,
            side=score.direction,
            order_type=OrderType.MARKET,
            quantity=units,
            price=mid_price,
            stop_loss=stop_loss,
            take_profit=None,  # exit on reversion at the next rebalance
            strategy="value",
            reason=f"value z={score.z_score:+.2f} dev={score.deviation_pct:+.1f}%",
        )

    async def _close_position(self, pair: str, position: ValuePosition, reason: str) -> None:
        """Close an active value position (flatten first, then cancel SL child)."""
        logger.info(f"Value: closing {pair} ({reason})")
        order_service = OrderService(self._client)

        reverse_side = OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY
        close_order = Order(
            instrument=pair,
            side=reverse_side,
            order_type=OrderType.MARKET,
            quantity=position.quantity,
            strategy="value",
        )
        try:
            ib_trade = await order_service.place_order(close_order)
            fill_price = await self._monitor.await_fill(ib_trade)
        except ForexBotError as e:
            logger.error(f"Value: failed to close {pair}, keeping position tracked: {e}")
            return

        if fill_price is None:
            logger.error(
                f"Value: close order for {pair} did not fill — position and its "
                f"stop loss remain in place, will retry next rebalance"
            )
            return

        try:
            open_trades = await order_service.get_open_trades()
            for trade in open_trades:
                if trade.order.parentId == position.ib_order_id:
                    await order_service.cancel_order(trade)
                    logger.info(f"Value: cancelled SL child for {pair}")
        except ForexBotError as e:
            logger.critical(
                f"Value: {pair} is flat but its SL child could not be cancelled — "
                f"a working stop order remains at IB and can open a new position. "
                f"Cancel it in TWS. Error: {e}"
            )

        await self._monitor.record_exit_fill(position.ib_order_id, fill_price)
        self._positions.pop(pair, None)
        logger.info(f"Value: closed {pair} via {reverse_side} {position.quantity} at {fill_price}")

    async def _send_rebalance_summary(
        self,
        scores: list[ValueScore],
        entered: list[str],
        closed: list[str],
    ) -> None:
        """Send Telegram summary of rebalance results."""
        if not self._notifier:
            return

        lines = ["*VALUE / PPP REBALANCE*\n"]

        if scores:
            lines.append("*Targets:*")
            for s in scores:
                status = "NEW" if s.pair in entered else "HELD"
                lines.append(
                    f"  {s.pair} {s.direction} z={s.z_score:+.2f} ({s.deviation_pct:+.1f}%) [{status}]"
                )

        if closed:
            lines.append(f"\n*Closed:* {', '.join(closed)}")

        held = [p for p in self._positions if p not in entered]
        if held:
            lines.append(f"*Held:* {', '.join(held)}")

        lines.append(f"\n*Active value positions:* {len(self._positions)}")

        try:
            await self._notifier.send_raw("\n".join(lines))
        except Exception as e:
            logger.warning(f"Value rebalance notification failed: {e}")
