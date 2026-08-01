"""Tests for the daily P&L snapshot: per-position mark-to-market from IB,
the Telegram message, and the scheduled job guard."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from forex_bot.broker.client import IBClient
from forex_bot.models.account import AccountSummary, CarryPositionPnl, PortfolioPosition
from forex_bot.notifications.telegram import TelegramNotifier


def _pf_item(symbol, local, position, mkt_price, mkt_val, avg, upnl, rpnl=0.0):
    return SimpleNamespace(
        contract=SimpleNamespace(symbol=symbol, localSymbol=local),
        position=position,
        marketPrice=mkt_price,
        marketValue=mkt_val,
        averageCost=avg,
        unrealizedPNL=upnl,
        realizedPNL=rpnl,
    )


@pytest.mark.asyncio
async def test_get_portfolio_maps_and_skips_zero():
    client = IBClient()
    client.ensure_connected = AsyncMock()
    client.ib = MagicMock()
    client.ib.portfolio = MagicMock(return_value=[
        _pf_item("USD", "USD.ZAR", 3312, 16.5, 54648.0, 16.37, 210.5),
        _pf_item("AUD", "AUD.JPY", -3315, 112.0, -37129.0, 112.58, -85.2),
        _pf_item("EUR", "EUR.USD", 0, 1.08, 0.0, 1.08, 0.0),  # skipped
    ])

    out = await client.get_portfolio()

    assert len(out) == 2
    zar = next(p for p in out if p.instrument == "USD.ZAR")
    assert zar.side == "BUY" and zar.quantity == 3312
    assert zar.unrealized_pnl == 210.5
    jpy = next(p for p in out if p.instrument == "AUD.JPY")
    assert jpy.side == "SELL" and jpy.quantity == 3315
    assert jpy.unrealized_pnl == -85.2


@pytest.fixture
def notifier():
    n = TelegramNotifier(bot_token="t", chat_id="c", enabled=True)
    n._send = AsyncMock()
    return n


@pytest.mark.asyncio
async def test_snapshot_message_positive_totals(notifier):
    account = AccountSummary(net_liquidation=5120.0, unrealized_pnl=125.30, realized_pnl=40.0)
    positions = [
        PortfolioPosition(instrument="USD.ZAR", side="BUY", quantity=3312, unrealized_pnl=210.5),
        PortfolioPosition(instrument="AUD.JPY", side="SELL", quantity=3315, unrealized_pnl=-85.2),
    ]

    await notifier.notify_pnl_snapshot(account, positions)

    text = notifier._send.call_args[0][0]
    assert "P&L SNAPSHOT" in text
    assert "5,120.00" in text
    assert "+$125.30" in text          # account unrealized, positive sign
    assert "Open positions (2)" in text
    # Biggest mover (ZAR, |210.5|) listed before JPY (|85.2|)
    assert text.index("USD.ZAR") < text.index("AUD.JPY")
    assert "+$210.50" in text and "−$85.20" in text


@pytest.mark.asyncio
async def test_snapshot_negative_unrealized_uses_minus(notifier):
    account = AccountSummary(net_liquidation=4900.0, unrealized_pnl=-73.4)
    await notifier.notify_pnl_snapshot(account, [])
    text = notifier._send.call_args[0][0]
    assert "−$73.40" in text
    assert "No open positions" in text


@pytest.mark.asyncio
async def test_snapshot_sent_silently(notifier):
    await notifier.notify_pnl_snapshot(AccountSummary(), [])
    # silent=True keyword so the daily snapshot doesn't buzz the phone
    assert notifier._send.call_args.kwargs.get("silent") is True


@pytest.mark.asyncio
async def test_snapshot_disabled_notifier_is_noop():
    n = TelegramNotifier(bot_token="", chat_id="", enabled=False)
    # Must not raise even with no transport configured
    await n.notify_pnl_snapshot(AccountSummary(unrealized_pnl=10.0), [])


@pytest.mark.asyncio
async def test_snapshot_folds_in_carry_pnl(notifier):
    """IB's own UnrealizedPnL is $0 for carry (IDEALPRO spot FX never marks
    to market there) — the snapshot's headline total and position list must
    include carry's own computed P&L, not just IB's (empty) portfolio feed."""
    account = AccountSummary(net_liquidation=4840.85, unrealized_pnl=0.0)
    carry = [
        CarryPositionPnl(
            instrument="USDTRY", side="SELL", quantity=990,
            entry_price=46.82081, current_price=47.52, unrealized_pnl_cad=-20.5,
        ),
        CarryPositionPnl(
            instrument="AUDJPY", side="BUY", quantity=3315,
            entry_price=112.58, current_price=112.9, unrealized_pnl_cad=9.9,
        ),
    ]

    await notifier.notify_pnl_snapshot(account, [], carry_positions=carry)

    text = notifier._send.call_args[0][0]
    # total = 0.0 (IB) + (-20.5 + 9.9) carry = -10.6
    assert "−$10.60" in text
    assert "Open positions (2)" in text
    assert "USDTRY" in text and "AUDJPY" in text
    # Biggest mover (USDTRY, |20.5|) listed before AUDJPY (|9.9|)
    assert text.index("USDTRY") < text.index("AUDJPY")


@pytest.mark.asyncio
async def test_snapshot_no_carry_positions_defaults_empty(notifier):
    await notifier.notify_pnl_snapshot(AccountSummary(unrealized_pnl=0.0), [])
    text = notifier._send.call_args[0][0]
    assert "No open positions" in text
