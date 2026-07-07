from __future__ import annotations

import pytest
from sqlalchemy import select

from forex_bot.data import database as db_module
from forex_bot.data.database import get_session, init_db
from forex_bot.data.schemas import OrderRecord, TradeRecord
from forex_bot.data.trade_journal import TradeJournal
from forex_bot.models.orders import Order, OrderSide, OrderStatus, OrderType, Trade


@pytest.fixture
async def journal_db(tmp_path, monkeypatch):
    """Point the database module at a fresh, isolated SQLite file per test."""
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_journal.db")
    db_module._engine = None
    db_module._session_factory = None
    await init_db()
    yield
    if db_module._engine is not None:
        await db_module._engine.dispose()
    db_module._engine = None
    db_module._session_factory = None


async def _fetch_ib_order_id(order_id: int) -> int | None:
    async with get_session() as session:
        result = await session.execute(
            select(OrderRecord.ib_order_id).where(OrderRecord.id == order_id)
        )
        return result.scalar_one_or_none()


def _make_order(**overrides) -> Order:
    defaults = dict(
        instrument="USDZAR",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=1000,
        stop_loss=18.0,
        strategy="straddle",
    )
    defaults.update(overrides)
    return Order(**defaults)


class TestUpdateOrderStatusIbOrderId:
    """update_order_status must persist ib_order_id when given, and leave it
    untouched when omitted — this is the core fix: without it, fill/cancel
    events keyed by IB order ID can never find the journaled row."""

    async def test_persists_ib_order_id_when_given(self, journal_db):
        journal = TradeJournal()
        order = _make_order()
        order_id = await journal.log_order(order)
        assert await _fetch_ib_order_id(order_id) is None

        await journal.update_order_status(
            order_id, OrderStatus.SUBMITTED, ib_order_id=555
        )

        assert await _fetch_ib_order_id(order_id) == 555

    async def test_leaves_ib_order_id_untouched_when_omitted(self, journal_db):
        journal = TradeJournal()
        order = _make_order()
        order_id = await journal.log_order(order)

        await journal.update_order_status(
            order_id, OrderStatus.SUBMITTED, ib_order_id=555
        )
        # A later status update with no ib_order_id (e.g. the REJECTED /
        # ERROR paths in ExecutionEngine) must not clobber the value.
        await journal.update_order_status(order_id, OrderStatus.FILLED, fill_price=18.5)

        assert await _fetch_ib_order_id(order_id) == 555

    async def test_ib_order_id_stays_none_when_never_provided(self, journal_db):
        journal = TradeJournal()
        order = _make_order()
        order_id = await journal.log_order(order)

        await journal.update_order_status(order_id, OrderStatus.REJECTED)

        assert await _fetch_ib_order_id(order_id) is None


class TestUpdateOrderStatusByIbIdEndToEnd:
    """End-to-end regression test for the bug: after log_order() (which
    journals before IB placement, so ib_order_id is initially None) and the
    post-placement update_order_status(..., ib_order_id=...), a fill/cancel
    event arriving with only the IB order ID must be able to find the row."""

    async def test_finds_order_after_ib_order_id_persisted(self, journal_db):
        journal = TradeJournal()
        order = _make_order()
        order_id = await journal.log_order(order)

        # Simulate ExecutionEngine's post-placement update.
        await journal.update_order_status(
            order_id, OrderStatus.SUBMITTED, ib_order_id=777
        )

        # Simulate PositionMonitor handling an IB fill event.
        db_id = await journal.update_order_status_by_ib_id(
            777, OrderStatus.FILLED, fill_price=18.55
        )

        assert db_id == order_id
        record = await journal.get_order_by_ib_id(777)
        assert record is not None
        assert record.id == order_id
        assert record.status == OrderStatus.FILLED.value
        assert record.fill_price == 18.55

    async def test_returns_none_when_ib_order_id_never_persisted(self, journal_db):
        """Guards against regressing back to the pre-fix behavior."""
        journal = TradeJournal()
        order = _make_order()
        order_id = await journal.log_order(order)

        # Bug reproduction: never persist ib_order_id.
        await journal.update_order_status(order_id, OrderStatus.SUBMITTED)

        db_id = await journal.update_order_status_by_ib_id(999, OrderStatus.FILLED)

        assert db_id is None


class TestCommissionBeforeTradeOrdering:
    """A commission report can arrive BEFORE the trade row is created (it lands
    on the order first). log_trade must backfill it onto the new trade record so
    the commission isn't lost — the bug where the dashboard showed no commission
    on carry fills whose commission report preceded trade creation."""

    async def test_commission_before_trade_is_backfilled(self, journal_db):
        journal = TradeJournal()
        order = _make_order(ib_order_id=555, strategy="carry")
        db_order_id = await journal.log_order(order)

        # Commission arrives before the trade row exists → recorded on the order.
        await journal.update_commission(555, 2.84)

        # Trade row created afterwards (on fill).
        trade = Trade(
            order_id=db_order_id, instrument="USDZAR", side=OrderSide.BUY,
            quantity=1000, entry_price=18.0, strategy="carry",
        )
        trade_id = await journal.log_trade(trade)

        async with get_session() as session:
            rec = (
                await session.execute(
                    select(TradeRecord).where(TradeRecord.id == trade_id)
                )
            ).scalar_one()
            assert rec.commission == pytest.approx(2.84)

    async def test_commission_after_trade_still_updates(self, journal_db):
        """The normal ordering (commission after the trade exists) still works."""
        journal = TradeJournal()
        order = _make_order(ib_order_id=556, strategy="carry")
        db_order_id = await journal.log_order(order)
        trade = Trade(
            order_id=db_order_id, instrument="USDZAR", side=OrderSide.BUY,
            quantity=1000, entry_price=18.0, strategy="carry",
        )
        trade_id = await journal.log_trade(trade)

        await journal.update_commission(556, 3.10)

        async with get_session() as session:
            rec = (
                await session.execute(
                    select(TradeRecord).where(TradeRecord.id == trade_id)
                )
            ).scalar_one()
            assert rec.commission == pytest.approx(3.10)
