from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from forex_bot.data.turso_sync import TursoSyncer


class TestTursoSyncerDisabled:
    """Test that TursoSyncer is a no-op when disabled."""

    def test_disabled_when_no_url(self):
        syncer = TursoSyncer(database_url="", auth_token="token")
        assert not syncer._enabled

    def test_disabled_when_no_token(self):
        syncer = TursoSyncer(database_url="libsql://db.turso.io", auth_token="")
        assert not syncer._enabled

    def test_disabled_explicitly(self):
        syncer = TursoSyncer(
            database_url="libsql://db.turso.io",
            auth_token="token",
            enabled=False,
        )
        assert not syncer._enabled

    @pytest.mark.asyncio
    async def test_push_order_noop_when_disabled(self):
        syncer = TursoSyncer(database_url="", auth_token="")
        # Should not raise
        await syncer.push_order(
            order_id=1, ib_order_id=100, instrument="USDZAR",
            side="BUY", order_type="STP", quantity=10000,
            price=18.5, stop_loss=18.4, take_profit=19.0,
            status="SUBMITTED", event_id=1, strategy="straddle",
            entry_spread_pips=3.0, created_at=datetime.utcnow(),
        )

    @pytest.mark.asyncio
    async def test_push_trade_noop_when_disabled(self):
        syncer = TursoSyncer(database_url="", auth_token="")
        await syncer.push_trade(
            trade_id=1, order_id=1, instrument="USDZAR",
            side="BUY", quantity=10000, entry_price=18.5,
            stop_loss=18.4, take_profit=19.0, entry_spread_pips=3.0,
            event_id=1, strategy="straddle", opened_at=datetime.utcnow(),
        )

    @pytest.mark.asyncio
    async def test_push_trade_close_noop_when_disabled(self):
        syncer = TursoSyncer(database_url="", auth_token="")
        await syncer.push_trade_close(
            trade_id=1, exit_price=19.0, pnl=50.0,
            pnl_pips=70.0, closed_at=datetime.utcnow(),
        )


