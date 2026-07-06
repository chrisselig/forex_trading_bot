"""Unit tests for the value / PPP strategy."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forex_bot.broker.exceptions import OrderError
from forex_bot.models.account import AccountSummary
from forex_bot.models.market import PriceSnapshot
from forex_bot.models.orders import OrderSide
from forex_bot.strategy.value import ValueManager, ValuePosition, ValueScore


def _months(n: int, start: tuple[int, int] = (2020, 1)) -> list[tuple[int, int]]:
    y, m = start
    out = []
    for _ in range(n):
        out.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def _series(values: list[float]) -> dict[tuple[int, int], float]:
    return dict(zip(_months(len(values)), values, strict=True))


@pytest.fixture
def mock_settings():
    with patch("forex_bot.strategy.value.get_settings") as mock:
        settings = MagicMock()
        settings.value.enabled = True
        settings.value.instruments = ["EURUSD", "GBPUSD", "USDJPY"]
        settings.value.lookback_years = 8
        settings.value.z_threshold = 1.0
        settings.value.max_concurrent_value = 4
        settings.value.max_risk_per_value_pct = 1.0
        settings.value.stop_loss_pct = 8.0
        settings.value.rebalance_day_of_month = 1
        settings.value.rebalance_hour_utc = 14
        settings.value.rebalance_minute = 37
        settings.value.max_spread_pips = 20.0
        settings.value.max_spread_overrides = {}
        mock.return_value = settings
        yield settings


@pytest.fixture
def value_manager(mock_settings):
    client = AsyncMock()
    client.is_connected = True
    journal = AsyncMock()
    journal.get_open_orders_by_strategy.return_value = []
    monitor = MagicMock()
    monitor.await_fill = AsyncMock(return_value=1.1000)
    monitor.record_exit_fill = AsyncMock()
    return ValueManager(
        client=client,
        execution_engine=AsyncMock(),
        journal=journal,
        pricing=AsyncMock(),
        monitor=monitor,
        notifier=AsyncMock(),
    )


# --- Valuation (real-exchange-rate z-score) tests ---


class TestComputeValuations:
    @pytest.mark.asyncio
    async def test_overvalued_sells(self, value_manager):
        """RER far above its mean → base overvalued → SELL."""
        value_manager._settings.instruments = ["EURUSD"]
        value_manager._fetch_cpi = AsyncMock(return_value=_series([100.0] * 30))
        value_manager._fetch_monthly_nominal = AsyncMock(
            return_value=_series([1.10] * 29 + [1.30])
        )
        scores = await value_manager._compute_valuations()
        assert len(scores) == 1
        assert scores[0].direction == OrderSide.SELL
        assert scores[0].z_score > 1.0
        assert scores[0].deviation_pct > 0

    @pytest.mark.asyncio
    async def test_undervalued_buys(self, value_manager):
        """RER far below its mean → base undervalued → BUY."""
        value_manager._settings.instruments = ["EURUSD"]
        value_manager._fetch_cpi = AsyncMock(return_value=_series([100.0] * 30))
        value_manager._fetch_monthly_nominal = AsyncMock(
            return_value=_series([1.10] * 29 + [0.90])
        )
        scores = await value_manager._compute_valuations()
        assert len(scores) == 1
        assert scores[0].direction == OrderSide.BUY
        assert scores[0].z_score < -1.0

    @pytest.mark.asyncio
    async def test_within_threshold_filtered(self, value_manager):
        """With realistic variance, a value at the long-run mean → z≈0 → skipped."""
        value_manager._settings.instruments = ["EURUSD"]
        # Spread series (std ~0.05) whose last point sits at the mean → tiny z
        spread = ([1.05, 1.15] * 15)[:29] + [1.10]
        value_manager._fetch_cpi = AsyncMock(return_value=_series([100.0] * 30))
        value_manager._fetch_monthly_nominal = AsyncMock(return_value=_series(spread))
        scores = await value_manager._compute_valuations()
        assert scores == []

    @pytest.mark.asyncio
    async def test_insufficient_history_skipped(self, value_manager):
        """Fewer than MIN_MONTHS aligned points → skip the pair."""
        value_manager._settings.instruments = ["EURUSD"]
        value_manager._fetch_cpi = AsyncMock(return_value=_series([100.0] * 10))
        value_manager._fetch_monthly_nominal = AsyncMock(
            return_value=_series([1.10] * 9 + [1.30])
        )
        scores = await value_manager._compute_valuations()
        assert scores == []

    @pytest.mark.asyncio
    async def test_missing_cpi_skipped(self, value_manager):
        """No CPI for a currency → skip, don't crash."""
        value_manager._settings.instruments = ["EURUSD"]
        value_manager._fetch_cpi = AsyncMock(return_value=None)
        value_manager._fetch_monthly_nominal = AsyncMock(return_value=_series([1.1] * 30))
        scores = await value_manager._compute_valuations()
        assert scores == []

    @pytest.mark.asyncio
    async def test_relative_cpi_shifts_rer(self, value_manager):
        """Higher base inflation raises the RER even with flat nominal price."""
        value_manager._settings.instruments = ["EURUSD"]
        # Flat nominal; base CPI ramps up at the end → RER rises → SELL
        rising = [100.0] * 29 + [140.0]
        flat = [100.0] * 30

        async def cpi(cur):
            return _series(rising) if cur == "EUR" else _series(flat)

        value_manager._fetch_cpi = AsyncMock(side_effect=cpi)
        value_manager._fetch_monthly_nominal = AsyncMock(return_value=_series([1.10] * 30))
        scores = await value_manager._compute_valuations()
        assert len(scores) == 1
        assert scores[0].direction == OrderSide.SELL

    @pytest.mark.asyncio
    async def test_ranked_and_capped(self, value_manager):
        """Scores are ranked by |z| and capped at max_concurrent_value."""
        value_manager._settings.instruments = ["EURUSD", "GBPUSD", "USDJPY"]
        value_manager._settings.max_concurrent_value = 2
        value_manager._fetch_cpi = AsyncMock(return_value=_series([100.0] * 30))

        async def nominal(pair):
            last = {"EURUSD": 1.30, "GBPUSD": 1.50, "USDJPY": 1.05}[pair]
            base = {"EURUSD": 1.10, "GBPUSD": 1.10, "USDJPY": 1.00}[pair]
            return _series([base] * 29 + [last])

        value_manager._fetch_monthly_nominal = AsyncMock(side_effect=nominal)
        scores = await value_manager._compute_valuations()
        assert len(scores) == 2  # capped
        zs = [abs(s.z_score) for s in scores]
        assert zs == sorted(zs, reverse=True)


