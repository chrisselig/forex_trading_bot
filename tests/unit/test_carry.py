"""Unit tests for carry trade strategy."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forex_bot.models.account import AccountSummary
from forex_bot.models.market import PriceSnapshot
from forex_bot.models.orders import OrderSide
from forex_bot.strategy.carry import CarryManager, CarryPosition, CarryScore


@pytest.fixture
def mock_settings():
    """Minimal carry config for tests."""
    with patch("forex_bot.strategy.carry.get_settings") as mock:
        settings = MagicMock()
        settings.carry.enabled = True
        settings.carry.instruments = ["USDZAR", "USDTRY", "AUDJPY"]
        settings.carry.min_differential_pct = 2.0
        settings.carry.risk_budget_pct = 5.0
        settings.carry.max_concurrent_carry = 5
        settings.carry.max_risk_per_carry_pct = 1.5
        settings.carry.stop_loss_pct = 5.0
        settings.carry.rebalance_day_of_week = "sun"
        settings.carry.rebalance_hour_utc = 14
        settings.carry.fallback_rates = {"TRY": 50.0}
        settings.carry.max_spread_pips = 30.0
        settings.carry.max_spread_overrides = {}
        mock.return_value = settings
        yield settings


@pytest.fixture
def carry_manager(mock_settings):
    """Create a CarryManager with all mocked dependencies."""
    client = AsyncMock()
    client.is_connected = True

    engine = AsyncMock()
    journal = AsyncMock()
    journal.get_open_orders_by_strategy.return_value = []

    pricing = AsyncMock()
    monitor = MagicMock()
    notifier = AsyncMock()

    return CarryManager(
        client=client,
        execution_engine=engine,
        journal=journal,
        pricing=pricing,
        monitor=monitor,
        notifier=notifier,
    )


# --- Scoring Tests ---


class TestCalculateScores:
    def test_positive_diff_sell(self, carry_manager):
        """Positive differential (quote > base) → SELL pair."""
        rates = {"USD": 5.0, "ZAR": 8.0}
        scores = carry_manager._calculate_scores(rates)
        assert len(scores) == 1
        assert scores[0].pair == "USDZAR"
        assert scores[0].direction == OrderSide.SELL
        assert scores[0].differential == 3.0

    def test_negative_diff_buy(self, carry_manager):
        """Negative differential (base > quote) → BUY pair."""
        rates = {"USD": 5.0, "ZAR": 2.0}
        scores = carry_manager._calculate_scores(rates)
        assert len(scores) == 1
        assert scores[0].pair == "USDZAR"
        assert scores[0].direction == OrderSide.BUY
        assert scores[0].differential == -3.0

    def test_below_threshold_filtered(self, carry_manager):
        """Pairs with differential below threshold are excluded."""
        rates = {"USD": 5.0, "ZAR": 6.0}  # diff = 1.0, below 2.0 threshold
        scores = carry_manager._calculate_scores(rates)
        assert len(scores) == 0

    def test_missing_rate_skipped(self, carry_manager):
        """Pairs with missing currency rates are skipped."""
        rates = {"USD": 5.0}  # No ZAR, TRY, AUD, JPY
        scores = carry_manager._calculate_scores(rates)
        assert len(scores) == 0

    def test_sorted_by_abs_differential(self, carry_manager):
        """Scores sorted by absolute differential descending."""
        rates = {"USD": 5.0, "ZAR": 8.0, "TRY": 50.0, "AUD": 4.0, "JPY": 0.1}
        scores = carry_manager._calculate_scores(rates)
        diffs = [abs(s.differential) for s in scores]
        assert diffs == sorted(diffs, reverse=True)

    def test_max_concurrent_limits_scores(self, carry_manager):
        """Scores limited to max_concurrent_carry."""
        carry_manager._settings.max_concurrent_carry = 1
        rates = {"USD": 5.0, "ZAR": 8.0, "TRY": 50.0}
        scores = carry_manager._calculate_scores(rates)
        assert len(scores) == 1
        assert scores[0].pair == "USDTRY"  # Highest diff

    def test_rate_source_fallback(self, carry_manager):
        """Source tagged as 'fallback' when using fallback rates."""
        rates = {"USD": 5.0, "TRY": 50.0}
        scores = carry_manager._calculate_scores(rates)
        assert len(scores) == 1
        assert scores[0].rate_source == "fallback"


# --- Rate Fetching Tests ---


class TestFetchRates:
    @pytest.mark.asyncio
    async def test_fallback_when_fred_unavailable(self, carry_manager):
        """TRY uses fallback rate when no FRED series exists."""
        carry_manager._settings.instruments = ["USDTRY"]
        with patch.object(carry_manager, "_fetch_fred_rate", new_callable=AsyncMock) as mock_fred:
            mock_fred.return_value = 5.0  # USD rate
            rates = await carry_manager._fetch_rates()
            assert "TRY" in rates
            assert rates["TRY"] == 50.0  # from fallback_rates config

    @pytest.mark.asyncio
    async def test_fred_failure_falls_back(self, carry_manager):
        """When FRED raises, falls back to config value if available."""
        carry_manager._settings.instruments = ["USDTRY"]
        with patch.object(carry_manager, "_fetch_fred_rate", new_callable=AsyncMock) as mock_fred:
            mock_fred.side_effect = Exception("FRED down")
            carry_manager._settings.fallback_rates = {"TRY": 50.0, "USD": 5.0}
            rates = await carry_manager._fetch_rates()
            assert rates.get("USD") == 5.0
            assert rates.get("TRY") == 50.0


# --- Rebalance Tests ---


class TestRebalance:
    @pytest.mark.asyncio
    async def test_disabled_noop(self, carry_manager):
        """Rebalance is a no-op when carry.enabled is False."""
        carry_manager._settings.enabled = False
        await carry_manager.rebalance()
        carry_manager._engine.execute_signal.assert_not_called()

    @pytest.mark.asyncio
    async def test_disconnected_skips(self, carry_manager):
        """Rebalance skips when IB is not connected."""
        carry_manager._client.is_connected = False
        await carry_manager.rebalance()
        carry_manager._engine.execute_signal.assert_not_called()

    @pytest.mark.asyncio
    async def test_enters_new_position(self, carry_manager):
        """Rebalance enters a new carry position."""
        carry_manager._settings.instruments = ["USDZAR"]

        with patch.object(carry_manager, "_fetch_rates", new_callable=AsyncMock) as mock_rates:
            mock_rates.return_value = {"USD": 5.0, "ZAR": 8.0}

            price = PriceSnapshot(
                instrument="USDZAR", timestamp=datetime.now(UTC),
                bid=18.5000, ask=18.5100,
            )
            carry_manager._pricing.get_snapshot.return_value = price
            carry_manager._pricing.get_quote_to_cad_rate = AsyncMock(return_value=0.075)
            carry_manager._client.get_account_summary = AsyncMock(
                return_value=AccountSummary(net_liquidation=5000.0),
            )

            mock_order = MagicMock()
            mock_order.ib_order_id = 100
            carry_manager._engine.execute_signal.return_value = mock_order

            await carry_manager.rebalance()

            carry_manager._engine.execute_signal.assert_called_once()
            signal = carry_manager._engine.execute_signal.call_args[0][0]
            assert signal.instrument == "USDZAR"
            assert signal.side == OrderSide.SELL
            assert signal.strategy == "carry"
            assert signal.stop_loss is not None
            assert signal.take_profit is None

            assert "USDZAR" in carry_manager._positions
            carry_manager._monitor.exclude_from_holding_check.assert_called_once_with({100})

    @pytest.mark.asyncio
    async def test_closes_removed_pair(self, carry_manager):
        """Rebalance closes a position when pair is no longer a target."""
        carry_manager._settings.instruments = ["USDZAR"]
        carry_manager._positions["USDTRY"] = MagicMock(
            pair="USDTRY", side=OrderSide.SELL, ib_order_id=99,
        )

        with (
            patch.object(carry_manager, "_fetch_rates", new_callable=AsyncMock) as mock_rates,
            patch.object(carry_manager, "_close_position", new_callable=AsyncMock) as mock_close,
        ):
            mock_rates.return_value = {"USD": 5.0, "ZAR": 8.0}
            carry_manager._pricing.get_snapshot.return_value = PriceSnapshot(
                instrument="USDZAR", timestamp=datetime.now(UTC),
                bid=18.5, ask=18.51,
            )
            carry_manager._pricing.get_quote_to_cad_rate = AsyncMock(return_value=0.075)
            carry_manager._client.get_account_summary.return_value = AccountSummary(
                net_liquidation=5000.0,
            )
            mock_order = MagicMock()
            mock_order.ib_order_id = 101
            carry_manager._engine.execute_signal.return_value = mock_order

            await carry_manager.rebalance()

            mock_close.assert_called_once()
            assert mock_close.call_args[0][0] == "USDTRY"

    @pytest.mark.asyncio
    async def test_closes_on_direction_flip(self, carry_manager):
        """Rebalance closes position when direction flips."""
        carry_manager._settings.instruments = ["USDZAR"]
        carry_manager._positions["USDZAR"] = MagicMock(
            pair="USDZAR", side=OrderSide.BUY, ib_order_id=50,
        )

        with (
            patch.object(carry_manager, "_fetch_rates", new_callable=AsyncMock) as mock_rates,
            patch.object(carry_manager, "_close_position", new_callable=AsyncMock) as mock_close,
        ):
            mock_rates.return_value = {"USD": 5.0, "ZAR": 8.0}  # diff > 0, want SELL
            carry_manager._pricing.get_snapshot.return_value = PriceSnapshot(
                instrument="USDZAR", timestamp=datetime.now(UTC),
                bid=18.5, ask=18.51,
            )
            carry_manager._pricing.get_quote_to_cad_rate = AsyncMock(return_value=0.075)
            carry_manager._client.get_account_summary.return_value = AccountSummary(
                net_liquidation=5000.0,
            )
            mock_order = MagicMock()
            mock_order.ib_order_id = 102
            carry_manager._engine.execute_signal.return_value = mock_order

            await carry_manager.rebalance()

            mock_close.assert_called_once()
            assert mock_close.call_args[0][2] == "direction flipped"

    @pytest.mark.asyncio
    async def test_holds_matching_position(self, carry_manager):
        """Rebalance holds existing position when direction matches."""
        carry_manager._settings.instruments = ["USDZAR"]
        carry_manager._positions["USDZAR"] = MagicMock(
            pair="USDZAR", side=OrderSide.SELL, ib_order_id=50,
        )

        with patch.object(carry_manager, "_fetch_rates", new_callable=AsyncMock) as mock_rates:
            mock_rates.return_value = {"USD": 5.0, "ZAR": 8.0}  # diff > 0, want SELL

            await carry_manager.rebalance()

            carry_manager._engine.execute_signal.assert_not_called()


# --- Signal Building Tests ---


class TestBuildEntrySignal:
    def test_signal_has_carry_strategy(self, carry_manager):
        """Signal strategy is tagged as 'carry'."""
        score = CarryScore(
            pair="USDZAR", base_currency="USD", quote_currency="ZAR",
            base_rate=5.0, quote_rate=8.0, differential=3.0,
            direction=OrderSide.SELL, rate_source="fred",
        )
        signal = carry_manager._build_entry_signal(score, 18.5, 5000.0, 1)
        assert signal.strategy == "carry"

    def test_sell_stop_loss_above_entry(self, carry_manager):
        """SELL carry: stop loss is above entry price."""
        score = CarryScore(
            pair="USDZAR", base_currency="USD", quote_currency="ZAR",
            base_rate=5.0, quote_rate=8.0, differential=3.0,
            direction=OrderSide.SELL, rate_source="fred",
        )
        signal = carry_manager._build_entry_signal(score, 18.5, 5000.0, 1)
        assert signal.stop_loss > 18.5

    def test_buy_stop_loss_below_entry(self, carry_manager):
        """BUY carry: stop loss is below entry price."""
        score = CarryScore(
            pair="USDZAR", base_currency="USD", quote_currency="ZAR",
            base_rate=8.0, quote_rate=5.0, differential=-3.0,
            direction=OrderSide.BUY, rate_source="fred",
        )
        signal = carry_manager._build_entry_signal(score, 18.5, 5000.0, 1)
        assert signal.stop_loss < 18.5

    def test_no_take_profit(self, carry_manager):
        """Carry signals should not have a take profit."""
        score = CarryScore(
            pair="USDZAR", base_currency="USD", quote_currency="ZAR",
            base_rate=5.0, quote_rate=8.0, differential=3.0,
            direction=OrderSide.SELL, rate_source="fred",
        )
        signal = carry_manager._build_entry_signal(score, 18.5, 5000.0, 1)
        assert signal.take_profit is None

    def test_small_position_size_fxconv(self, carry_manager):
        """FXCONV allows small positions — no 25K floor."""
        score = CarryScore(
            pair="USDZAR", base_currency="USD", quote_currency="ZAR",
            base_rate=5.0, quote_rate=8.0, differential=3.0,
            direction=OrderSide.SELL, rate_source="fred",
        )
        # Small NLV should produce small position, not 25K
        signal = carry_manager._build_entry_signal(score, 18.5, 100.0, 5, quote_to_cad=0.075)
        assert signal.quantity >= 1
        assert signal.quantity < 25000

    def test_quote_to_cad_affects_sizing(self, carry_manager):
        """quote_to_cad conversion changes position size."""
        score = CarryScore(
            pair="USDZAR", base_currency="USD", quote_currency="ZAR",
            base_rate=5.0, quote_rate=8.0, differential=3.0,
            direction=OrderSide.SELL, rate_source="fred",
        )
        sig_low = carry_manager._build_entry_signal(score, 18.5, 5000.0, 1, quote_to_cad=0.075)
        sig_high = carry_manager._build_entry_signal(score, 18.5, 5000.0, 1, quote_to_cad=1.0)
        # Lower quote_to_cad means cheaper pips → larger position
        assert sig_low.quantity > sig_high.quantity


# --- State Management Tests ---


class TestStateManagement:
    def test_get_carry_order_ids(self, carry_manager):
        """Returns set of active carry order IDs."""
        carry_manager._positions = {
            "USDZAR": MagicMock(ib_order_id=100),
            "USDTRY": MagicMock(ib_order_id=200),
        }
        assert carry_manager.get_carry_order_ids() == {100, 200}

    def test_get_active_currencies(self, carry_manager):
        """Returns currencies involved in carry positions (excludes CAD)."""
        carry_manager._positions = {
            "USDZAR": MagicMock(),
            "AUDJPY": MagicMock(),
        }
        currencies = carry_manager.get_active_currencies()
        assert "USD" in currencies
        assert "ZAR" in currencies
        assert "AUD" in currencies
        assert "JPY" in currencies
        assert "CAD" not in currencies

    @pytest.mark.asyncio
    async def test_restore_state(self, carry_manager):
        """Restore rebuilds positions from journal records."""
        mock_order = MagicMock()
        mock_order.instrument = "USDZAR"
        mock_order.side = "SELL"
        mock_order.price = 18.5
        mock_order.quantity = 25000
        mock_order.stop_loss = 19.4
        mock_order.ib_order_id = 100
        mock_order.created_at = datetime.now(UTC)

        carry_manager._journal.get_open_orders_by_strategy.return_value = [mock_order]
        await carry_manager.restore_state()

        assert "USDZAR" in carry_manager._positions
        assert carry_manager._positions["USDZAR"].ib_order_id == 100


# --- Stop Loss Monitor Tests ---


class TestCheckStopLosses:
    @pytest.mark.asyncio
    async def test_buy_sl_triggered(self, carry_manager):
        """BUY position: SL triggers when mid drops below stop_loss."""
        carry_manager._positions["USDZAR"] = CarryPosition(
            pair="USDZAR", side=OrderSide.BUY, entry_price=18.5,
            quantity=500, stop_loss=17.575, ib_order_id=100,
            opened_at=datetime.now(UTC),
        )
        carry_manager._pricing.get_snapshot.return_value = PriceSnapshot(
            instrument="USDZAR", timestamp=datetime.now(UTC),
            bid=17.50, ask=17.52,  # mid=17.51, below SL=17.575
        )

        with patch.object(carry_manager, "_close_position", new_callable=AsyncMock) as mock_close:
            await carry_manager.check_stop_losses()
            mock_close.assert_called_once()
            assert mock_close.call_args[0][0] == "USDZAR"
            assert mock_close.call_args[0][2] == "stop loss triggered"

    @pytest.mark.asyncio
    async def test_sell_sl_triggered(self, carry_manager):
        """SELL position: SL triggers when mid rises above stop_loss."""
        carry_manager._positions["USDZAR"] = CarryPosition(
            pair="USDZAR", side=OrderSide.SELL, entry_price=18.5,
            quantity=500, stop_loss=19.425, ib_order_id=100,
            opened_at=datetime.now(UTC),
        )
        carry_manager._pricing.get_snapshot.return_value = PriceSnapshot(
            instrument="USDZAR", timestamp=datetime.now(UTC),
            bid=19.50, ask=19.52,  # mid=19.51, above SL=19.425
        )

        with patch.object(carry_manager, "_close_position", new_callable=AsyncMock) as mock_close:
            await carry_manager.check_stop_losses()
            mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_trigger_within_range(self, carry_manager):
        """No SL trigger when price is within range."""
        carry_manager._positions["USDZAR"] = CarryPosition(
            pair="USDZAR", side=OrderSide.BUY, entry_price=18.5,
            quantity=500, stop_loss=17.575, ib_order_id=100,
            opened_at=datetime.now(UTC),
        )
        carry_manager._pricing.get_snapshot.return_value = PriceSnapshot(
            instrument="USDZAR", timestamp=datetime.now(UTC),
            bid=18.40, ask=18.42,  # mid=18.41, above SL=17.575
        )

        with patch.object(carry_manager, "_close_position", new_callable=AsyncMock) as mock_close:
            await carry_manager.check_stop_losses()
            mock_close.assert_not_called()

    @pytest.mark.asyncio
    async def test_pricing_failure_handled(self, carry_manager):
        """Pricing failure doesn't crash the monitor."""
        carry_manager._positions["USDZAR"] = CarryPosition(
            pair="USDZAR", side=OrderSide.BUY, entry_price=18.5,
            quantity=500, stop_loss=17.575, ib_order_id=100,
            opened_at=datetime.now(UTC),
        )
        carry_manager._pricing.get_snapshot.side_effect = Exception("no price")

        # Should not raise
        await carry_manager.check_stop_losses()
        assert "USDZAR" in carry_manager._positions  # Position kept

    @pytest.mark.asyncio
    async def test_empty_positions_noop(self, carry_manager):
        """No-op when no positions exist."""
        await carry_manager.check_stop_losses()
        carry_manager._pricing.get_snapshot.assert_not_called()

    @pytest.mark.asyncio
    async def test_disconnected_noop(self, carry_manager):
        """No-op when IB is disconnected."""
        carry_manager._client.is_connected = False
        carry_manager._positions["USDZAR"] = CarryPosition(
            pair="USDZAR", side=OrderSide.BUY, entry_price=18.5,
            quantity=500, stop_loss=17.575, ib_order_id=100,
            opened_at=datetime.now(UTC),
        )
        await carry_manager.check_stop_losses()
        carry_manager._pricing.get_snapshot.assert_not_called()

    @pytest.mark.asyncio
    async def test_sl_sends_telegram(self, carry_manager):
        """SL trigger sends Telegram notification."""
        carry_manager._positions["USDZAR"] = CarryPosition(
            pair="USDZAR", side=OrderSide.BUY, entry_price=18.5,
            quantity=500, stop_loss=17.575, ib_order_id=100,
            opened_at=datetime.now(UTC),
        )
        carry_manager._pricing.get_snapshot.return_value = PriceSnapshot(
            instrument="USDZAR", timestamp=datetime.now(UTC),
            bid=17.50, ask=17.52,
        )

        with patch.object(carry_manager, "_close_position", new_callable=AsyncMock):
            await carry_manager.check_stop_losses()
            carry_manager._notifier.send_raw.assert_called_once()
            msg = carry_manager._notifier.send_raw.call_args[0][0]
            assert "CARRY STOP LOSS" in msg


