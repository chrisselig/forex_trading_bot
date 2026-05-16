from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


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
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    def spread_pips(self, pip_size: float = 0.0001) -> float:
        return self.spread / pip_size
