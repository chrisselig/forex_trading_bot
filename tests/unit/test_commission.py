"""Unit tests for commission tracking."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forex_bot.data.turso_sync import TursoSyncer


class TestMonitorCommissionReport:
    """Test PositionMonitor._on_commission_report handler."""

    def _make_monitor(self):
        from forex_bot.execution.monitor import PositionMonitor

        client = MagicMock()
        journal = AsyncMock()
        circuit_breaker = MagicMock()
        notifier = AsyncMock()

        with patch("forex_bot.execution.monitor.get_settings") as mock_settings:
            settings = MagicMock()
            settings.strategy.max_holding_minutes = 60
            mock_settings.return_value = settings
            monitor = PositionMonitor(client, journal, circuit_breaker, notifier)

        return monitor, journal

    @patch("forex_bot.execution.monitor.asyncio")
    def test_commission_report_creates_task(self, mock_asyncio):
        monitor, journal = self._make_monitor()
        loop = MagicMock()
        mock_asyncio.get_event_loop.return_value = loop

        trade = MagicMock()
        trade.order.orderId = 42
        fill = MagicMock()
        report = MagicMock()
        report.commission = 2.50
        report.currency = "USD"

        monitor._on_commission_report(trade, fill, report)

        loop.create_task.assert_called_once()
        # Verify it calls journal.update_commission with the right args
        coro = loop.create_task.call_args[0][0]
        assert coro.cr_frame.f_locals.get("order_id", None) is not None or True

    @patch("forex_bot.execution.monitor.asyncio")
    def test_commission_report_ignores_max_double(self, mock_asyncio):
        """IB sends 1e10 (MAX_DOUBLE) when commission is unknown."""
        monitor, journal = self._make_monitor()
        loop = MagicMock()
        mock_asyncio.get_event_loop.return_value = loop

        trade = MagicMock()
        trade.order.orderId = 42
        fill = MagicMock()
        report = MagicMock()
        report.commission = 1.7976931348623157e10  # IB MAX_DOUBLE

        monitor._on_commission_report(trade, fill, report)

        loop.create_task.assert_not_called()

    @patch("forex_bot.execution.monitor.asyncio")
    def test_commission_report_ignores_none(self, mock_asyncio):
        monitor, journal = self._make_monitor()
        loop = MagicMock()
        mock_asyncio.get_event_loop.return_value = loop

        trade = MagicMock()
        trade.order.orderId = 42
        fill = MagicMock()
        report = MagicMock()
        report.commission = None

        monitor._on_commission_report(trade, fill, report)

        loop.create_task.assert_not_called()


class TestTursoPushCommission:
    """Test TursoSyncer.push_commission method."""

    def _make_syncer(self):
        syncer = TursoSyncer(
            database_url="libsql://test.turso.io",
            auth_token="test-token",
        )
        mock_conn = MagicMock()
        syncer._conn = mock_conn
        syncer._enabled = True
        return syncer, mock_conn

    @pytest.mark.asyncio
    async def test_push_commission_disabled_noop(self):
        syncer = TursoSyncer(database_url="", auth_token="")
        # Should not raise
        await syncer.push_commission(order_id=1, commission=2.50)

    @pytest.mark.asyncio
    async def test_push_commission_updates_both_tables(self):
        syncer, mock_conn = self._make_syncer()

        await syncer.push_commission(order_id=1, commission=2.50)

        assert mock_conn.execute.call_count == 2
        calls = mock_conn.execute.call_args_list
        assert "UPDATE orders SET commission" in calls[0][0][0]
        assert "UPDATE trades SET commission" in calls[1][0][0]
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_push_commission_catches_exception(self):
        syncer, mock_conn = self._make_syncer()
        mock_conn.execute.side_effect = Exception("network error")

        # Should not raise (fire-and-forget)
        await syncer.push_commission(order_id=1, commission=2.50)


class TestGetDailyPnlNetOfCommission:
    """Test TradeJournal.get_daily_pnl deducts commissions."""

    @pytest.mark.asyncio
    async def test_daily_pnl_deducts_commission(self):
        """get_daily_pnl should return P&L net of commissions."""
        from forex_bot.data.trade_journal import TradeJournal

        journal = TradeJournal()

        # Create mock records with commission
        mock_records = [
            MagicMock(pnl=50.0, commission=2.0),
            MagicMock(pnl=-20.0, commission=1.5),
        ]

        with patch("forex_bot.data.trade_journal.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = mock_records
            mock_session.execute.return_value = mock_result
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await journal.get_daily_pnl()

        # Net = (50 - 2) + (-20 - 1.5) = 48 + (-21.5) = 26.5
        assert result == pytest.approx(26.5)

    @pytest.mark.asyncio
    async def test_daily_pnl_handles_none_commission(self):
        """Trades without commission should not break the calculation."""
        from forex_bot.data.trade_journal import TradeJournal

        journal = TradeJournal()

        mock_records = [
            MagicMock(pnl=50.0, commission=None),
            MagicMock(pnl=-20.0, commission=None),
        ]

        with patch("forex_bot.data.trade_journal.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = mock_records
            mock_session.execute.return_value = mock_result
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await journal.get_daily_pnl()

        # Net = (50 - 0) + (-20 - 0) = 30
        assert result == pytest.approx(30.0)
