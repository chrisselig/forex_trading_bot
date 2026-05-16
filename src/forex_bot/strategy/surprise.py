from __future__ import annotations

from loguru import logger

from forex_bot.config import get_settings
from forex_bot.broker.contracts import get_pip_size
from forex_bot.models.events import EconomicEvent
from forex_bot.models.market import PriceSnapshot
from forex_bot.models.orders import OrderSide, OrderType
from forex_bot.strategy.base import BaseStrategy
from forex_bot.strategy.signals import Signal, CloseSignal


class SurpriseStrategy(BaseStrategy):
    """Post-event strategy: trade in the direction of a data surprise."""

    name = "surprise"

    def __init__(self):
        settings = get_settings()
        self._threshold_pct = settings.strategy.surprise_threshold_pct
        self._tp_pips = settings.strategy.surprise_tp_pips
        self._sl_pips = settings.strategy.surprise_sl_pips

    async def evaluate_pre_event(
        self,
        event: EconomicEvent,
        price: PriceSnapshot,
    ) -> list[Signal]:
        """Surprise strategy doesn't generate pre-event signals."""
        return []

    async def evaluate_post_event(
        self,
        event: EconomicEvent,
        price: PriceSnapshot,
    ) -> list[Signal]:
        """Trade surprise direction if magnitude exceeds threshold."""
        surprise = event.surprise_pct
        if surprise is None:
            logger.debug(f"No surprise data for {event.title}")
            return []

        if abs(surprise) < self._threshold_pct:
            logger.info(
                f"Surprise {surprise:.1f}% below threshold "
                f"{self._threshold_pct}% for {event.title}"
            )
            return []

        pip = get_pip_size(price.instrument)
        tp_distance = self._tp_pips * pip
        sl_distance = self._sl_pips * pip

        # Positive surprise = USD strength for most indicators
        # For unemployment-type indicators, positive surprise = USD weakness
        usd_positive = surprise > 0
        unemployment_indicators = ["unemployment", "jobless", "claims"]
        if any(ind in event.title.lower() for ind in unemployment_indicators):
            usd_positive = not usd_positive

        # For pairs where USD is the quote currency (EURUSD, GBPUSD):
        #   USD strength → SELL the pair
        # For pairs where USD is the base (USDCAD, USDJPY):
        #   USD strength → BUY the pair
        instrument = price.instrument.upper()
        usd_is_base = instrument.startswith("USD")

        if usd_positive:
            side = OrderSide.BUY if usd_is_base else OrderSide.SELL
        else:
            side = OrderSide.SELL if usd_is_base else OrderSide.BUY

        entry = price.ask if side == OrderSide.BUY else price.bid

        if side == OrderSide.BUY:
            sl = entry - sl_distance
            tp = entry + tp_distance
        else:
            sl = entry + sl_distance
            tp = entry - tp_distance

        signal = Signal(
            instrument=price.instrument,
            side=side,
            order_type=OrderType.MARKET,
            price=entry,
            stop_loss=sl,
            take_profit=tp,
            event_id=event.id,
            strategy=self.name,
            reason=f"Surprise {surprise:+.1f}% on {event.title} → {side.value} {instrument}",
        )

        logger.info(f"Surprise signal: {signal.reason}")
        return [signal]

    async def should_close_positions(
        self,
        event: EconomicEvent,
        price: PriceSnapshot,
    ) -> list[CloseSignal]:
        """No custom close logic — rely on SL/TP."""
        return []
