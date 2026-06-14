from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forex_bot.reporting.weekly import WeeklyReporter


class TestWeeklyReporter:

    def _make_reporter(self) -> tuple[WeeklyReporter, AsyncMock]:
        notifier = MagicMock()
        notifier.send_raw = AsyncMock()
        return WeeklyReporter(notifier=notifier), notifier.send_raw

    @pytest.mark.asyncio
    async def test_sends_no_trades_message(self):
        reporter, send_raw = self._make_reporter()

        with patch.object(reporter, "_get_closed_trades", return_value=[]), \
             patch.object(reporter, "_get_filled_orders", return_value=[]):
            await reporter.send_report()

        send_raw.assert_called_once()
        msg = send_raw.call_args[0][0]
        assert "WEEKLY PERFORMANCE REPORT" in msg
        assert "No trades closed this week" in msg

    @pytest.mark.asyncio
    async def test_sends_report_with_trades(self):
        reporter, send_raw = self._make_reporter()

        trades = [
            MagicMock(
                instrument="USDZAR", pnl=50.0, pnl_pips=70.0,
                event_id=1, closed_at=datetime(2026, 6, 13),
                slippage_pips=1.0,
            ),
            MagicMock(
                instrument="USDTRY", pnl=-20.0, pnl_pips=-10.0,
                event_id=2, closed_at=datetime(2026, 6, 12),
                slippage_pips=0.5,
            ),
        ]

        orders = [
            MagicMock(entry_spread_pips=3.0, slippage_pips=1.0, filled_at=datetime(2026, 6, 13)),
            MagicMock(entry_spread_pips=5.0, slippage_pips=0.5, filled_at=datetime(2026, 6, 12)),
        ]

        with patch.object(reporter, "_get_closed_trades", return_value=trades), \
             patch.object(reporter, "_get_filled_orders", return_value=orders), \
             patch.object(reporter, "_get_event_breakdown", return_value={}):
            await reporter.send_report()

        send_raw.assert_called_once()
        msg = send_raw.call_args[0][0]
        assert "WEEKLY PERFORMANCE REPORT" in msg
        assert "Trades: `2`" in msg
        assert "Won: `1`" in msg
        assert "Lost: `1`" in msg
        assert "Win rate: `50%`" in msg
        assert "+$30.00" in msg
        assert "By pair:" in msg
        assert "Avg spread" in msg

    @pytest.mark.asyncio
    async def test_includes_mc_comparison(self):
        reporter, send_raw = self._make_reporter()

        trades = [
            MagicMock(
                instrument="USDZAR", pnl=50.0, pnl_pips=15.0,
                event_id=1, closed_at=datetime(2026, 6, 13),
                slippage_pips=1.0,
            ),
        ]

        with patch.object(reporter, "_get_closed_trades", return_value=trades), \
             patch.object(reporter, "_get_filled_orders", return_value=[]), \
             patch.object(reporter, "_get_event_breakdown", return_value={}):
            await reporter.send_report()

        msg = send_raw.call_args[0][0]
        assert "vs MC expectations" in msg
        assert "USDZAR" in msg
        assert "IN RANGE" in msg  # 15.0 is within [12.0, 22.8]

    @pytest.mark.asyncio
    async def test_mc_below_ci(self):
        reporter, send_raw = self._make_reporter()

        trades = [
            MagicMock(
                instrument="USDZAR", pnl=-10.0, pnl_pips=5.0,
                event_id=1, closed_at=datetime(2026, 6, 13),
                slippage_pips=1.0,
            ),
        ]

        with patch.object(reporter, "_get_closed_trades", return_value=trades), \
             patch.object(reporter, "_get_filled_orders", return_value=[]), \
             patch.object(reporter, "_get_event_breakdown", return_value={}):
            await reporter.send_report()

        msg = send_raw.call_args[0][0]
        assert "BELOW CI" in msg  # 5.0 is below [12.0, 22.8]

    @pytest.mark.asyncio
    async def test_catches_exceptions(self):
        reporter, send_raw = self._make_reporter()

        with patch.object(reporter, "_get_closed_trades", side_effect=Exception("db error")):
            await reporter.send_report()  # Should not raise

        send_raw.assert_not_called()
