from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime

from loguru import logger
from ib_async import IB, BarData

from forex_bot.broker.client import IBClient
from forex_bot.broker.contracts import get_quote_currency, make_forex_contract
from forex_bot.broker.exceptions import DataError
from forex_bot.models.market import Candle, PriceSnapshot

# Upper bound for any IB request that should answer quickly. A wedged TWS
# (socket open, API unresponsive) otherwise hangs the awaiting job forever.
IB_CALL_TIMEOUT_S = 30.0


def _is_valid_quote(value: float | None) -> bool:
    """True if the value is a usable price. ib_async initializes absent
    quotes to NaN, which passes truthiness and <=0 checks."""
    return value is not None and not math.isnan(value) and value > 0


class PricingService:
    """Handles real-time and historical market data from IB.

    Pacing state is class-level and mutated in place ON PURPOSE: IB's
    60-requests-per-10-minutes historical data limit applies per connection,
    not per PricingService instance, so all instances must share one budget.
    """

    # IB pacing: max 60 historical data requests per 10 minutes
    _request_timestamps: list[float] = []
    _pacing_lock: asyncio.Lock = asyncio.Lock()
    _PACING_WINDOW = 600  # 10 minutes
    _PACING_LIMIT = 60

    def __init__(self, client: IBClient):
        self._client = client

    @property
    def ib(self) -> IB:
        return self._client.ib

    async def _throttle(self) -> None:
        """Enforce IB historical data pacing limits (shared across instances)."""
        async with self._pacing_lock:
            now = asyncio.get_running_loop().time()
            # Mutate in place — reassignment would create a per-instance
            # shadow copy and split the shared budget.
            self._request_timestamps[:] = [
                t for t in self._request_timestamps if now - t < self._PACING_WINDOW
            ]
            if len(self._request_timestamps) >= self._PACING_LIMIT:
                wait_time = self._PACING_WINDOW - (now - self._request_timestamps[0])
                logger.warning(f"IB pacing limit reached, waiting {wait_time:.0f}s")
                await asyncio.sleep(wait_time)
            self._request_timestamps.append(asyncio.get_running_loop().time())

    async def get_snapshot(self, pair: str) -> PriceSnapshot:
        """Get current bid/ask for a forex pair."""
        await self._client.ensure_connected()
        contract = make_forex_contract(pair)
        try:
            await asyncio.wait_for(
                self.ib.qualifyContractsAsync(contract), IB_CALL_TIMEOUT_S
            )
        except TimeoutError as e:
            raise DataError(f"Timed out qualifying contract for {pair}") from e

        ticker = self.ib.reqMktData(contract, snapshot=True)
        try:
            for _ in range(50):
                await asyncio.sleep(0.1)
                if _is_valid_quote(ticker.bid) and _is_valid_quote(ticker.ask):
                    break

            if not _is_valid_quote(ticker.bid) or not _is_valid_quote(ticker.ask):
                raise DataError(
                    f"No market data received for {pair} "
                    f"(bid={ticker.bid}, ask={ticker.ask})"
                )

            return PriceSnapshot(
                instrument=pair,
                timestamp=datetime.now(UTC),
                bid=ticker.bid,
                ask=ticker.ask,
            )
        finally:
            # Always release the market data line, even on error/cancellation —
            # IB caps concurrent subscriptions and leaks exhaust the cap.
            self.ib.cancelMktData(contract)

    async def get_quote_to_cad_rate(self, pair: str) -> float:
        """Get the conversion rate from the pair's quote currency to CAD.

        Returns 1.0 if the quote currency is already CAD.
        For USD-quote pairs (e.g. AUDUSD): returns USDCAD mid.
        For other-quote pairs (e.g. USDTRY): returns USDCAD / pair_mid.

        Raises DataError when the rate cannot be determined — callers must
        fail closed. The old silent 1.0 fallback oversized positions by the
        full CAD/quote differential (~40% for USD-quoted pairs).
        """
        quote = get_quote_currency(pair)
        if quote == "CAD":
            return 1.0

        try:
            if quote == "USD":
                usdcad = await self.get_snapshot("USDCAD")
                return usdcad.mid

            # For non-USD, non-CAD quote currencies (TRY, ZAR, JPY, etc.)
            # 1 unit of quote currency = USDCAD / pair_mid CAD
            usdcad, pair_snapshot = await asyncio.gather(
                self.get_snapshot("USDCAD"), self.get_snapshot(pair)
            )
            return usdcad.mid / pair_snapshot.mid
        except DataError as e:
            raise DataError(f"Cannot determine quote-to-CAD rate for {pair}: {e}") from e

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
        try:
            await asyncio.wait_for(
                self.ib.qualifyContractsAsync(contract), IB_CALL_TIMEOUT_S
            )
            bars: list[BarData] = await asyncio.wait_for(
                self.ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime="",
                    durationStr=duration,
                    barSizeSetting=bar_size,
                    whatToShow=what_to_show,
                    useRTH=False,
                    formatDate=2,  # UTC
                ),
                IB_CALL_TIMEOUT_S * 2,
            )
        except TimeoutError as e:
            raise DataError(f"Timed out fetching historical data for {pair}") from e
        except (OSError, ValueError) as e:
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
