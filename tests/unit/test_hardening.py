"""Regression tests for the 2026-07 hardening pass.

Each test pins a specific production bug found in the full-repo review so
it cannot silently reappear.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from forex_bot.broker.contracts import get_pip_size, get_tick_size
from forex_bot.broker.exceptions import OrderError
from forex_bot.execution.monitor import _planned_price
from forex_bot.models.market import PriceSnapshot
from forex_bot.models.orders import OrderStatus
from forex_bot.risk.rules import MaxSpread, PositiveQuantity

_IB_UNSET_DOUBLE = 1.7976931348623157e308


# ---------------------------------------------------------------------------
# Dedup prune: naive/aware TypeError killed every pre-event handler
# ---------------------------------------------------------------------------

def _make_job_manager():
    from forex_bot.scheduler.jobs import JobManager

    return JobManager(
        scheduler=MagicMock(),
        execution_engine=MagicMock(),
        pricing=MagicMock(),
        event_store=MagicMock(),
        strategy_registry=MagicMock(),
        monitor=MagicMock(),
        client=MagicMock(),
        settings=MagicMock(),
        notifier=None,
    )


def test_dedup_prune_handles_naive_event_times():
    """Keys carry naive-UTC datetimes; pruning must not raise TypeError."""
    jm = _make_job_manager()
    fresh = datetime.now(UTC).replace(tzinfo=None)
    stale = fresh - timedelta(hours=48)
    jm._straddle_placed = {("USDZAR", stale), ("USDTRY", fresh)}

    jm._prune_stale_dedup_keys()  # raised TypeError before the fix

    assert jm._straddle_placed == {("USDTRY", fresh)}


# ---------------------------------------------------------------------------
# NaN prices: ib_async initializes absent quotes to NaN
# ---------------------------------------------------------------------------

def test_price_snapshot_rejects_nan_and_nonpositive():
    for bad_bid, bad_ask in [
        (float("nan"), 1.1), (1.1, float("nan")), (0.0, 1.1), (1.1, -1.0),
    ]:
        with pytest.raises(ValidationError):
            PriceSnapshot(
                instrument="EURUSD",
                timestamp=datetime.now(UTC),
                bid=bad_bid,
                ask=bad_ask,
            )


# ---------------------------------------------------------------------------
# Slippage: UNSET_DOUBLE sentinel treated as a real planned price
# ---------------------------------------------------------------------------

def test_planned_price_ignores_unset_sentinel():
    order = MagicMock()
    order.lmtPrice = _IB_UNSET_DOUBLE
    order.auxPrice = _IB_UNSET_DOUBLE
    assert _planned_price(order) is None

    order.auxPrice = 18.5  # stop entry price
    assert _planned_price(order) == 18.5


# ---------------------------------------------------------------------------
# Pip sizes: unlisted JPY crosses were a silent 100x error
# ---------------------------------------------------------------------------

def test_pip_and_tick_size_jpy_fallback():
    assert get_pip_size("CADJPY") == 0.01
    assert get_tick_size("CHFJPY") == 0.005
    assert get_pip_size("EURCAD") == 0.0001


# ---------------------------------------------------------------------------
# Risk rules
# ---------------------------------------------------------------------------

def test_max_spread_uses_pair_pip_size():
    """A 2-pip USDJPY spread must not be read as 200 pips."""
    rule = MaxSpread(20.0, {})
    signal = MagicMock(instrument="USDJPY")
    price = PriceSnapshot(
        instrument="USDJPY",
        timestamp=datetime.now(UTC),
        bid=149.500,
        ask=149.520,  # 2 real pips
    )
    assert rule.validate(signal, MagicMock(), price) is None  # passes

    wide = PriceSnapshot(
        instrument="USDJPY",
        timestamp=datetime.now(UTC),
        bid=149.500,
        ask=149.750,  # 25 real pips > 20 limit
    )
    assert rule.validate(signal, MagicMock(), wide) is not None


def test_positive_quantity_rule():
    rule = PositiveQuantity()
    assert rule.validate(MagicMock(quantity=0), MagicMock()) is not None
    assert rule.validate(MagicMock(quantity=-5), MagicMock()) is not None
    assert rule.validate(MagicMock(quantity=1000), MagicMock()) is None


# ---------------------------------------------------------------------------
# Order acceptance verification: async rejections must surface
# ---------------------------------------------------------------------------

def _fake_trade(status: str, order_id: int = 1):
    t = MagicMock()
    t.orderStatus.status = status
    t.order.orderId = order_id
    t.log = []
    return t


@pytest.mark.asyncio
async def test_verify_submission_raises_on_rejection():
    from forex_bot.broker.orders import OrderService

    svc = OrderService(MagicMock())
    trades = [_fake_trade("Submitted", 1), _fake_trade("Inactive", 2)]
    with pytest.raises(OrderError, match="rejected"):
        await svc._verify_submission(trades, wait_s=0.5)


@pytest.mark.asyncio
async def test_verify_submission_passes_on_accepted():
    from forex_bot.broker.orders import OrderService

    svc = OrderService(MagicMock())
    trades = [_fake_trade("PreSubmitted", 1), _fake_trade("Submitted", 2)]
    await svc._verify_submission(trades, wait_s=0.5)  # should not raise


# ---------------------------------------------------------------------------
# Trade close pipeline: exit fill -> journal close + circuit breaker feed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exit_fill_closes_trade_and_feeds_breaker(mock_settings):
    from forex_bot.execution.monitor import PositionMonitor
    from forex_bot.models.orders import OrderSide, Trade

    journal = AsyncMock()
    order_rec = MagicMock(
        id=5, instrument="USDZAR", status=OrderStatus.FILLED.value,
        side="BUY", quantity=1000.0, strategy="straddle",
    )
    journal.get_order_by_ib_id.return_value = order_rec
    journal.get_trade_by_order_db_id.return_value = Trade(
        id=9, order_id=5, instrument="USDZAR", side=OrderSide.BUY,
        quantity=1000.0, entry_price=18.5000, fill_price=18.5000,
        stop_loss=18.4900,
    )
    breaker = MagicMock()
    client = MagicMock()
    client.get_account_summary = AsyncMock(
        return_value=MagicMock(net_liquidation=5000.0)
    )
    pricing = MagicMock()
    pricing.get_quote_to_cad_rate = AsyncMock(return_value=0.075)

    monitor = PositionMonitor(client, journal, breaker, pricing=pricing)
    await monitor.record_exit_fill(101, exit_price=18.5070)

    # TP hit: +70 pips, pnl = 0.007 * 1000 * 0.075 CAD
    journal.close_trade.assert_awaited_once()
    args = journal.close_trade.await_args.args
    assert args[1] == 18.5070
    assert args[2] == pytest.approx(0.007 * 1000 * 0.075)
    assert args[3] == pytest.approx(70.0)
    # Entry order marked CLOSED, breaker fed with the CAD P&L
    journal.update_order_status.assert_awaited_once_with(5, OrderStatus.CLOSED)
    breaker.record_trade_result.assert_called_once()
    assert breaker.record_trade_result.call_args.args[0] == pytest.approx(0.525)


@pytest.mark.asyncio
async def test_exit_fill_is_idempotent(mock_settings):
    """A duplicate exit-fill event must not close the trade twice."""
    from forex_bot.execution.monitor import PositionMonitor
    from forex_bot.models.orders import OrderSide, Trade

    journal = AsyncMock()
    journal.get_order_by_ib_id.return_value = MagicMock(
        id=5, instrument="USDZAR", side="BUY", quantity=1000.0,
    )
    journal.get_trade_by_order_db_id.return_value = Trade(
        id=9, order_id=5, instrument="USDZAR", side=OrderSide.BUY,
        quantity=1000.0, entry_price=18.5, closed_at=datetime.now(UTC),
    )
    breaker = MagicMock()
    monitor = PositionMonitor(MagicMock(), journal, breaker, pricing=MagicMock())

    await monitor.record_exit_fill(101, exit_price=18.6)

    journal.close_trade.assert_not_awaited()
    breaker.record_trade_result.assert_not_called()


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.strategy.max_holding_minutes = 120
    with patch("forex_bot.execution.monitor.get_settings", return_value=settings):
        yield settings
