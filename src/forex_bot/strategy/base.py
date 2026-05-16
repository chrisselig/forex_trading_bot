from __future__ import annotations

from abc import ABC, abstractmethod

from forex_bot.models.events import EconomicEvent
from forex_bot.models.market import PriceSnapshot
from forex_bot.strategy.signals import Signal, CloseSignal


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies."""

    name: str = "base"

    @abstractmethod
    async def evaluate_pre_event(
        self,
        event: EconomicEvent,
        price: PriceSnapshot,
    ) -> list[Signal]:
        """Evaluate before event release. Returns signals to place."""
        ...

    @abstractmethod
    async def evaluate_post_event(
        self,
        event: EconomicEvent,
        price: PriceSnapshot,
    ) -> list[Signal]:
        """Evaluate after event release. Returns signals to place."""
        ...

    @abstractmethod
    async def should_close_positions(
        self,
        event: EconomicEvent,
        price: PriceSnapshot,
    ) -> list[CloseSignal]:
        """Check if any positions should be closed."""
        ...
