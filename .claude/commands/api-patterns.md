# API Integration Patterns

When I'm working with external APIs (IB, Forex Factory, FRED), follow these patterns. Flag violations and show the fix.

---

## 1. Connection Lifecycle

Connections are expensive resources. Manage them explicitly.

**BAD** — new connection per request, no cleanup on error:
```python
async def get_price(pair: str) -> float:
    ib = IB()
    await ib.connectAsync("127.0.0.1", 4002, clientId=1)
    contract = Forex(pair)
    ticker = ib.reqMktData(contract)
    await asyncio.sleep(2)
    price = ticker.bid
    ib.disconnect()  # never reached if reqMktData throws
    return price
```

**GOOD** — long-lived connection, context manager for cleanup, reconnection logic:
```python
class IBClient:
    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    async def ensure_connected(self) -> None:
        if not self.is_connected:
            logger.warning("IB connection lost, reconnecting...")
            await self.connect()

# Usage:
async with IBClient() as client:
    pricing = PricingService(client)
    snapshot = await pricing.get_snapshot("EURUSD")
```

---

## 2. Rate Limiting & Pacing

External APIs have limits. Violating them gets you banned or throttled.

**BAD** — fires 100 requests simultaneously, gets rate-limited or banned:
```python
async def fetch_all_bars(pairs: list[str]):
    tasks = [self._fetch_bars(pair) for pair in pairs]
    return await asyncio.gather(*tasks)  # 100 concurrent IB requests = pacing violation
```

**GOOD** — respects IB's 60 requests per 10 minutes limit:
```python
async def _throttle(self) -> None:
    """Enforce IB historical data pacing limits."""
    now = asyncio.get_event_loop().time()
    # Remove timestamps outside the window
    self._request_timestamps = [
        t for t in self._request_timestamps
        if now - t < self._PACING_WINDOW
    ]
    if len(self._request_timestamps) >= self._PACING_LIMIT:
        wait_time = self._PACING_WINDOW - (now - self._request_timestamps[0])
        logger.warning(f"IB pacing limit reached, waiting {wait_time:.0f}s")
        await asyncio.sleep(wait_time)
    self._request_timestamps.append(now)

async def get_historical_bars(self, pair: str, ...) -> list[Candle]:
    await self._throttle()  # always throttle before historical requests
    bars = await self.ib.reqHistoricalDataAsync(...)
```

**BAD** — scraping without any politeness:
```python
async def fetch_all_weeks(self):
    for week in last_52_weeks:
        response = await client.get(f"{FF_URL}?week={week}")  # 52 requests in 2 seconds
```

**GOOD** — rate-limited, with backoff:
```python
class ForexFactoryScraper:
    def __init__(self, rate_limit_seconds: float = 2.0):
        self._rate_limit = rate_limit_seconds
        self._last_request: float = 0

    async def _throttle(self) -> None:
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request
        if elapsed < self._rate_limit:
            await asyncio.sleep(self._rate_limit - elapsed)
        self._last_request = asyncio.get_event_loop().time()
```

---

## 3. Timeout Everything

Never wait indefinitely. A hung connection should fail, not freeze the bot.

**BAD** — waits forever if IB never responds:
```python
async def get_snapshot(self, pair: str):
    ticker = self.ib.reqMktData(contract)
    while not ticker.bid:  # infinite loop if no data subscription
        await asyncio.sleep(0.1)
    return ticker.bid
```

**GOOD** — bounded wait with clear failure:
```python
async def get_snapshot(self, pair: str) -> PriceSnapshot:
    ticker = self.ib.reqMktData(contract, snapshot=True)
    for _ in range(50):  # max 5 seconds
        await asyncio.sleep(0.1)
        if ticker.bid and ticker.ask and ticker.bid > 0:
            break
    else:
        self.ib.cancelMktData(contract)
        raise DataError(f"No market data received for {pair} within 5s")

    snapshot = PriceSnapshot(instrument=pair, bid=ticker.bid, ask=ticker.ask, ...)
    self.ib.cancelMktData(contract)
    return snapshot
```

---

## 4. Parsing External Data

External data is untrusted. Parse into typed models immediately at the boundary.

**BAD** — raw dict propagates through the system, shape is implicit:
```python
async def fetch_events(self):
    html = await self._get_html()
    rows = self._parse_table(html)
    return rows  # list[dict] — what keys? what types? who knows

# Later, somewhere deep in strategy code:
event_time = rows[0]["time"]  # KeyError? wrong type? stale format?
```

**GOOD** — parse into Pydantic model at the boundary, everything downstream is typed:
```python
async def fetch_week(self, date: datetime | None = None) -> list[EconomicEvent]:
    html = await self._get_html(date)
    return self._parse_html(html)  # returns list[EconomicEvent]

def _parse_html(self, html: str) -> list[EconomicEvent]:
    # ...parsing logic...
    events.append(EconomicEvent(
        title=title,
        country=currency,
        impact=impact,           # EventImpact enum, validated
        scheduled_at=scheduled_utc,  # datetime, already UTC
        forecast=forecast or None,
        actual=actual or None,
    ))
    return events
```

