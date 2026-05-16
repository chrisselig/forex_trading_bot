from __future__ import annotations

from loguru import logger

from forex_bot.strategy.base import BaseStrategy
from forex_bot.strategy.straddle import StraddleStrategy
from forex_bot.strategy.surprise import SurpriseStrategy


class StrategyRegistry:
    """Discovers and manages available strategies."""

    def __init__(self):
        self._strategies: dict[str, BaseStrategy] = {}

    def register(self, strategy: BaseStrategy) -> None:
        self._strategies[strategy.name] = strategy
        logger.debug(f"Registered strategy: {strategy.name}")

    def get(self, name: str) -> BaseStrategy | None:
        return self._strategies.get(name)

    def all(self) -> list[BaseStrategy]:
        return list(self._strategies.values())

    @property
    def names(self) -> list[str]:
        return list(self._strategies.keys())


def create_default_registry() -> StrategyRegistry:
    """Create a registry with all built-in strategies."""
    registry = StrategyRegistry()
    registry.register(StraddleStrategy())
    registry.register(SurpriseStrategy())
    return registry
