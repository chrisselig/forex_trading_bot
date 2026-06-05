from __future__ import annotations
from datetime import UTC, datetime
from pydantic import BaseModel, Field


class AccountSummary(BaseModel):
    account_id: str = ""
    net_liquidation: float = 0.0
    total_cash: float = 0.0
    buying_power: float = 0.0
    gross_position_value: float = 0.0
    maintenance_margin: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
