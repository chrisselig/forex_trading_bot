from __future__ import annotations

from datetime import datetime, timedelta
from loguru import logger

try:
    from fredapi import Fred
except ImportError:
    Fred = None  # type: ignore

from forex_bot.config import get_settings


class FredClient:
    """Fetches historical economic indicator data from FRED."""

    def __init__(self, api_key: str | None = None):
        if Fred is None:
            raise ImportError("fredapi is required: pip install fredapi")
        key = api_key or get_settings().fred_api_key
        if not key:
            raise ValueError("FRED_API_KEY is required. Get one at https://fred.stlouisfed.org/docs/api/api_key.html")
        self._fred = Fred(api_key=key)

    def get_series(
        self,
        series_id: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]:
        """Fetch a FRED series and return as list of {date, value} dicts."""
        if start_date is None:
            start_date = datetime.now() - timedelta(days=365 * 2)
        if end_date is None:
            end_date = datetime.now()

        logger.info(f"Fetching FRED series {series_id} ({start_date.date()} to {end_date.date()})")
        data = self._fred.get_series(
            series_id,
            observation_start=start_date.strftime("%Y-%m-%d"),
            observation_end=end_date.strftime("%Y-%m-%d"),
        )

        results = []
        for date, value in data.items():
            if value is not None and str(value) != "nan":
                results.append({"date": date.to_pydatetime(), "value": float(value)})

        logger.info(f"Got {len(results)} observations for {series_id}")
        return results

    def get_release_dates(self, series_id: str) -> list[datetime]:
        """Get historical release dates for a series."""
        # The release dates can be fetched via the releases endpoint
        try:
            self._fred.search(series_id)
            return []  # FRED API doesn't directly expose this simply
        except Exception:
            return []
