from __future__ import annotations
from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, Field


class EventImpact(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EconomicEvent(BaseModel):
    id: int | None = None
    title: str
    country: str = "USD"
    impact: EventImpact = EventImpact.HIGH
    scheduled_at: datetime  # UTC
    actual: str | None = None
    forecast: str | None = None
    previous: str | None = None
    source_url: str = ""
    fred_series: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def has_actual(self) -> bool:
        return self.actual is not None and self.actual.strip() != ""

    @property
    def surprise_pct(self) -> float | None:
        """Calculate surprise as percentage deviation from forecast."""
        if not self.has_actual or not self.forecast:
            return None
        try:
            actual_val = float(self.actual.replace("%", "").replace("K", "e3").replace("M", "e6").replace("B", "e9"))
            forecast_val = float(self.forecast.replace("%", "").replace("K", "e3").replace("M", "e6").replace("B", "e9"))
            if forecast_val == 0:
                return None
            return ((actual_val - forecast_val) / abs(forecast_val)) * 100
        except (ValueError, ZeroDivisionError):
            return None
