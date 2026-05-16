from __future__ import annotations

from loguru import logger

from forex_bot.config import get_settings
from forex_bot.broker.contracts import get_pip_size
from forex_bot.models.events import EconomicEvent
from forex_bot.models.market import PriceSnapshot
from forex_bot.models.orders import OrderSide, OrderType
from forex_bot.strategy.base import BaseStrategy
from forex_bot.strategy.signals import Signal, CloseSignal


class StraddleStrategy(BaseStrategy):
    """Pre-event straddle: place buy stop above + sell stop below current price."""

    name = "straddle"

    def __init__(self):
        settings = get_settings()
        self._distance_pips = settings.strategy.straddle_distance_pips
        self._tp_pips = settings.strategy.straddle_tp_pips
        self._sl_pips = settings.strategy.straddle_sl_pips

    async def evaluate_pre_event(
        self,
        event: EconomicEvent,
        price: PriceSnapshot,
    ) -> list[Signal]:
        """Place buy stop above and sell stop below current mid price."""
        pip = get_pip_size(price.instrument)
        mid = price.mid
        distance = self._distance_pips * pip
        tp_distance = self._tp_pips * pip
        sl_distance = self._sl_pips * pip

        buy_entry = mid + distance
        sell_entry = mid - distance

        signals = [
            Signal(
                instrument=price.instrument,
                side=OrderSide.BUY,
                order_type=OrderType.STOP,
                price=buy_entry,
                stop_loss=buy_entry - sl_distance,
                take_profit=buy_entry + tp_distance,
                event_id=event.id,
                strategy=self.name,
                reason=f"Straddle BUY stop for {event.title}",
            ),
            Signal(
                instrument=price.instrument,
                side=OrderSide.SELL,
                order_type=OrderType.STOP,
                price=sell_entry,
                stop_loss=sell_entry + sl_distance,
                take_profit=sell_entry - tp_distance,
                event_id=event.id,
                strategy=self.name,
                reason=f"Straddle SELL stop for {event.title}",
            ),
        ]

        logger.info(
            f"Straddle signals for {event.title}: "
            f"BUY@{buy_entry:.5f} SELL@{sell_entry:.5f} (mid={mid:.5f})"
        )
        return signals

    async def evaluate_post_event(
        self,
        event: EconomicEvent,
        price: PriceSnapshot,
    ) -> list[Signal]:
        """Straddle strategy doesn't generate post-event signals."""
        return []

    async def should_close_positions(
        self,
        event: EconomicEvent,
        price: PriceSnapshot,
    ) -> list[CloseSignal]:
        """No custom close logic — rely on SL/TP from bracket orders."""
        return []
