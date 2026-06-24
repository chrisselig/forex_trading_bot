from __future__ import annotations

from abc import ABC, abstractmethod

from forex_bot.strategy.signals import Signal
from forex_bot.models.account import AccountSummary
from forex_bot.models.market import PriceSnapshot


class RiskRule(ABC):
    """Abstract base for risk validation rules."""

    @abstractmethod
    def validate(
        self,
        signal: Signal,
        account: AccountSummary,
        price: PriceSnapshot | None = None,
        open_position_count: int = 0,
        daily_pnl: float = 0.0,
        quote_to_cad: float = 1.0,
    ) -> str | None:
        """Return error message if rule is violated, None if OK."""
        ...


class MaxRiskPerTrade(RiskRule):
    def __init__(self, max_pct: float = 1.0):
        self.max_pct = max_pct

    def validate(self, signal, account, price=None, open_position_count=0, daily_pnl=0.0, quote_to_cad=1.0):
        if signal.stop_loss is None or signal.price is None:
            return None  # Can't validate without SL
        risk_amount = abs(signal.price - signal.stop_loss) * signal.quantity * quote_to_cad
        max_risk = account.net_liquidation * (self.max_pct / 100)
        if risk_amount > max_risk:
            return f"Risk ${risk_amount:.2f} exceeds {self.max_pct}% limit (${max_risk:.2f})"
        return None


class MaxDailyDrawdown(RiskRule):
    def __init__(self, max_pct: float = 3.0):
        self.max_pct = max_pct

    def validate(self, signal, account, price=None, open_position_count=0, daily_pnl=0.0, quote_to_cad=1.0):
        max_loss = account.net_liquidation * (self.max_pct / 100)
        if daily_pnl < -max_loss:
            return f"Daily drawdown ${abs(daily_pnl):.2f} exceeds {self.max_pct}% limit (${max_loss:.2f})"
        return None


class MaxConcurrentPositions(RiskRule):
    def __init__(self, max_positions: int = 3):
        self.max_positions = max_positions

    def validate(self, signal, account, price=None, open_position_count=0, daily_pnl=0.0, quote_to_cad=1.0):
        if open_position_count >= self.max_positions:
            return f"Already at max concurrent positions ({self.max_positions})"
        return None


class MandatoryStopLoss(RiskRule):
    def validate(self, signal, account, price=None, open_position_count=0, daily_pnl=0.0, quote_to_cad=1.0):
        if signal.stop_loss is None:
            return "Stop loss is mandatory for all trades"
        return None


class MaxSpread(RiskRule):
    def __init__(self, max_pips: float = 3.0, overrides: dict[str, float] | None = None):
        self.max_pips = max_pips
        self._overrides = overrides or {}

    def validate(self, signal, account, price=None, open_position_count=0, daily_pnl=0.0, quote_to_cad=1.0):
        if price is None:
            return None
        limit = self._overrides.get(signal.instrument, self.max_pips)
        spread_pips = price.spread_pips()
        if spread_pips > limit:
            return f"Spread {spread_pips:.1f} pips exceeds max {limit:.0f} pips for {signal.instrument}"
        return None
