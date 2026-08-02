from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class CotCrowdingReading(BaseModel):
    """A currency's speculative-crowding reading from the CFTC Traders in
    Financial Futures (TFF) report.

    z_score is leveraged-fund net position (as % of open interest) on the
    latest report date, standardized against its own trailing history.
    Positive means leveraged funds are net long relative to their own
    history; negative means net short. Extremes in either direction mark a
    crowded trade — the setup for a violent unwind if sentiment flips.
    """

    currency: str
    report_date: datetime
    net_pct_oi: float
    z_score: float
    n_weeks: int
