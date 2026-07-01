from __future__ import annotations
from datetime import UTC, datetime
from enum import StrEnum
from pydantic import BaseModel, Field


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    BRACKET = "BRACKET"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class Order(BaseModel):
    id: int | None = None
    ib_order_id: int | None = None
    instrument: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    status: OrderStatus = OrderStatus.PENDING
    event_id: int | None = None
    strategy: str = ""
    oca_group: str = ""  # OCA group ID for straddle leg cancellation
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    filled_at: datetime | None = None
    fill_price: float | None = None
    commission: float | None = None


class Trade(BaseModel):
    id: int | None = None
    order_id: int | None = None
    instrument: str
    side: OrderSide
    quantity: float
    entry_price: float
    exit_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    pnl: float | None = None
    pnl_pips: float | None = None
    entry_spread_pips: float | None = None
    fill_price: float | None = None
    slippage_pips: float | None = None
    event_id: int | None = None
    strategy: str = ""
    commission: float | None = None
    opened_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    closed_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.exit_price is None


class Position(BaseModel):
    instrument: str
    side: OrderSide
    quantity: float
    avg_cost: float
    unrealized_pnl: float = 0.0
    market_value: float = 0.0
