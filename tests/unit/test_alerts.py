from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forex_bot.models.orders import OrderSide, Trade
from forex_bot.reporting.alerts import AnomalyDetector


def _make_trade(**kwargs) -> Trade:
    defaults = dict(
        id=1, order_id=1, instrument="USDZAR", side=OrderSide.BUY,
        quantity=10000, entry_price=18.5, exit_price=19.0,
        stop_loss=18.4, take_profit=19.2, pnl=50.0, pnl_pips=50.0,
        entry_spread_pips=3.0, fill_price=18.51, slippage_pips=1.0,
        event_id=1, strategy="straddle",
        opened_at=datetime(2026, 6, 13, 12, 0),
        closed_at=datetime(2026, 6, 13, 13, 0),
    )
    defaults.update(kwargs)
    return Trade(**defaults)


class TestAnomalyDetector:

    def _make_detector(self) -> tuple[AnomalyDetector, AsyncMock]:
        notifier = MagicMock()
        notifier.send_raw = AsyncMock()
        return AnomalyDetector(notifier=notifier), notifier.send_raw

    @pytest.mark.asyncio
    async def test_skips_open_trades(self):
        detector, send_raw = self._make_detector()
        trade = _make_trade(exit_price=None, pnl=None)
        await detector.check_trade(trade)
        send_raw.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_slippage_alert_when_none(self):
        detector, send_raw = self._make_detector()
        trade = _make_trade(slippage_pips=None)
        await detector._check_slippage(trade)
        send_raw.assert_not_called()

    @pytest.mark.asyncio
    async def test_slippage_alert_fires_when_high(self):
        detector, send_raw = self._make_detector()
        trade = _make_trade(slippage_pips=10.0)

        # Mock DB to return historical slippages averaging ~2.0 pips
        mock_result = MagicMock()
        mock_result.all.return_value = [(1.5,), (2.0,), (2.5,), (2.0,), (2.0,)]

        with patch("forex_bot.reporting.alerts.get_session") as mock_session:
            session = AsyncMock()
            session.execute = AsyncMock(return_value=mock_result)
            mock_session.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            await detector._check_slippage(trade)

        send_raw.assert_called_once()
        msg = send_raw.call_args[0][0]
        assert "ANOMALY" in msg
        assert "SLIPPAGE" in msg

    @pytest.mark.asyncio
    async def test_slippage_alert_skipped_when_normal(self):
        detector, send_raw = self._make_detector()
        trade = _make_trade(slippage_pips=2.0)  # Within 2x of avg

        mock_result = MagicMock()
        mock_result.all.return_value = [(1.5,), (2.0,), (2.5,), (2.0,), (2.0,)]

        with patch("forex_bot.reporting.alerts.get_session") as mock_session:
            session = AsyncMock()
            session.execute = AsyncMock(return_value=mock_result)
            mock_session.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            await detector._check_slippage(trade)

        send_raw.assert_not_called()

    @pytest.mark.asyncio
    async def test_slippage_skipped_with_insufficient_data(self):
        detector, send_raw = self._make_detector()
        trade = _make_trade(slippage_pips=10.0)

        mock_result = MagicMock()
        mock_result.all.return_value = [(1.5,), (2.0,)]  # Only 2, need 5

        with patch("forex_bot.reporting.alerts.get_session") as mock_session:
            session = AsyncMock()
            session.execute = AsyncMock(return_value=mock_result)
            mock_session.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            await detector._check_slippage(trade)

        send_raw.assert_not_called()

    @pytest.mark.asyncio
    async def test_losing_streak_alert_fires(self):
        detector, send_raw = self._make_detector()

        # Mock 3 consecutive losses
        mock_records = [
            MagicMock(pnl=-20.0, pnl_pips=-10.0, instrument="USDZAR"),
            MagicMock(pnl=-15.0, pnl_pips=-10.0, instrument="USDTRY"),
            MagicMock(pnl=-25.0, pnl_pips=-10.0, instrument="USDZAR"),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_records

        with patch("forex_bot.reporting.alerts.get_session") as mock_session:
            session = AsyncMock()
            session.execute = AsyncMock(return_value=mock_result)
            mock_session.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            await detector._check_losing_streak()

        send_raw.assert_called_once()
        msg = send_raw.call_args[0][0]
        assert "LOSING STREAK" in msg

    @pytest.mark.asyncio
    async def test_losing_streak_not_triggered_with_win(self):
        detector, send_raw = self._make_detector()

        mock_records = [
            MagicMock(pnl=-20.0, pnl_pips=-10.0, instrument="USDZAR"),
            MagicMock(pnl=30.0, pnl_pips=15.0, instrument="USDTRY"),  # A win
            MagicMock(pnl=-25.0, pnl_pips=-10.0, instrument="USDZAR"),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_records

        with patch("forex_bot.reporting.alerts.get_session") as mock_session:
            session = AsyncMock()
            session.execute = AsyncMock(return_value=mock_result)
            mock_session.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            await detector._check_losing_streak()

        send_raw.assert_not_called()
