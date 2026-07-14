"""Unit tests for risk management."""

import pytest
from datetime import UTC, datetime

from forex_bot.broker.contracts import get_pip_size
from forex_bot.models.account import AccountSummary
from forex_bot.models.market import PriceSnapshot
from forex_bot.models.orders import OrderSide
from forex_bot.risk.manager import RiskManager
from forex_bot.risk.rules import (
    MaxDailyDrawdown,
    MaxConcurrentPositions,
    MandatoryStopLoss,
    MaxOrderSize,
    MaxRiskPerTrade,
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


class TestMaxOrderSize:
    def test_rejects_oversized_order(self, account):
        rule = MaxOrderSize(max_units=10_000_000)
        signal = Signal(
            instrument="USDTRY", side=OrderSide.SELL, quantity=12_000_000,
            price=47.0, stop_loss=47.001,
        )
        assert rule.validate(signal, account) is not None

    def test_allows_legit_exotic_size(self, account):
        # A real USDTRY straddle leg (~2.5M units) must pass.
        rule = MaxOrderSize(max_units=10_000_000)
        signal = Signal(
            instrument="USDTRY", side=OrderSide.SELL, quantity=2_453_000,
            price=47.0, stop_loss=47.001,
        )
        assert rule.validate(signal, account) is None

    def test_allows_at_exact_cap(self, account):
        rule = MaxOrderSize(max_units=10_000_000)
        signal = Signal(
            instrument="USDTRY", side=OrderSide.SELL, quantity=10_000_000,
            price=47.0, stop_loss=47.001,
        )
        assert rule.validate(signal, account) is None


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


class TestCalculatePositionSize:
    """Regression tests for the mini-lot rounding boundary.

    calculate_position_size floors to whole mini-lots so the sized position's
    risk can never exceed the max-risk-per-trade cap. The previous behavior
    rounded to the nearest mini-lot, which rounded *up* about half the time,
    tripping the strict ``>`` check in MaxRiskPerTrade and silently rejecting
    the trade (observed live on USDTRY straddles: $246.92 vs $246.91 cap).
    """

    @staticmethod
    def _rejection(nlv, risk_pct, sl_pips, pair, quote_to_cad):
        """Size a position, then run it through MaxRiskPerTrade. Returns the
        rejection string, or None if the sized position is within the cap."""
        # calculate_position_size uses no instance state.
        rm = RiskManager.__new__(RiskManager)
        units = rm.calculate_position_size(
            account_balance=nlv,
            stop_loss_pips=sl_pips,
            pair=pair,
            risk_pct=risk_pct,
            quote_to_cad=quote_to_cad,
        )
        price = 46.87
        signal = Signal(
            instrument=pair,
            side=OrderSide.BUY,
            quantity=units,
            price=price,
            stop_loss=price - sl_pips * get_pip_size(pair),
        )
        account = AccountSummary(net_liquidation=nlv)
        return MaxRiskPerTrade(max_pct=risk_pct).validate(
            signal, account, quote_to_cad=quote_to_cad
        )

    def test_usdtry_straddle_within_cap(self):
        """The exact scenario that was rejected live is now accepted."""
        assert self._rejection(
            nlv=4938.2, risk_pct=5.0, sl_pips=10.0,
            pair="USDTRY", quote_to_cad=0.030226,
        ) is None

    @pytest.mark.parametrize("nlv", [4800.0 + i * 3.7 for i in range(60)])
    def test_never_exceeds_cap_across_balances(self, nlv):
        """Flooring guarantees sized risk <= cap for every balance; the old
        nearest-rounding failed for roughly half of these."""
        assert self._rejection(
            nlv=nlv, risk_pct=5.0, sl_pips=10.0,
            pair="USDTRY", quote_to_cad=0.030226,
        ) is None
