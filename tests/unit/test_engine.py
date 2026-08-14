"""Unit tests for ExecutionEngine.execute_signals straddle rollback behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from forex_bot.execution.engine import ExecutionEngine
from forex_bot.models.orders import Order, OrderSide, OrderType
from forex_bot.strategy.signals import Signal


@pytest.fixture
def engine():
    """ExecutionEngine with mocked collaborators; execute_signal is stubbed
    per-test so execute_signals is tested in isolation."""
    client = AsyncMock()
    risk_manager = AsyncMock()
    circuit_breaker = AsyncMock()
    journal = AsyncMock()
    notifier = AsyncMock()

    eng = ExecutionEngine(
        client=client,
        risk_manager=risk_manager,
        circuit_breaker=circuit_breaker,
        journal=journal,
        notifier=notifier,
    )
    eng._order_service = AsyncMock()
    return eng


def _order(instrument: str, side: OrderSide, ib_order_id: int) -> Order:
    return Order(
        instrument=instrument,
        side=side,
        order_type=OrderType.STOP,
        quantity=2499.0,
        ib_order_id=ib_order_id,
    )


def _signal(instrument: str, side: OrderSide) -> Signal:
    return Signal(
        instrument=instrument,
        side=side,
        strategy="straddle",
        order_type=OrderType.STOP,
        quantity=2499.0,
        price=47.9,
        stop_loss=47.8,
        take_profit=48.6,
    )


class TestExecuteSignalsRollback:
    async def test_all_legs_succeed_returns_all_orders(self, engine):
        buy_order = _order("USDTRY", OrderSide.BUY, 412)
        sell_order = _order("USDTRY", OrderSide.SELL, 428)
        engine.execute_signal = AsyncMock(side_effect=[buy_order, sell_order])

        result = await engine.execute_signals(
            [_signal("USDTRY", OrderSide.BUY), _signal("USDTRY", OrderSide.SELL)]
        )

        assert result == [buy_order, sell_order]
        engine._order_service.cancel_order_by_id.assert_not_called()
        engine._notifier.notify_straddle_rollback.assert_not_called()

    async def test_second_leg_failure_cancels_first_leg(self, engine):
        buy_order = _order("USDTRY", OrderSide.BUY, 412)
        engine.execute_signal = AsyncMock(side_effect=[buy_order, None])

        result = await engine.execute_signals(
            [_signal("USDTRY", OrderSide.BUY), _signal("USDTRY", OrderSide.SELL)]
        )

        assert result == []
        engine._order_service.cancel_order_by_id.assert_called_once_with(412)
        engine._notifier.notify_straddle_rollback.assert_called_once()

    async def test_first_leg_failure_has_nothing_to_roll_back(self, engine):
        engine.execute_signal = AsyncMock(return_value=None)

        result = await engine.execute_signals(
            [_signal("USDTRY", OrderSide.BUY), _signal("USDTRY", OrderSide.SELL)]
        )

        assert result == []
        engine._order_service.cancel_order_by_id.assert_not_called()
        engine._notifier.notify_straddle_rollback.assert_not_called()
        # Second signal is never attempted once the first has failed.
        assert engine.execute_signal.call_count == 1

    async def test_rollback_cancels_all_prior_legs_not_just_the_last(self, engine):
        """A 3-signal batch (not a real straddle shape today, but the loop
        must not assume exactly 2 legs) rolls back every already-placed leg."""
        first = _order("USDTRY", OrderSide.BUY, 100)
        second = _order("USDTRY", OrderSide.SELL, 101)
        engine.execute_signal = AsyncMock(side_effect=[first, second, None])

        result = await engine.execute_signals(
            [
                _signal("USDTRY", OrderSide.BUY),
                _signal("USDTRY", OrderSide.SELL),
                _signal("USDTRY", OrderSide.BUY),
            ]
        )

        assert result == []
        assert engine._order_service.cancel_order_by_id.call_count == 2
        engine._order_service.cancel_order_by_id.assert_any_call(100)
        engine._order_service.cancel_order_by_id.assert_any_call(101)
