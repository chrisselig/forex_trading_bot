from __future__ import annotations
from datetime import UTC, datetime
from pydantic import BaseModel, Field


class AccountSummary(BaseModel):
    account_id: str = ""
    net_liquidation: float = 0.0
    total_cash: float = 0.0
    buying_power: float = 0.0
    available_funds: float = 0.0
    gross_position_value: float = 0.0
    maintenance_margin: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PortfolioPosition(BaseModel):
    """A single open position with live mark-to-market, from IB's portfolio
    feed (ib.portfolio()). Unlike ib.positions(), this carries the current
    market price and per-position unrealized P&L — the "am I up or down on
    this pair right now" numbers."""

    instrument: str
    side: str = ""  # "BUY" (long) or "SELL" (short)
    quantity: float = 0.0
    avg_cost: float = 0.0
    market_price: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


class CarryPositionPnl(BaseModel):
    """Mark-to-market unrealized P&L for a carry position.

    IDEALPRO spot FX settles as a currency cash-balance change, not a
    broker "position" — it never appears in ib.positions()/ib.portfolio(),
    and IB's account-level UnrealizedPnL tag doesn't capture it either
    (confirmed 0.00 for every currency on a live account holding real carry
    exposure). This is computed from carry's own entry-price tracking
    against a fresh price snapshot — the only place this P&L can come from.
    """

    instrument: str
    side: str = ""
    quantity: float = 0.0
    entry_price: float = 0.0
    current_price: float = 0.0
    unrealized_pnl_cad: float = 0.0
