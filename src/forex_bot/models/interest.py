from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class InterestAccrualRow(BaseModel):
    """One currency's real, IB-computed interest accrual for a single day,
    parsed from the "Interest Accruals" Flex Query report. Already
    converted to the account's base currency (CAD)."""

    currency: str
    from_date: datetime
    to_date: datetime
    amount_cad: float
