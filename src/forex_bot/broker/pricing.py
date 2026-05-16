from __future__ import annotations

import asyncio
from datetime import datetime
from loguru import logger
from ib_async import IB, BarData

from forex_bot.broker.client import IBClient
from forex_bot.broker.contracts import make_forex_contract, get_pip_size
from forex_bot.broker.exceptions import DataError
from forex_bot.models.market import Candle, PriceSnapshot


class PricingService:
    """Handles real-time and historical market data from IB."""

    # IB pacing: max 60 historical data requests per 10 minutes
    _request_timestamps: list[float] = []
    _PACING_WINDOW = 600  # 10 minutes
    _PACING_LIMIT = 60

    def __init__(self, client: IBClient):
        self._client = client

    @property
    def ib(self) -> IB:
        return self._client.ib

    async def _throttle(self) -> None:
        """Enforce IB historical data pacing limits."""
        now = asyncio.get_event_loop().time()
        self._request_timestamps = [t for t in self._request_timestamps if now - t < self._PACING_WINDOW]
        if len(self._request_timestamps) >= self._PACING_LIMIT:
            wait_time = self._PACING_WINDOW - (now - self._request_timestamps[0])
            logger.warning(f"IB pacing limit reached, waiting {wait_time:.0f}s")
            await asyncio.sleep(wait_time)
        self._request_timestamps.append(now)

    async def get_snapshot(self, pair: str) -> PriceSnapshot:
        """Get current bid/ask for a forex pair."""
        await self._client.ensure_connected()
        contract = make_forex_contract(pair)
        self.ib.qualifyContracts(contract)
        ticker = self.ib.reqMktData(contract, snapshot=True)
        # Wait for data to arrive
        for _ in range(50):
            await asyncio.sleep(0.1)
            if ticker.bid and ticker.ask and ticker.bid > 0:
                break

        if not ticker.bid or not ticker.ask or ticker.bid <= 0:
            self.ib.cancelMktData(contract)
            raise DataError(f"No market data received for {pair}")

        snapshot = PriceSnapshot(
            instrument=pair,
            timestamp=datetime.utcnow(),
            bid=ticker.bid,
            ask=ticker.ask,
        )
        self.ib.cancelMktData(contract)
        return snapshot

    async def stream_prices(self, pair: str):
        """Yield PriceSnapshot objects as prices update. Async generator."""
        await self._client.ensure_connected()
        contract = make_forex_contract(pair)
        self.ib.qualifyContracts(contract)
        self.ib.reqMktData(contract)
        ticker = self.ib.ticker(contract)

        try:
            while True:
                await asyncio.sleep(0.25)
                if ticker.bid and ticker.ask and ticker.bid > 0:
                    yield PriceSnapshot(
                        instrument=pair,
                        timestamp=datetime.utcnow(),
                        bid=ticker.bid,
                        ask=ticker.ask,
                    )
        finally:
            self.ib.cancelMktData(contract)

    async def get_historical_bars(
        self,
        pair: str,
        duration: str = "1 D",
        bar_size: str = "5 mins",
        what_to_show: str = "MIDPOINT",
    ) -> list[Candle]:
        """Fetch historical bars from IB."""
        await self._client.ensure_connected()
        await self._throttle()

        contract = make_forex_contract(pair)
        self.ib.qualifyContracts(contract)

        try:
            bars: list[BarData] = await self.ib.reqHistoricalDataAsync(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow=what_to_show,
                useRTH=False,
                formatDate=2,  # UTC
            )
        except Exception as e:
            raise DataError(f"Failed to fetch historical data for {pair}: {e}") from e

        return [
            Candle(
                instrument=pair,
                timestamp=bar.date,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                timeframe=bar_size,
            )
            for bar in bars
        ]
