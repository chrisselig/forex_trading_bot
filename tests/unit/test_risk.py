"""Unit tests for risk management."""

import pytest
from datetime import UTC, datetime

from forex_bot.models.account import AccountSummary
from forex_bot.models.market import PriceSnapshot
from forex_bot.models.orders import OrderSide
from forex_bot.risk.rules import (
    MaxDailyDrawdown,
    MaxConcurrentPositions,
    MandatoryStopLoss,
    MaxSpread,
)
from forex_bot.risk.circuit_breaker import CircuitBreaker, CircuitState
from forex_bot.strategy.signals import Signal


@pytest.fixture
def account():
    return AccountSummary(net_liquidation=100000.0)


@pytest.fixture
def price():
    return PriceSnapshot(
        instrument="EURUSD",
        timestamp=datetime.now(UTC),
        bid=1.08500,
        ask=1.08520,
    )


class TestMandatoryStopLoss:
    def test_rejects_no_stop_loss(self, account):
        rule = MandatoryStopLoss()
        signal = Signal(instrument="EURUSD", side=OrderSide.BUY)
        assert rule.validate(signal, account) is not None

    def test_allows_with_stop_loss(self, account):
        rule = MandatoryStopLoss()
        signal = Signal(instrument="EURUSD", side=OrderSide.BUY, stop_loss=1.0800)
        assert rule.validate(signal, account) is None


class TestMaxConcurrentPositions:
    def test_rejects_at_limit(self, account):
        rule = MaxConcurrentPositions(max_positions=3)
        signal = Signal(instrument="EURUSD", side=OrderSide.BUY)
        assert rule.validate(signal, account, open_position_count=3) is not None

    def test_allows_under_limit(self, account):
        rule = MaxConcurrentPositions(max_positions=3)
        signal = Signal(instrument="EURUSD", side=OrderSide.BUY)
        assert rule.validate(signal, account, open_position_count=2) is None


class TestMaxSpread:
    def test_rejects_wide_spread(self, account, price):
        rule = MaxSpread(max_pips=1.0)
        signal = Signal(instrument="EURUSD", side=OrderSide.BUY)
        assert rule.validate(signal, account, price=price) is not None

    def test_allows_narrow_spread(self, account, price):
        rule = MaxSpread(max_pips=5.0)
        signal = Signal(instrument="EURUSD", side=OrderSide.BUY)
        assert rule.validate(signal, account, price=price) is None


class TestMaxDailyDrawdown:
    def test_rejects_on_drawdown(self, account):
        rule = MaxDailyDrawdown(max_pct=3.0)
        signal = Signal(instrument="EURUSD", side=OrderSide.BUY)
        assert rule.validate(signal, account, daily_pnl=-4000.0) is not None

    def test_allows_within_limit(self, account):
        rule = MaxDailyDrawdown(max_pct=3.0)
        signal = Signal(instrument="EURUSD", side=OrderSide.BUY)
        assert rule.validate(signal, account, daily_pnl=-1000.0) is None


class TestCircuitBreaker:
    def test_starts_active(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.ACTIVE

    def test_halts_on_drawdown(self):
        cb = CircuitBreaker(max_daily_drawdown_pct=3.0)
        cb.record_trade_result(-4000.0, 100000.0)
        assert cb.state == CircuitState.HALTED

    def test_cooldown_on_consecutive_losses(self):
        cb = CircuitBreaker(max_consecutive_losses=3)
        cb.record_trade_result(-100.0, 100000.0)
        cb.record_trade_result(-100.0, 100000.0)
        cb.record_trade_result(-100.0, 100000.0)
        assert cb.state == CircuitState.COOLDOWN

    def test_reset_clears_halt(self):
        cb = CircuitBreaker(max_daily_drawdown_pct=3.0)
        cb.record_trade_result(-4000.0, 100000.0)
        assert cb.state == CircuitState.HALTED
        cb.reset()
        assert cb.state == CircuitState.ACTIVE

    def test_check_returns_none_when_active(self):
        cb = CircuitBreaker()
        assert cb.check() is None

    def test_check_returns_error_when_halted(self):
        cb = CircuitBreaker(max_daily_drawdown_pct=3.0)
        cb.record_trade_result(-4000.0, 100000.0)
        assert cb.check() is not None
        assert "HALTED" in cb.check()

    def test_winning_resets_consecutive(self):
        cb = CircuitBreaker(max_consecutive_losses=3)
        cb.record_trade_result(-100.0, 100000.0)
        cb.record_trade_result(-100.0, 100000.0)
        cb.record_trade_result(200.0, 100000.0)
        cb.record_trade_result(-100.0, 100000.0)
        assert cb.state == CircuitState.ACTIVE