# --- Rebalance tests ---


class TestRebalance:
    @pytest.mark.asyncio
    async def test_disabled_noop(self, value_manager):
        value_manager._settings.enabled = False
        await value_manager.rebalance()
        value_manager._engine.execute_signal.assert_not_called()

    @pytest.mark.asyncio
    async def test_disconnected_skips(self, value_manager):
        value_manager._client.is_connected = False
        await value_manager.rebalance()
        value_manager._engine.execute_signal.assert_not_called()

    @pytest.mark.asyncio
    async def test_enters_new_position(self, value_manager):
        score = ValueScore(
            pair="EURUSD", real_exchange_rate=0.9, mean_rer=1.1,
            z_score=-1.8, deviation_pct=-18.0, direction=OrderSide.BUY,
        )
        with patch.object(value_manager, "_compute_valuations", new_callable=AsyncMock) as mv:
            mv.return_value = [score]
            value_manager._pricing.get_snapshot.return_value = PriceSnapshot(
                instrument="EURUSD", timestamp=datetime.now(UTC), bid=1.10, ask=1.1002,
            )
            value_manager._pricing.get_quote_to_cad_rate = AsyncMock(return_value=1.35)
            value_manager._client.get_account_summary = AsyncMock(
                return_value=AccountSummary(net_liquidation=5000.0),
            )
            order = MagicMock()
            order.ib_order_id = 100
            value_manager._engine.execute_signal.return_value = order

            await value_manager.rebalance()

            signal = value_manager._engine.execute_signal.call_args[0][0]
            assert signal.instrument == "EURUSD"
            assert signal.side == OrderSide.BUY
            assert signal.strategy == "value"
            assert signal.take_profit is None
            assert "EURUSD" in value_manager._positions
            value_manager._monitor.exclude_from_holding_check.assert_called_once_with({100})

    @pytest.mark.asyncio
    async def test_closes_reverted_pair(self, value_manager):
        value_manager._positions["USDJPY"] = MagicMock(
            pair="USDJPY", side=OrderSide.SELL, ib_order_id=99,
        )
        with (
            patch.object(value_manager, "_compute_valuations", new_callable=AsyncMock) as mv,
            patch.object(value_manager, "_close_position", new_callable=AsyncMock) as mc,
        ):
            mv.return_value = []  # nothing mis-valued now → close everything
            await value_manager.rebalance()
            mc.assert_called_once()
            assert mc.call_args[0][0] == "USDJPY"
            assert mc.call_args[0][2] == "reverted to fair value"

    @pytest.mark.asyncio
    async def test_closes_on_direction_flip(self, value_manager):
        value_manager._positions["EURUSD"] = MagicMock(
            pair="EURUSD", side=OrderSide.SELL, ib_order_id=50,
        )
        flip = ValueScore(
            pair="EURUSD", real_exchange_rate=0.9, mean_rer=1.1,
            z_score=-1.8, deviation_pct=-18.0, direction=OrderSide.BUY,
        )
        with (
            patch.object(value_manager, "_compute_valuations", new_callable=AsyncMock) as mv,
            patch.object(value_manager, "_close_position", new_callable=AsyncMock) as mc,
        ):
            mv.return_value = [flip]
            value_manager._pricing.get_snapshot.return_value = PriceSnapshot(
                instrument="EURUSD", timestamp=datetime.now(UTC), bid=1.10, ask=1.1002,
            )
            value_manager._pricing.get_quote_to_cad_rate = AsyncMock(return_value=1.35)
            value_manager._client.get_account_summary.return_value = AccountSummary(
                net_liquidation=5000.0,
            )
            order = MagicMock()
            order.ib_order_id = 51
            value_manager._engine.execute_signal.return_value = order

            await value_manager.rebalance()
            mc.assert_called_once()
            assert mc.call_args[0][2] == "direction flipped"

    @pytest.mark.asyncio
    async def test_holds_matching_position(self, value_manager):
        value_manager._positions["EURUSD"] = MagicMock(
            pair="EURUSD", side=OrderSide.BUY, ib_order_id=50,
        )
        score = ValueScore(
            pair="EURUSD", real_exchange_rate=0.9, mean_rer=1.1,
            z_score=-1.8, deviation_pct=-18.0, direction=OrderSide.BUY,
        )
        with patch.object(value_manager, "_compute_valuations", new_callable=AsyncMock) as mv:
            mv.return_value = [score]
            await value_manager.rebalance()
            value_manager._engine.execute_signal.assert_not_called()