class TestTursoSyncerEnabled:
    """Test TursoSyncer calls when enabled (mock the connection)."""

    def _make_syncer(self) -> tuple[TursoSyncer, MagicMock]:
        syncer = TursoSyncer(
            database_url="libsql://test.turso.io",
            auth_token="test-token",
            account_type="paper",
        )
        mock_conn = MagicMock()
        syncer._conn = mock_conn  # Bypass lazy connect
        return syncer, mock_conn

    @pytest.mark.asyncio
    async def test_push_order_executes_sql(self):
        syncer, mock_conn = self._make_syncer()
        await syncer.push_order(
            order_id=1, ib_order_id=100, instrument="USDTRY",
            side="BUY", order_type="STP", quantity=10000,
            price=32.5, stop_loss=32.4, take_profit=33.2,
            status="SUBMITTED", event_id=5, strategy="straddle",
            entry_spread_pips=5.0, created_at=datetime(2026, 6, 13, 12, 30),
        )
        mock_conn.execute.assert_called_once()
        mock_conn.commit.assert_called_once()
        sql = mock_conn.execute.call_args[0][0]
        assert "INSERT OR REPLACE INTO orders" in sql
        assert "account_type" in sql
        # Verify account_type is 'paper'
        params = mock_conn.execute.call_args[0][1]
        assert params[-1] == "paper"

    @pytest.mark.asyncio
    async def test_push_order_status_executes_update(self):
        syncer, mock_conn = self._make_syncer()
        await syncer.push_order_status(
            order_id=1, status="FILLED",
            fill_price=32.55, filled_at=datetime(2026, 6, 13, 12, 31),
            slippage_pips=0.5,
        )
        mock_conn.execute.assert_called_once()
        sql = mock_conn.execute.call_args[0][0]
        assert "UPDATE orders SET status" in sql

    @pytest.mark.asyncio
    async def test_push_trade_executes_insert(self):
        syncer, mock_conn = self._make_syncer()
        await syncer.push_trade(
            trade_id=1, order_id=1, instrument="USDZAR",
            side="SELL", quantity=10000, entry_price=18.5,
            stop_loss=18.6, take_profit=17.8,
            entry_spread_pips=4.0, event_id=3,
            strategy="straddle", opened_at=datetime(2026, 6, 13, 12, 30),
        )
        mock_conn.execute.assert_called_once()
        sql = mock_conn.execute.call_args[0][0]
        assert "INSERT OR REPLACE INTO trades" in sql
        assert "account_type" in sql
        params = mock_conn.execute.call_args[0][1]
        assert params[-1] == "paper"

    @pytest.mark.asyncio
    async def test_push_trade_close_executes_update(self):
        syncer, mock_conn = self._make_syncer()
        await syncer.push_trade_close(
            trade_id=1, exit_price=17.8, pnl=70.0,
            pnl_pips=70.0, closed_at=datetime(2026, 6, 13, 13, 0),
        )
        mock_conn.execute.assert_called_once()
        sql = mock_conn.execute.call_args[0][0]
        assert "UPDATE trades SET exit_price" in sql

    @pytest.mark.asyncio
    async def test_push_order_catches_exceptions(self):
        syncer, mock_conn = self._make_syncer()
        mock_conn.execute.side_effect = Exception("network error")
        # Should not raise — fire-and-forget
        await syncer.push_order(
            order_id=1, ib_order_id=100, instrument="USDTRY",
            side="BUY", order_type="STP", quantity=10000,
            price=32.5, stop_loss=32.4, take_profit=33.2,
            status="SUBMITTED", event_id=5, strategy="straddle",
            entry_spread_pips=5.0, created_at=datetime.utcnow(),
        )
        # Should still be enabled (error is logged, not fatal)
        assert syncer._enabled

    @pytest.mark.asyncio
    async def test_account_type_live(self):
        syncer = TursoSyncer(
            database_url="libsql://test.turso.io",
            auth_token="test-token",
            account_type="live",
        )
        mock_conn = MagicMock()
        syncer._conn = mock_conn
        await syncer.push_order(
            order_id=1, ib_order_id=100, instrument="USDZAR",
            side="BUY", order_type="STP", quantity=10000,
            price=18.5, stop_loss=18.4, take_profit=19.0,
            status="SUBMITTED", event_id=1, strategy="straddle",
            entry_spread_pips=3.0, created_at=datetime.utcnow(),
        )
        params = mock_conn.execute.call_args[0][1]
        assert params[-1] == "live"


    @pytest.mark.asyncio
    async def test_push_event_executes_insert(self):
        syncer, mock_conn = self._make_syncer()
        await syncer.push_event(
            event_id=1, title="Non-Farm Payrolls", country="USD",
            impact="high", scheduled_at=datetime(2026, 6, 13, 12, 30),
            actual="200K", forecast="180K", previous="175K",
            fred_series="PAYEMS", created_at=datetime(2026, 6, 13, 10, 0),
        )
        mock_conn.execute.assert_called_once()
        mock_conn.commit.assert_called_once()
        sql = mock_conn.execute.call_args[0][0]
        assert "INSERT OR REPLACE INTO events" in sql

    @pytest.mark.asyncio
    async def test_push_event_actual_executes_update(self):
        syncer, mock_conn = self._make_syncer()
        await syncer.push_event_actual(event_id=1, actual="200K")
        mock_conn.execute.assert_called_once()
        sql = mock_conn.execute.call_args[0][0]
        assert "UPDATE events SET actual" in sql

    @pytest.mark.asyncio
    async def test_push_event_noop_when_disabled(self):
        syncer = TursoSyncer(database_url="", auth_token="")
        await syncer.push_event(
            event_id=1, title="NFP", country="USD", impact="high",
            scheduled_at=datetime(2026, 6, 13, 12, 30),
            actual=None, forecast="180K", previous="175K",
            fred_series="", created_at=datetime(2026, 6, 13, 10, 0),
        )
        # No exception, no connection attempted


class TestBrokerConfigAccountType:
    """Test account_type derivation from broker port."""

    def test_paper_port_4002(self):
        from forex_bot.config import BrokerConfig
        cfg = BrokerConfig(port=4002)
        assert cfg.account_type == "paper"

    def test_paper_port_7497(self):
        from forex_bot.config import BrokerConfig
        cfg = BrokerConfig(port=7497)
        assert cfg.account_type == "paper"

    def test_live_port_4001(self):
        from forex_bot.config import BrokerConfig
        cfg = BrokerConfig(port=4001)
        assert cfg.account_type == "live"

    def test_live_port_7496(self):
        from forex_bot.config import BrokerConfig
        cfg = BrokerConfig(port=7496)
        assert cfg.account_type == "live"
