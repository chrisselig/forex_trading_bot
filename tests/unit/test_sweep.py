"""Unit tests for currency sweep module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from forex_bot.broker.sweep import get_cash_balances, MIN_SWEEP_THRESHOLD


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.ensure_connected = AsyncMock()
    client.ib = MagicMock()
    return client


def _make_account_value(tag, value, currency):
    av = MagicMock()
    av.tag = tag
    av.value = value
    av.currency = currency
    return av


class TestGetCashBalances:
    @pytest.mark.asyncio
    async def test_returns_non_cad_balances(self, mock_client):
        mock_client.ib.accountValues.return_value = [
            _make_account_value("CashBalance", "12.50", "USD"),
            _make_account_value("CashBalance", "100.00", "CAD"),
            _make_account_value("CashBalance", "-340.00", "ZAR"),
        ]
        balances = await get_cash_balances(mock_client)
        assert "USD" in balances
        assert "ZAR" in balances
        assert "CAD" not in balances
        assert balances["USD"] == 12.50
        assert balances["ZAR"] == -340.0

    @pytest.mark.asyncio
    async def test_ignores_base_currency(self, mock_client):
        mock_client.ib.accountValues.return_value = [
            _make_account_value("CashBalance", "87.00", "BASE"),
            _make_account_value("CashBalance", "87.00", "CAD"),
        ]
        balances = await get_cash_balances(mock_client)
        assert len(balances) == 0

    @pytest.mark.asyncio
    async def test_ignores_below_threshold(self, mock_client):
        mock_client.ib.accountValues.return_value = [
            _make_account_value("CashBalance", "0.50", "USD"),
            _make_account_value("CashBalance", "5.00", "JPY"),
        ]
        balances = await get_cash_balances(mock_client)
        assert "USD" not in balances
        assert "JPY" in balances

    @pytest.mark.asyncio
    async def test_ignores_non_cash_tags(self, mock_client):
        mock_client.ib.accountValues.return_value = [
            _make_account_value("NetLiquidation", "87.00", "USD"),
            _make_account_value("CashBalance", "10.00", "USD"),
        ]
        balances = await get_cash_balances(mock_client)
        assert balances["USD"] == 10.0

    @pytest.mark.asyncio
    async def test_empty_account(self, mock_client):
        mock_client.ib.accountValues.return_value = []
        balances = await get_cash_balances(mock_client)
        assert len(balances) == 0
