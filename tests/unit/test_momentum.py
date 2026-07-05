"""Unit tests for the currency momentum strategy."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forex_bot.broker.exceptions import DataError, OrderError
from forex_bot.models.account import AccountSummary
from forex_bot.models.market import PriceSnapshot
from forex_bot.models.orders import OrderSide
from forex_bot.strategy.momentum import MomentumManager, MomentumPosition, MomentumScore


def _bar(close: float) -> MagicMock:
    """Minimal stand-in for a Candle (only .close is read by the strategy)."""
    return MagicMock(close=close)


@pytest.fixture
def mock_settings():
    """Minimal momentum config for tests."""
    with patch("forex_bot.strategy.momentum.get_settings") as mock:
        settings = MagicMock()
        settings.momentum.enabled = True
        settings.momentum.instruments = ["EURUSD", "GBPUSD", "USDJPY"]
        settings.momentum.lookback_months = 3
        settings.momentum.min_return_pct = 2.0
        settings.momentum.max_concurrent_momentum = 4
        settings.momentum.max_risk_per_momentum_pct = 1.0
        settings.momentum.stop_loss_pct = 5.0
        settings.momentum.rebalance_day_of_week = "mon"
        settings.momentum.rebalance_hour_utc = 14
        settings.momentum.rebalance_minute = 22
        settings.momentum.max_spread_pips = 30.0
        settings.momentum.max_spread_overrides = {}
        mock.return_value = settings
        yield settings


@pytest.fixture
def momentum_manager(mock_settings):
    """Create a MomentumManager with all mocked dependencies."""
    client = AsyncMock()
    client.is_connected = True

    engine = AsyncMock()
    journal = AsyncMock()
    journal.get_open_orders_by_strategy.return_value = []

    pricing = AsyncMock()
    monitor = MagicMock()
    monitor.await_fill = AsyncMock(return_value=1.1050)
    monitor.record_exit_fill = AsyncMock()
    notifier = AsyncMock()

    return MomentumManager(
        client=client,
        execution_engine=engine,
        journal=journal,
        pricing=pricing,
        monitor=monitor,
        notifier=notifier,
    )


# --- Scoring Tests ---


class TestCalculateScores:
    def test_positive_return_buy(self, momentum_manager):
        """Positive trailing return (uptrend) → BUY (long the winner)."""
        scores = momentum_manager._calculate_scores({"EURUSD": 6.0})
        assert len(scores) == 1
        assert scores[0].pair == "EURUSD"
        assert scores[0].direction == OrderSide.BUY
        assert scores[0].trailing_return_pct == 6.0

    def test_negative_return_sell(self, momentum_manager):
        """Negative trailing return (downtrend) → SELL (short the loser)."""
        scores = momentum_manager._calculate_scores({"USDJPY": -4.0})
        assert len(scores) == 1
        assert scores[0].direction == OrderSide.SELL
        assert scores[0].trailing_return_pct == -4.0

    def test_below_threshold_filtered(self, momentum_manager):
        """Pairs whose |return| is below the threshold are excluded."""
        scores = momentum_manager._calculate_scores({"EURUSD": 1.0})  # < 2.0
        assert len(scores) == 0

    def test_sorted_by_abs_return(self, momentum_manager):
        """Scores are sorted by absolute return descending (strongest trend first)."""
        scores = momentum_manager._calculate_scores(
            {"EURUSD": 3.0, "GBPUSD": -8.0, "USDJPY": 5.0}
        )
        rets = [abs(s.trailing_return_pct) for s in scores]
        assert rets == sorted(rets, reverse=True)
        assert scores[0].pair == "GBPUSD"

    def test_max_concurrent_limits_scores(self, momentum_manager):
        """Scores are limited to max_concurrent_momentum."""
        momentum_manager._settings.max_concurrent_momentum = 1
        scores = momentum_manager._calculate_scores(
            {"EURUSD": 3.0, "GBPUSD": -8.0, "USDJPY": 5.0}
        )
        assert len(scores) == 1
        assert scores[0].pair == "GBPUSD"  # largest |return|


# --- Return Fetching Tests ---


class TestFetchReturns:
    @pytest.mark.asyncio
    async def test_computes_trailing_return(self, momentum_manager):
        """Trailing return = (last_close / first_close - 1) * 100."""
        momentum_manager._settings.instruments = ["EURUSD"]
        momentum_manager._pricing.get_historical_bars.return_value = [
            _bar(1.0000), _bar(1.0300), _bar(1.0600),
        ]
        returns = await momentum_manager._fetch_returns()
        assert returns["EURUSD"] == pytest.approx(6.0)

    @pytest.mark.asyncio
    async def test_insufficient_bars_skipped(self, momentum_manager):
        """A pair with fewer than 2 bars is skipped, not fatal."""
        momentum_manager._settings.instruments = ["EURUSD"]
        momentum_manager._pricing.get_historical_bars.return_value = [_bar(1.0)]
        returns = await momentum_manager._fetch_returns()
        assert "EURUSD" not in returns

    @pytest.mark.asyncio
    async def test_data_error_skipped(self, momentum_manager):
        """A DataError on one pair skips it without aborting the rebalance."""
        momentum_manager._settings.instruments = ["EURUSD"]
        momentum_manager._pricing.get_historical_bars.side_effect = DataError("no data")
        returns = await momentum_manager._fetch_returns()
        assert returns == {}


# --- Rebalance Tests ---


class TestRebalance:
    @pytest.mark.asyncio
    async def test_disabled_noop(self, momentum_manager):
        """Rebalance is a no-op when momentum.enabled is False."""
        momentum_manager._settings.enabled = False
        await momentum_manager.rebalance()
        momentum_manager._engine.execute_signal.assert_not_called()

    @pytest.mark.asyncio
    async def test_disconnected_skips(self, momentum_manager):
        """Rebalance skips when IB is not connected."""
        momentum_manager._client.is_connected = False
        await momentum_manager.rebalance()
        momentum_manager._engine.execute_signal.assert_not_called()

    @pytest.mark.asyncio
    async def test_enters_new_position(self, momentum_manager):
        """Rebalance enters a new momentum position for an uptrending pair."""
        momentum_manager._settings.instruments = ["EURUSD"]

        with patch.object(momentum_manager, "_fetch_returns", new_callable=AsyncMock) as mock_ret:
            mock_ret.return_value = {"EURUSD": 6.0}  # uptrend → BUY

            momentum_manager._pricing.get_snapshot.return_value = PriceSnapshot(
                instrument="EURUSD", timestamp=datetime.now(UTC),
                bid=1.1000, ask=1.1002,
            )
            momentum_manager._pricing.get_quote_to_cad_rate = AsyncMock(return_value=1.35)
            momentum_manager._client.get_account_summary = AsyncMock(
                return_value=AccountSummary(net_liquidation=5000.0),
            )

            mock_order = MagicMock()
            mock_order.ib_order_id = 100
            momentum_manager._engine.execute_signal.return_value = mock_order

            await momentum_manager.rebalance()

            momentum_manager._engine.execute_signal.assert_called_once()
            signal = momentum_manager._engine.execute_signal.call_args[0][0]
            assert signal.instrument == "EURUSD"
            assert signal.side == OrderSide.BUY
            assert signal.strategy == "momentum"
            assert signal.stop_loss is not None
            assert signal.take_profit is None

            assert "EURUSD" in momentum_manager._positions
            momentum_manager._monitor.exclude_from_holding_check.assert_called_once_with({100})

    @pytest.mark.asyncio
    async def test_closes_removed_pair(self, momentum_manager):
        """Rebalance closes a position when the pair is no longer a target."""
        momentum_manager._settings.instruments = ["EURUSD"]
        momentum_manager._positions["USDJPY"] = MagicMock(
            pair="USDJPY", side=OrderSide.SELL, ib_order_id=99,
        )

        with (
            patch.object(momentum_manager, "_fetch_returns", new_callable=AsyncMock) as mock_ret,
            patch.object(momentum_manager, "_close_position", new_callable=AsyncMock) as mock_close,
        ):
            mock_ret.return_value = {"EURUSD": 6.0}
            momentum_manager._pricing.get_snapshot.return_value = PriceSnapshot(
                instrument="EURUSD", timestamp=datetime.now(UTC), bid=1.10, ask=1.1002,
            )
            momentum_manager._pricing.get_quote_to_cad_rate = AsyncMock(return_value=1.35)
            momentum_manager._client.get_account_summary.return_value = AccountSummary(
                net_liquidation=5000.0,
            )
            mock_order = MagicMock()
            mock_order.ib_order_id = 101
            momentum_manager._engine.execute_signal.return_value = mock_order

            await momentum_manager.rebalance()

            mock_close.assert_called_once()
            assert mock_close.call_args[0][0] == "USDJPY"

    @pytest.mark.asyncio
    async def test_closes_on_direction_flip(self, momentum_manager):
        """Rebalance closes a position when the trend direction flips."""
        momentum_manager._settings.instruments = ["EURUSD"]
        momentum_manager._positions["EURUSD"] = MagicMock(
            pair="EURUSD", side=OrderSide.SELL, ib_order_id=50,
        )

        with (
            patch.object(momentum_manager, "_fetch_returns", new_callable=AsyncMock) as mock_ret,
            patch.object(momentum_manager, "_close_position", new_callable=AsyncMock) as mock_close,
        ):
            mock_ret.return_value = {"EURUSD": 6.0}  # now uptrend → want BUY
            momentum_manager._pricing.get_snapshot.return_value = PriceSnapshot(
                instrument="EURUSD", timestamp=datetime.now(UTC), bid=1.10, ask=1.1002,
            )
            momentum_manager._pricing.get_quote_to_cad_rate = AsyncMock(return_value=1.35)
            momentum_manager._client.get_account_summary.return_value = AccountSummary(
                net_liquidation=5000.0,
            )
            mock_order = MagicMock()
            mock_order.ib_order_id = 102
            momentum_manager._engine.execute_signal.return_value = mock_order

            await momentum_manager.rebalance()

            mock_close.assert_called_once()
            assert mock_close.call_args[0][2] == "direction flipped"

    @pytest.mark.asyncio
    async def test_holds_matching_position(self, momentum_manager):
        """Rebalance holds an existing position when the direction still matches."""
        momentum_manager._settings.instruments = ["EURUSD"]
        momentum_manager._positions["EURUSD"] = MagicMock(
            pair="EURUSD", side=OrderSide.BUY, ib_order_id=50,
        )

        with patch.object(momentum_manager, "_fetch_returns", new_callable=AsyncMock) as mock_ret:
            mock_ret.return_value = {"EURUSD": 6.0}  # uptrend → BUY (unchanged)
            await momentum_manager.rebalance()
            momentum_manager._engine.execute_signal.assert_not_called()


# --- Signal Building Tests ---


def _score(pair="EURUSD", ret=6.0, direction=OrderSide.BUY) -> MomentumScore:
    return MomentumScore(
        pair=pair, trailing_return_pct=ret, direction=direction, lookback_months=3,
    )


class TestBuildEntrySignal:
    def test_signal_has_momentum_strategy(self, momentum_manager):
        signal = momentum_manager._build_entry_signal(_score(), 1.10, 5000.0, 1)
        assert signal.strategy == "momentum"

    def test_buy_stop_loss_below_entry(self, momentum_manager):
        signal = momentum_manager._build_entry_signal(
            _score(direction=OrderSide.BUY), 1.10, 5000.0, 1,
        )
        assert signal.stop_loss < 1.10

    def test_sell_stop_loss_above_entry(self, momentum_manager):
        signal = momentum_manager._build_entry_signal(
            _score(ret=-6.0, direction=OrderSide.SELL), 1.10, 5000.0, 1,
        )
        assert signal.stop_loss > 1.10

    def test_no_take_profit(self, momentum_manager):
        signal = momentum_manager._build_entry_signal(_score(), 1.10, 5000.0, 1)
        assert signal.take_profit is None

    def test_small_position_size_odd_lot(self, momentum_manager):
        """IDEALPRO accepts odd lots — no 25K floor needed."""
        signal = momentum_manager._build_entry_signal(
            _score(), 1.10, 100.0, 4, quote_to_cad=1.35,
        )
        assert signal.quantity >= 1
        assert signal.quantity < 25000

    def test_quote_to_cad_affects_sizing(self, momentum_manager):
        sig_low = momentum_manager._build_entry_signal(_score(), 1.10, 5000.0, 1, quote_to_cad=0.5)
        sig_high = momentum_manager._build_entry_signal(_score(), 1.10, 5000.0, 1, quote_to_cad=1.35)
        # Lower quote_to_cad means cheaper pips → larger position
        assert sig_low.quantity > sig_high.quantity


# --- State Management Tests ---


class TestStateManagement:
    def test_get_momentum_order_ids(self, momentum_manager):
        momentum_manager._positions = {
            "EURUSD": MagicMock(ib_order_id=100),
            "USDJPY": MagicMock(ib_order_id=200),
        }
        assert momentum_manager.get_momentum_order_ids() == {100, 200}

    def test_get_active_currencies(self, momentum_manager):
        momentum_manager._positions = {"EURUSD": MagicMock(), "USDJPY": MagicMock()}
        currencies = momentum_manager.get_active_currencies()
        assert {"EUR", "USD", "JPY"} <= currencies
        assert "CAD" not in currencies

    @pytest.mark.asyncio
    async def test_restore_state(self, momentum_manager):
        mock_order = MagicMock()
        mock_order.instrument = "EURUSD"
        mock_order.side = "BUY"
        mock_order.price = 1.10
        mock_order.quantity = 1000
        mock_order.stop_loss = 1.045
        mock_order.ib_order_id = 100
        mock_order.created_at = datetime.now(UTC)

        momentum_manager._journal.get_open_orders_by_strategy.return_value = [mock_order]
        await momentum_manager.restore_state()

        assert "EURUSD" in momentum_manager._positions
        assert momentum_manager._positions["EURUSD"].ib_order_id == 100


# --- Close Position Tests ---


class TestClosePosition:
    @pytest.mark.asyncio
    async def test_close_buy_cancels_sl_and_sells(self, momentum_manager):
        """Closing a BUY position cancels the SL child and places a SELL order."""
        pos = MomentumPosition(
            pair="EURUSD", side=OrderSide.BUY, entry_price=1.10,
            quantity=1000, stop_loss=1.045, ib_order_id=100,
            opened_at=datetime.now(UTC),
        )
        momentum_manager._positions["EURUSD"] = pos

        sl_trade = MagicMock()
        sl_trade.order.parentId = 100

        with patch("forex_bot.strategy.momentum.OrderService") as MockOS:
            mock_svc = AsyncMock()
            mock_svc.get_open_trades.return_value = [sl_trade]
            MockOS.return_value = mock_svc

            await momentum_manager._close_position("EURUSD", pos, "test")

            mock_svc.place_order.assert_called_once()
            close_order = mock_svc.place_order.call_args[0][0]
            assert close_order.instrument == "EURUSD"
            assert close_order.side == OrderSide.SELL
            assert close_order.quantity == 1000
            mock_svc.cancel_order.assert_called_once_with(sl_trade)
            momentum_manager._monitor.record_exit_fill.assert_awaited_once_with(100, 1.1050)
            assert "EURUSD" not in momentum_manager._positions

    @pytest.mark.asyncio
    async def test_close_failure_keeps_position_tracked(self, momentum_manager):
        """If the flatten order fails, the position stays tracked and its SL
        is NOT cancelled."""
        pos = MomentumPosition(
            pair="EURUSD", side=OrderSide.BUY, entry_price=1.10,
            quantity=1000, stop_loss=1.045, ib_order_id=100,
            opened_at=datetime.now(UTC),
        )
        momentum_manager._positions["EURUSD"] = pos

        with patch("forex_bot.strategy.momentum.OrderService") as MockOS:
            mock_svc = AsyncMock()
            mock_svc.place_order.side_effect = OrderError("IB error")
            MockOS.return_value = mock_svc

            await momentum_manager._close_position("EURUSD", pos, "test")

            assert "EURUSD" in momentum_manager._positions
            mock_svc.cancel_order.assert_not_called()
            momentum_manager._monitor.record_exit_fill.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_close_fill_timeout_keeps_position_and_sl(self, momentum_manager):
        """If the flatten order never fills, the position and SL stay in place."""
        pos = MomentumPosition(
            pair="EURUSD", side=OrderSide.BUY, entry_price=1.10,
            quantity=1000, stop_loss=1.045, ib_order_id=100,
            opened_at=datetime.now(UTC),
        )
        momentum_manager._positions["EURUSD"] = pos
        momentum_manager._monitor.await_fill = AsyncMock(return_value=None)

        with patch("forex_bot.strategy.momentum.OrderService") as MockOS:
            mock_svc = AsyncMock()
            MockOS.return_value = mock_svc

            await momentum_manager._close_position("EURUSD", pos, "test")

            assert "EURUSD" in momentum_manager._positions
            mock_svc.cancel_order.assert_not_called()
