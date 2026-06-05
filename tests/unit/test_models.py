"""Unit tests for Pydantic data models."""

from datetime import UTC, datetime
from forex_bot.models.events import EconomicEvent, EventImpact
from forex_bot.models.market import PriceSnapshot, Candle
from forex_bot.models.orders import Order, OrderSide, OrderType, OrderStatus
from forex_bot.models.account import AccountSummary


class TestEconomicEvent:
    def test_surprise_pct_positive(self):
        event = EconomicEvent(
            title="NFP",
            scheduled_at=datetime.now(UTC),
            actual="250K",
            forecast="200K",
        )
        assert event.surprise_pct is not None
        assert event.surprise_pct == pytest.approx(25.0)

    def test_surprise_pct_negative(self):
        event = EconomicEvent(
            title="NFP",
            scheduled_at=datetime.now(UTC),
            actual="150K",
            forecast="200K",
        )
        assert event.surprise_pct is not None
        assert event.surprise_pct == pytest.approx(-25.0)

    def test_surprise_pct_no_actual(self):
        event = EconomicEvent(
            title="NFP",
            scheduled_at=datetime.now(UTC),
            forecast="200K",
        )
        assert event.surprise_pct is None

    def test_has_actual(self):
        event = EconomicEvent(
            title="NFP",
            scheduled_at=datetime.now(UTC),
            actual="250K",
        )
        assert event.has_actual is True

    def test_no_actual(self):
        event = EconomicEvent(
            title="NFP",
            scheduled_at=datetime.now(UTC),
        )
        assert event.has_actual is False


class TestPriceSnapshot:
    def test_mid_price(self):
        price = PriceSnapshot(
            instrument="EURUSD",
            timestamp=datetime.now(UTC),
            bid=1.08500,
            ask=1.08520,
        )
        assert price.mid == pytest.approx(1.08510)

    def test_spread(self):
        price = PriceSnapshot(
            instrument="EURUSD",
            timestamp=datetime.now(UTC),
            bid=1.08500,
            ask=1.08520,
        )
        assert price.spread == pytest.approx(0.00020)

    def test_spread_pips(self):
        price = PriceSnapshot(
            instrument="EURUSD",
            timestamp=datetime.now(UTC),
            bid=1.08500,
            ask=1.08520,
        )
        assert price.spread_pips() == pytest.approx(2.0)

    def test_spread_pips_jpy(self):
        price = PriceSnapshot(
            instrument="USDJPY",
            timestamp=datetime.now(UTC),
            bid=149.500,
            ask=149.520,
        )
        assert price.spread_pips(pip_size=0.01) == pytest.approx(2.0)


class TestOrder:
    def test_default_status(self):
        order = Order(
            instrument="EURUSD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10000,
        )
        assert order.status == OrderStatus.PENDING


import pytest