# --- Signal building tests ---


def _score(direction=OrderSide.BUY, z=-1.8) -> ValueScore:
    return ValueScore(
        pair="EURUSD", real_exchange_rate=0.9, mean_rer=1.1,
        z_score=z, deviation_pct=-18.0, direction=direction,
    )


class TestBuildEntrySignal:
    def test_strategy_tagged_value(self, value_manager):
        sig = value_manager._build_entry_signal(_score(), 1.10, 5000.0, 1)
        assert sig.strategy == "value"

    def test_buy_stop_below(self, value_manager):
        sig = value_manager._build_entry_signal(_score(OrderSide.BUY), 1.10, 5000.0, 1)
        assert sig.stop_loss < 1.10

    def test_sell_stop_above(self, value_manager):
        sig = value_manager._build_entry_signal(_score(OrderSide.SELL, z=1.8), 1.10, 5000.0, 1)
        assert sig.stop_loss > 1.10

    def test_no_take_profit(self, value_manager):
        sig = value_manager._build_entry_signal(_score(), 1.10, 5000.0, 1)
        assert sig.take_profit is None

    def test_quote_to_cad_affects_sizing(self, value_manager):
        low = value_manager._build_entry_signal(_score(), 1.10, 5000.0, 1, quote_to_cad=0.5)
        high = value_manager._build_entry_signal(_score(), 1.10, 5000.0, 1, quote_to_cad=1.35)
        assert low.quantity > high.quantity


