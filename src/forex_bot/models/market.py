from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class Candle(BaseModel):
    instrument: str
    timestamp: datetime  # UTC
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    timeframe: str = "5 mins"


class PriceSnapshot(BaseModel):
    instrument: str
    timestamp: datetime
    # ib_async initializes absent quotes to NaN — reject them at the boundary
    # so NaN can never propagate into order price math.
    bid: float = Field(gt=0, allow_inf_nan=False)
    ask: float = Field(gt=0, allow_inf_nan=False)

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    def spread_pips(self, pip_size: float) -> float:
        """Spread in pips. pip_size is mandatory: a 0.0001 default silently
        produced 100x errors for JPY-quoted pairs."""
        return self.spread / pip_size
