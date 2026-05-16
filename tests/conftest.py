"""Shared test fixtures."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from forex_bot.models.events import EconomicEvent, EventImpact
from forex_bot.models.market import PriceSnapshot
from forex_bot.models.orders import Order, OrderSide, OrderType, Trade
from forex_bot.models.account import AccountSummary


@pytest.fixture
def sample_event():
    return EconomicEvent(
        id=1,
        title="Non-Farm Employment Change",
        country="USD",
        impact=EventImpact.HIGH,
        scheduled_at=datetime.utcnow() + timedelta(minutes=30),
        forecast="200K",
        previous="180K",
    )


@pytest.fixture
def sample_event_with_actual():
    return EconomicEvent(
        id=2,
        title="Non-Farm Employment Change",
        country="USD",
        impact=EventImpact.HIGH,
        scheduled_at=datetime.utcnow() - timedelta(minutes=5),
        actual="250K",
        forecast="200K",
        previous="180K",
    )


@pytest.fixture
def sample_price():
    return PriceSnapshot(
        instrument="EURUSD",
        timestamp=datetime.utcnow(),
        bid=1.08500,
        ask=1.08520,
    )


@pytest.fixture
def sample_account():
    return AccountSummary(
        account_id="DU1234567",
        net_liquidation=100000.0,
        total_cash=95000.0,
        buying_power=200000.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
    )


@pytest.fixture
def mock_ib_client():
    """Create a mocked IBClient."""
    client = MagicMock()
    client.is_connected = True
    client.ib = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.ensure_connected = AsyncMock()
    client.get_account_summary = AsyncMock(
        return_value=AccountSummary(
            account_id="DU1234567",
            net_liquidation=100000.0,
            total_cash=95000.0,
            buying_power=200000.0,
        )
    )
    client.get_positions = AsyncMock(return_value=[])
    client.get_open_orders = AsyncMock(return_value=[])
    return client