# --- State management tests ---


class TestStateManagement:
    def test_get_value_order_ids(self, value_manager):
        value_manager._positions = {
            "EURUSD": MagicMock(ib_order_id=100),
            "USDJPY": MagicMock(ib_order_id=200),
        }
        assert value_manager.get_value_order_ids() == {100, 200}

    def test_get_active_currencies(self, value_manager):
        value_manager._positions = {"EURUSD": MagicMock(), "USDJPY": MagicMock()}
        cur = value_manager.get_active_currencies()
        assert {"EUR", "USD", "JPY"} <= cur
        assert "CAD" not in cur

    @pytest.mark.asyncio
    async def test_restore_state(self, value_manager):
        order = MagicMock()
        order.instrument = "EURUSD"
        order.side = "BUY"
        order.price = 1.10
        order.quantity = 1000
        order.stop_loss = 1.012
        order.ib_order_id = 100
        order.created_at = datetime.now(UTC)
        value_manager._journal.get_open_orders_by_strategy.return_value = [order]
        await value_manager.restore_state()
        assert "EURUSD" in value_manager._positions
        assert value_manager._positions["EURUSD"].ib_order_id == 100


# --- Close position tests ---


class TestClosePosition:
    @pytest.mark.asyncio
    async def test_close_buy_cancels_sl_and_sells(self, value_manager):
        pos = ValuePosition(
            pair="EURUSD", side=OrderSide.BUY, entry_price=1.10,
            quantity=1000, stop_loss=1.012, ib_order_id=100,
            opened_at=datetime.now(UTC),
        )
        value_manager._positions["EURUSD"] = pos
        sl_trade = MagicMock()
        sl_trade.order.parentId = 100
        with patch("forex_bot.strategy.value.OrderService") as MockOS:
            svc = AsyncMock()
            svc.get_open_trades.return_value = [sl_trade]
            MockOS.return_value = svc
            await value_manager._close_position("EURUSD", pos, "test")
            close_order = svc.place_order.call_args[0][0]
            assert close_order.side == OrderSide.SELL
            assert close_order.quantity == 1000
            svc.cancel_order.assert_called_once_with(sl_trade)
            value_manager._monitor.record_exit_fill.assert_awaited_once_with(100, 1.1000)
            assert "EURUSD" not in value_manager._positions

    @pytest.mark.asyncio
    async def test_close_failure_keeps_position(self, value_manager):
        pos = ValuePosition(
            pair="EURUSD", side=OrderSide.BUY, entry_price=1.10,
            quantity=1000, stop_loss=1.012, ib_order_id=100,
            opened_at=datetime.now(UTC),
        )
        value_manager._positions["EURUSD"] = pos
        with patch("forex_bot.strategy.value.OrderService") as MockOS:
            svc = AsyncMock()
            svc.place_order.side_effect = OrderError("IB error")
            MockOS.return_value = svc
            await value_manager._close_position("EURUSD", pos, "test")
            assert "EURUSD" in value_manager._positions
            svc.cancel_order.assert_not_called()
            value_manager._monitor.record_exit_fill.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_close_fill_timeout_keeps_position(self, value_manager):
        pos = ValuePosition(
            pair="EURUSD", side=OrderSide.BUY, entry_price=1.10,
            quantity=1000, stop_loss=1.012, ib_order_id=100,
            opened_at=datetime.now(UTC),
        )
        value_manager._positions["EURUSD"] = pos
        value_manager._monitor.await_fill = AsyncMock(return_value=None)
        with patch("forex_bot.strategy.value.OrderService") as MockOS:
            svc = AsyncMock()
            MockOS.return_value = svc
            await value_manager._close_position("EURUSD", pos, "test")
            assert "EURUSD" in value_manager._positions
            svc.cancel_order.assert_not_called()
