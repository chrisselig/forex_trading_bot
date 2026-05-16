"""Unit tests for trading strategies."""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from forex_bot.models.events import EconomicEvent, EventImpact
from forex_bot.models.market import PriceSnapshot
from forex_bot.models.orders import OrderSide


@pytest.fixture
def event():
    return EconomicEvent(
        id=1,
        title="Non-Farm Employment Change",
        country="USD",
        impact=EventImpact.HIGH,
        scheduled_at=datetime.utcnow(),
        forecast="200K",
        previous="180K",
    )


@pytest.fixture
def event_with_positive_surprise():
    return EconomicEvent(
        id=2,
        title="Non-Farm Employment Change",
        country="USD",
        impact=EventImpact.HIGH,
        scheduled_at=datetime.utcnow(),
        actual="250K",
        forecast="200K",
        previous="180K",
    )


@pytest.fixture
def event_unemployment_positive_surprise():
    return EconomicEvent(
        id=3,
        title="Unemployment Rate",
        country="USD",
        impact=EventImpact.HIGH,
        scheduled_at=datetime.utcnow(),
        actual="4.0%",
        forecast="3.5%",
        previous="3.5%",
    )


@pytest.fixture
def price():
    return PriceSnapshot(
        instrument="EURUSD",
        timestamp=datetime.utcnow(),
        bid=1.08500,
        ask=1.08520,
    )


class TestStraddleStrategy:
    @pytest.mark.asyncio
    async def test_generates_two_signals_pre_event(self, event, price):
        with patch("forex_bot.strategy.straddle.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                strategy=MagicMock(
                    straddle_distance_pips=20,
                    straddle_tp_pips=30,
                    straddle_sl_pips=15,
                )
            )
            from forex_bot.strategy.straddle import StraddleStrategy
            strategy = StraddleStrategy()
            signals = await strategy.evaluate_pre_event(event, price)
            assert len(signals) == 2
            sides = {s.side for s in signals}
            assert OrderSide.BUY in sides
            assert OrderSide.SELL in sides

    @pytest.mark.asyncio
    async def test_no_post_event_signals(self, event, price):
        with patch("forex_bot.strategy.straddle.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                strategy=MagicMock(
                    straddle_distance_pips=20,
                    straddle_tp_pips=30,
                    straddle_sl_pips=15,
                )
            )
            from forex_bot.strategy.straddle import StraddleStrategy
            strategy = StraddleStrategy()
            signals = await strategy.evaluate_post_event(event, price)
            assert len(signals) == 0


class TestSurpriseStrategy:
    @pytest.mark.asyncio
    async def test_generates_signal_on_surprise(self, event_with_positive_surprise, price):
        with patch("forex_bot.strategy.surprise.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                strategy=MagicMock(
                    surprise_threshold_pct=10.0,
                    surprise_tp_pips=25,
                    surprise_sl_pips=15,
                )
            )
            from forex_bot.strategy.surprise import SurpriseStrategy
            strategy = SurpriseStrategy()
            signals = await strategy.evaluate_post_event(event_with_positive_surprise, price)
            assert len(signals) == 1
            # Positive NFP surprise = USD strength = SELL EURUSD
            assert signals[0].side == OrderSide.SELL

    @pytest.mark.asyncio
    async def test_no_signal_below_threshold(self, price):
        event = EconomicEvent(
            title="NFP",
            scheduled_at=datetime.utcnow(),
            actual="205K",
            forecast="200K",
        )
        with patch("forex_bot.strategy.surprise.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                strategy=MagicMock(
                    surprise_threshold_pct=10.0,
                    surprise_tp_pips=25,
                    surprise_sl_pips=15,
                )
            )
            from forex_bot.strategy.surprise import SurpriseStrategy
            strategy = SurpriseStrategy()
            signals = await strategy.evaluate_post_event(event, price)
            assert len(signals) == 0

    @pytest.mark.asyncio
    async def test_unemployment_reverses_direction(self, event_unemployment_positive_surprise, price):
        with patch("forex_bot.strategy.surprise.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                strategy=MagicMock(
                    surprise_threshold_pct=10.0,
                    surprise_tp_pips=25,
                    surprise_sl_pips=15,
                )
            )
            from forex_bot.strategy.surprise import SurpriseStrategy
            strategy = SurpriseStrategy()
            signals = await strategy.evaluate_post_event(event_unemployment_positive_surprise, price)
            assert len(signals) == 1
            # Positive unemployment surprise = USD weakness = BUY EURUSD
            assert signals[0].side == OrderSide.BUY

    @pytest.mark.asyncio
    async def test_no_pre_event_signals(self, event, price):
        with patch("forex_bot.strategy.surprise.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                strategy=MagicMock(
                    surprise_threshold_pct=10.0,
                    surprise_tp_pips=25,
                    surprise_sl_pips=15,
                )
            )
            from forex_bot.strategy.surprise import SurpriseStrategy
            strategy = SurpriseStrategy()
            signals = await strategy.evaluate_pre_event(event, price)
            assert len(signals) == 0
