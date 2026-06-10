from __future__ import annotations

from datetime import UTC, datetime
from pydantic import BaseModel, Field

from forex_bot.models.orders import OrderSide, OrderType


class Signal(BaseModel):
    """A trading signal produced by a strategy."""
    instrument: str
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    quantity: float = 0  # 0 means let risk manager decide
    price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    event_id: int | None = None
    strategy: str = ""
    reason: str = ""
    oca_group: str = ""  # OCA group ID — IB cancels other orders in the group when one fills
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CloseSignal(BaseModel):
    """Signal to close an existing position."""
    instrument: str
    reason: str = ""
    strategy: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
