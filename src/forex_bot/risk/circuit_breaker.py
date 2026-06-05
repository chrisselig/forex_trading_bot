from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from loguru import logger


class CircuitState(StrEnum):
    ACTIVE = "ACTIVE"
    COOLDOWN = "COOLDOWN"
    HALTED = "HALTED"


class CircuitBreaker:
    """Kill switch for trading. HALTED state requires manual reset."""

    def __init__(
        self,
        max_daily_drawdown_pct: float = 3.0,
        max_consecutive_losses: int = 5,
        cooldown_minutes: int = 30,
    ):
        self._max_daily_drawdown_pct = max_daily_drawdown_pct
        self._max_consecutive_losses = max_consecutive_losses
        self._cooldown_minutes = cooldown_minutes

        self._state = CircuitState.ACTIVE
        self._consecutive_losses = 0
        self._daily_pnl = 0.0
        self._account_balance = 0.0
        self._cooldown_until: datetime | None = None
        self._halt_reason: str = ""

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.COOLDOWN and self._cooldown_until:
            if datetime.now(UTC) >= self._cooldown_until:
                self._state = CircuitState.ACTIVE
                self._cooldown_until = None
                logger.info("Circuit breaker cooldown expired, returning to ACTIVE")
        return self._state

    @property
    def halt_reason(self) -> str:
        return self._halt_reason

    def check(self) -> str | None:
        """Check if trading is allowed. Returns error message if blocked."""
        state = self.state
        if state == CircuitState.HALTED:
            return f"Circuit breaker HALTED: {self._halt_reason}. Manual reset required."
        if state == CircuitState.COOLDOWN:
            remaining = (self._cooldown_until - datetime.now(UTC)).total_seconds() / 60
            return f"Circuit breaker in COOLDOWN for {remaining:.0f} more minutes"
        return None

    def record_trade_result(self, pnl: float, account_balance: float) -> None:
        """Record a trade result and update circuit breaker state."""
        self._account_balance = account_balance
        self._daily_pnl += pnl

        if pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

        # Check consecutive losses
        if self._consecutive_losses >= self._max_consecutive_losses:
            self._enter_cooldown(f"{self._consecutive_losses} consecutive losses")

        # Check daily drawdown
        if self._account_balance > 0:
            drawdown_pct = abs(self._daily_pnl) / self._account_balance * 100
            if self._daily_pnl < 0 and drawdown_pct >= self._max_daily_drawdown_pct:
                self._halt(f"Daily drawdown {drawdown_pct:.1f}% exceeds {self._max_daily_drawdown_pct}%")

    def _enter_cooldown(self, reason: str) -> None:
        self._state = CircuitState.COOLDOWN
        self._cooldown_until = datetime.now(UTC) + timedelta(minutes=self._cooldown_minutes)
        logger.warning(f"Circuit breaker → COOLDOWN: {reason}")

    def _halt(self, reason: str) -> None:
        self._state = CircuitState.HALTED
        self._halt_reason = reason
        logger.error(f"Circuit breaker → HALTED: {reason}")

    def reset(self) -> None:
        """Manual reset — returns to ACTIVE state."""
        prev = self._state
        self._state = CircuitState.ACTIVE
        self._consecutive_losses = 0
        self._daily_pnl = 0.0
        self._cooldown_until = None
        self._halt_reason = ""
        logger.info(f"Circuit breaker manually reset from {prev} to ACTIVE")

    def reset_daily(self) -> None:
        """Reset daily counters (call at start of trading day)."""
        self._daily_pnl = 0.0
        self._consecutive_losses = 0
        if self._state == CircuitState.COOLDOWN:
            self._state = CircuitState.ACTIVE
            self._cooldown_until = None
        logger.info("Circuit breaker daily counters reset")
