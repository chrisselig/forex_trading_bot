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
        self._settings = get_settings()

    async def evaluate_pre_event(
        self,
        event: EconomicEvent,
        price: PriceSnapshot,
    ) -> list[Signal]:
        """Place buy stop above and sell stop below current mid price."""
        distance_pips, tp_pips, sl_pips = self._settings.strategy.get_straddle_params(
            price.instrument
        )
        pip = get_pip_size(price.instrument)
        mid = price.mid
        distance = distance_pips * pip
        tp_distance = tp_pips * pip
        sl_distance = sl_pips * pip

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
            f"Straddle signals for {event.title} on {price.instrument}: "
            f"BUY@{buy_entry:.5f} SELL@{sell_entry:.5f} (mid={mid:.5f}, "
            f"D={distance_pips} TP={tp_pips} SL={sl_pips})"
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
