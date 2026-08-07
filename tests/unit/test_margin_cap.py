"""Tests for margin-aware position capping (Error 201 prevention).

Risk-based sizing ignores margin capacity, so exotic-pair straddles
(2.5M USDTRY ≈ $1M CAD initial margin on a $5K account) were rejected by
IB with Error 201 on July 15-16, 2026. The execution engine now whatIf-checks
initial margin before placement and scales quantity to fit available funds.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from forex_bot.broker.exceptions import DataError
from forex_bot.broker.orders import OrderService
from forex_bot.config import get_settings
from forex_bot.execution.engine import ExecutionEngine
from forex_bot.models.account import AccountSummary
from forex_bot.models.orders import OrderSide, OrderType
from forex_bot.strategy.signals import Signal


def make_engine(
    available_funds: float,
    whatif_margin: float | None,
    quote_to_cad: float | Exception = 1.0,
) -> ExecutionEngine:
    client = MagicMock()
    client.ensure_connected = AsyncMock()
    client.get_account_summary = AsyncMock(
        return_value=AccountSummary(
            account_id="DU1234567",
            net_liquidation=available_funds,
            available_funds=available_funds,
        )
    )
    engine = ExecutionEngine(
        client=client,
        risk_manager=MagicMock(),
        circuit_breaker=MagicMock(),
        journal=MagicMock(),
    )
    engine._order_service = MagicMock()
    engine._order_service.whatif_init_margin = AsyncMock(return_value=whatif_margin)
    engine._pricing_service = MagicMock()
    if isinstance(quote_to_cad, Exception):
        engine._pricing_service.get_quote_to_cad_rate = AsyncMock(side_effect=quote_to_cad)
    else:
        engine._pricing_service.get_quote_to_cad_rate = AsyncMock(return_value=quote_to_cad)
    return engine


def make_signal(quantity: float = 2_453_000) -> Signal:
    return Signal(
        instrument="USDTRY",
        side=OrderSide.BUY,
        order_type=OrderType.STOP,
        quantity=quantity,
        price=47.04255,
        stop_loss=47.04155,
        take_profit=47.04955,
        strategy="straddle",
    )


@pytest.fixture(autouse=True)
def margin_pct():
    settings = get_settings()
    original = settings.risk.max_margin_pct_per_trade
    settings.risk.max_margin_pct_per_trade = 25.0
    yield
    settings.risk.max_margin_pct_per_trade = original


@pytest.mark.asyncio
async def test_under_cap_leaves_quantity_unchanged():
    # $100K available, 25% cap = $25K; margin needs only $1K
    engine = make_engine(available_funds=100_000, whatif_margin=1_000)
    signal = make_signal(quantity=21_000)

    error = await engine._apply_margin_cap(signal)

    assert error is None
    assert signal.quantity == 21_000


@pytest.mark.asyncio
async def test_over_cap_scales_quantity_down():
    # The real July 15 rejection: 2.45M USDTRY needs $1.05M margin, $4.9K account
    engine = make_engine(available_funds=4_900, whatif_margin=1_050_000)
    signal = make_signal(quantity=2_453_000)

    error = await engine._apply_margin_cap(signal)

    assert error is None
    # cap = 4900 * 25% = 1225; scale = 1225/1.05M * 0.95
    expected = int(2_453_000 * (1_225 / 1_050_000) * 0.95)
    assert signal.quantity == pytest.approx(expected, abs=1)
    # Scaled quantity's margin must now fit under the cap
    implied_margin = signal.quantity / 2_453_000 * 1_050_000
    assert implied_margin <= 1_225


@pytest.mark.asyncio
async def test_whatif_unavailable_uses_conservative_margin_estimate():
    # whatIf being explicitly unavailable (e.g. IB rejected the hypothetical
    # order with Error 201) used to mean "proceed at full size" — that's
    # exactly what let 2.5M-unit USDTRY orders reach IB and get rejected for
    # real. Estimate notional from quantity * price * quote-to-CAD (the same
    # conversion used elsewhere in this class) and scale down conservatively.
    quote_to_cad = 0.030462  # ~ real USDCAD/USDTRY ratio
    price = 47.04255
    original_qty = 2_453_000
    engine = make_engine(available_funds=4_900, whatif_margin=None, quote_to_cad=quote_to_cad)
    signal = make_signal(quantity=original_qty)

    error = await engine._apply_margin_cap(signal)

    assert error is None
    assert signal.quantity < original_qty
    # USDTRY isn't in the majors list -> 30% conservative margin assumption
    notional_cad = original_qty * price * quote_to_cad
    margin_estimate = notional_cad * 0.30
    cap = 4_900 * 0.25
    expected = int(original_qty * (cap / margin_estimate) * 0.95)
    assert signal.quantity == pytest.approx(expected, abs=1)


@pytest.mark.asyncio
async def test_whatif_unavailable_majors_use_lower_margin_estimate():
    # Majors (EURUSD/USDJPY/USDCAD/GBPUSD) get a 2% estimate instead of 30%,
    # so a much larger position is allowed to pass unscaled at the same
    # available funds.
    quote_to_cad = 0.7
    price = 1.1
    original_qty = 10_000
    engine = make_engine(available_funds=100_000, whatif_margin=None, quote_to_cad=quote_to_cad)
    signal = make_signal(quantity=original_qty)
    signal.instrument = "EURUSD"

    error = await engine._apply_margin_cap(signal)

    assert error is None
    notional_cad = original_qty * price * quote_to_cad
    margin_estimate = notional_cad * 0.02
    cap = 100_000 * 0.25
    assert margin_estimate <= cap  # sanity: this scenario should fit unscaled
    assert signal.quantity == original_qty


@pytest.mark.asyncio
async def test_whatif_and_quote_to_cad_both_unavailable_proceeds_unscaled():
    # Total data outage (whatIf AND pricing both down) must still fall back
    # to the original safety net — IB's own submission check is the backstop.
    engine = make_engine(
        available_funds=4_900, whatif_margin=None,
        quote_to_cad=DataError("no market data"),
    )
    signal = make_signal(quantity=2_453_000)

    error = await engine._apply_margin_cap(signal)

    assert error is None
    assert signal.quantity == 2_453_000


@pytest.mark.asyncio
async def test_whatif_unavailable_no_price_proceeds_unscaled():
    # Can't estimate notional without a price — fail safe, not with an error.
    engine = make_engine(available_funds=4_900, whatif_margin=None)
    signal = make_signal(quantity=2_453_000)
    signal.price = None

    error = await engine._apply_margin_cap(signal)

    assert error is None
    assert signal.quantity == 2_453_000


@pytest.mark.asyncio
async def test_negative_margin_change_needs_no_cap():
    # Closing/reducing orders free margin
    engine = make_engine(available_funds=4_900, whatif_margin=-500.0)
    signal = make_signal(quantity=10_000)

    error = await engine._apply_margin_cap(signal)

    assert error is None
    assert signal.quantity == 10_000


@pytest.mark.asyncio
async def test_no_available_funds_rejects():
    engine = make_engine(available_funds=0.0, whatif_margin=1_000)
    signal = make_signal()

    error = await engine._apply_margin_cap(signal)

    assert error is not None
    assert "No available funds" in error


@pytest.mark.asyncio
async def test_unfittable_order_rejects():
    # Margin so extreme that even 1 unit doesn't fit
    engine = make_engine(available_funds=100, whatif_margin=50_000_000)
    signal = make_signal(quantity=100)

    error = await engine._apply_margin_cap(signal)

    assert error is not None
    assert "Cannot fit margin" in error


@pytest.mark.asyncio
async def test_available_funds_parsed_from_account_summary():
    assert AccountSummary(available_funds=1234.5).available_funds == 1234.5
    assert AccountSummary().available_funds == 0.0


def make_order_service(whatif_result) -> OrderService:
    client = MagicMock()
    client.ensure_connected = AsyncMock()
    client.ib = MagicMock()
    client.ib.qualifyContractsAsync = AsyncMock(return_value=[MagicMock()])
    if isinstance(whatif_result, Exception):
        client.ib.whatIfOrderAsync = AsyncMock(side_effect=whatif_result)
    else:
        client.ib.whatIfOrderAsync = AsyncMock(return_value=whatif_result)
    return OrderService(client)


@pytest.mark.asyncio
async def test_whatif_init_margin_parses_margin():
    service = make_order_service(MagicMock(initMarginChange="121652.94"))

    margin = await service.whatif_init_margin(
        "USDZAR", OrderSide.BUY, 858_000, OrderType.STOP, price=16.46085
    )

    assert margin == pytest.approx(121_652.94)


@pytest.mark.asyncio
async def test_whatif_init_margin_max_value_sentinel_is_unknown():
    # IB reports "unknown" as Double.MAX_VALUE — must not be treated as a number
    service = make_order_service(
        MagicMock(initMarginChange="1.7976931348623157E308")
    )

    margin = await service.whatif_init_margin("USDTRY", OrderSide.BUY, 1_000)

    assert margin is None


@pytest.mark.asyncio
async def test_whatif_init_margin_timeout_returns_none():
    service = make_order_service(TimeoutError())

    margin = await service.whatif_init_margin("USDTRY", OrderSide.SELL, 1_000)

    assert margin is None


@pytest.mark.asyncio
async def test_whatif_init_margin_unparseable_returns_none():
    service = make_order_service(MagicMock(initMarginChange=""))

    margin = await service.whatif_init_margin("USDTRY", OrderSide.BUY, 1_000)

    assert margin is None


@pytest.mark.asyncio
async def test_whatif_init_margin_bare_list_result_returns_none():
    # ib_async resolves the whatIf future with a plain [] (its default empty
    # results container) instead of an OrderState when IB responds to the
    # reqId with a genuine order-level error rather than an openOrder
    # callback. Must not raise AttributeError up through order placement.
    service = make_order_service([])

    margin = await service.whatif_init_margin("USDTRY", OrderSide.BUY, 1_000)

    assert margin is None