# --- FXCONV Close Tests ---


class TestClosePosition:
    @pytest.mark.asyncio
    async def test_close_buy_places_sell(self, carry_manager):
        """Closing a BUY position places a SELL FXCONV order."""
        pos = CarryPosition(
            pair="USDZAR", side=OrderSide.BUY, entry_price=18.5,
            quantity=500, stop_loss=17.575, ib_order_id=100,
            opened_at=datetime.now(UTC),
        )
        carry_manager._positions["USDZAR"] = pos

        with patch("forex_bot.strategy.carry.OrderService") as MockOS:
            mock_svc = AsyncMock()
            MockOS.return_value = mock_svc

            await carry_manager._close_position("USDZAR", pos, "test")

            mock_svc.place_fxconv_order.assert_called_once_with(
                instrument="USDZAR", side=OrderSide.SELL, quantity=500,
            )
            assert "USDZAR" not in carry_manager._positions

    @pytest.mark.asyncio
    async def test_close_sell_places_buy(self, carry_manager):
        """Closing a SELL position places a BUY FXCONV order."""
        pos = CarryPosition(
            pair="USDTRY", side=OrderSide.SELL, entry_price=30.0,
            quantity=300, stop_loss=31.5, ib_order_id=200,
            opened_at=datetime.now(UTC),
        )
        carry_manager._positions["USDTRY"] = pos

        with patch("forex_bot.strategy.carry.OrderService") as MockOS:
            mock_svc = AsyncMock()
            MockOS.return_value = mock_svc

            await carry_manager._close_position("USDTRY", pos, "test")

            mock_svc.place_fxconv_order.assert_called_once_with(
                instrument="USDTRY", side=OrderSide.BUY, quantity=300,
            )
            assert "USDTRY" not in carry_manager._positions

    @pytest.mark.asyncio
    async def test_close_failure_still_removes_position(self, carry_manager):
        """Position removed from tracking even if FXCONV order fails."""
        pos = CarryPosition(
            pair="USDZAR", side=OrderSide.BUY, entry_price=18.5,
            quantity=500, stop_loss=17.575, ib_order_id=100,
            opened_at=datetime.now(UTC),
        )
        carry_manager._positions["USDZAR"] = pos

        with patch("forex_bot.strategy.carry.OrderService") as MockOS:
            mock_svc = AsyncMock()
            mock_svc.place_fxconv_order.side_effect = Exception("order failed")
            MockOS.return_value = mock_svc

            await carry_manager._close_position("USDZAR", pos, "test")

            assert "USDZAR" not in carry_manager._positions