**BAD** — trusting external timestamps without normalization:
```python
event.time = row["time"]  # "8:30am" — what timezone? ET? UTC? local?
```

**GOOD** — explicit timezone conversion at the boundary:
```python
ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

def _parse_event_time(self, date: datetime, time_str: str) -> datetime:
    """Parse FF time (e.g., '8:30am') as ET, return UTC."""
    t = datetime.strptime(time_str.strip().lower(), "%I:%M%p")
    et_time = date.replace(hour=t.hour, minute=t.minute, second=0, tzinfo=ET)
    return et_time.astimezone(UTC).replace(tzinfo=None)  # naive UTC for storage
```

---

## 5. Retry & Resilience

Transient failures should retry. Persistent failures should fail fast.

**BAD** — one network hiccup kills the entire calendar refresh:
```python
async def refresh_calendar(self):
    events = await self._scraper.fetch_week()  # network error = crash
    await self._store.save_events(events)
```

**GOOD** — retry transient failures, log and continue on persistent ones:
```python
async def refresh_calendar(self) -> None:
    """Fetch and store upcoming events. Tolerates transient failures."""
    try:
        events = await self._scraper.fetch_week()
        filtered = self._parser.filter_events(events)
        await self._event_store.save_events(filtered)
        logger.info(f"Calendar refreshed: {len(filtered)} target events")
    except httpx.TimeoutException:
        logger.warning("Calendar refresh timed out, will retry next cycle")
    except httpx.HTTPStatusError as e:
        logger.error(f"Calendar HTTP error {e.response.status_code}, skipping")
    except Exception as e:
        logger.error(f"Calendar refresh failed unexpectedly: {e}")
```

**BAD** — retry loop with no backoff, hammers a failing service:
```python
async def connect_with_retry(self):
    while True:
        try:
            await self.connect()
            break
        except ConnectionError:
            await asyncio.sleep(1)  # retry every second forever
```

**GOOD** — exponential backoff with a cap:
```python
async def connect_with_retry(self, max_attempts: int = 5) -> None:
    for attempt in range(max_attempts):
        try:
            await self.connect()
            return
        except ConnectionError as e:
            if attempt == max_attempts - 1:
                raise
            wait = min(2 ** attempt, 30)  # 1, 2, 4, 8, 16, 30 seconds
            logger.warning(f"Connection failed (attempt {attempt + 1}), retrying in {wait}s: {e}")
            await asyncio.sleep(wait)
```

---

## 6. IB-Specific Patterns

IB's API has unique constraints that differ from REST APIs.

**BAD** — using contract without qualification (IB may reject or return wrong data):
```python
contract = Forex("EURUSD")
bars = await ib.reqHistoricalDataAsync(contract, ...)  # may fail silently
```

**GOOD** — always qualify contracts first:
```python
contract = Forex("EURUSD")
ib.qualifyContracts(contract)  # resolves conId, exchange, etc.
bars = await ib.reqHistoricalDataAsync(contract, ...)
```

**BAD** — ignoring IB's daily reset, bot dies at 11:45 PM ET:
```python
# Bot starts, connects once, assumes connection lasts forever
await client.connect()
# ... hours later at 11:45 PM ET, connection drops, bot is dead
```

**GOOD** — health check detects and recovers from disconnection:
```python
# Scheduled every 5 minutes:
async def _health_check(self) -> None:
    if not self._client.is_connected:
        logger.warning("IB connection lost during health check")
        try:
            await self._client.connect()
            logger.info("IB reconnection successful")
        except Exception as e:
            logger.error(f"IB reconnection failed: {e}")
```

---

## 7. Testing External APIs

**BAD** — unit test hits real IB/FF, flaky, slow, requires infrastructure:
```python
async def test_get_snapshot():
    client = IBClient()
    await client.connect()  # needs real IB Gateway running!
    pricing = PricingService(client)
    snapshot = await pricing.get_snapshot("EURUSD")
    assert snapshot.bid > 0
```

**GOOD** — mock at the boundary, test your logic in isolation:
```python
async def test_get_snapshot(mock_ib_client):
    mock_ib_client.ib.reqMktData.return_value = MagicMock(bid=1.0850, ask=1.0852)
    pricing = PricingService(mock_ib_client)
    snapshot = await pricing.get_snapshot("EURUSD")
    assert snapshot.bid == 1.0850
    assert snapshot.spread_pips() == pytest.approx(2.0)
```

**GOOD** — integration test clearly marked, only runs when IB is available:
```python
@pytest.mark.integration
async def test_ib_connection_live():
    """Requires IB Gateway running on port 4002."""
    async with IBClient() as client:
        summary = await client.get_account_summary()
        assert summary.net_liquidation > 0
```

When implementing or debugging API integrations, apply these patterns and flag violations with corrected code.
