# Debug Helper

Help me debug an issue with: $ARGUMENTS

---

## Debugging Protocol

Work through this systematically. Do NOT guess — read code and trace data.

### Step 1: Reproduce
- Get the exact error message, full stack trace, or description of wrong behavior
- Identify the input that triggered it (which event, which pair, what time)
- Determine if it's consistent or intermittent

### Step 2: Isolate
- Trace the call chain from the error back to the entry point
- Read the source code of every function in the chain
- Identify where the actual value diverges from the expected value

### Step 3: Root Cause
- Don't stop at the symptom. The line that throws is rarely the line that's wrong.

**BAD** diagnosis — fixing the symptom:
```python
# Error: KeyError: 'NetLiquidation' in get_account_summary()
# "Fix": add a try/except
data.get("NetLiquidation", 0)  # masks the real problem
```

**GOOD** diagnosis — finding the root cause:
```python
# Why is 'NetLiquidation' missing from the dict?
# → accountSummaryAsync() returned empty list
# → because IB Gateway was in "sleep" state after daily reset
# → health check should have reconnected but didn't fire
# Real fix: ensure health check runs and reconnects properly
```

### Step 4: Fix
- Make the minimal change that addresses the root cause
- Don't refactor unrelated code in the same fix

### Step 5: Prevent
- Write a test that would have caught this bug
- Consider if a type change or validation could prevent the entire category of bug

---

## Common Issue Catalog

### IB Connection Issues

**Symptom**: `ConnectionError: Failed to connect to IB Gateway at 127.0.0.1:4002`
- Is IB Gateway / TWS actually running? Check with `lsof -i :4002`
- Is another bot instance using the same `clientId`? Each connection needs a unique ID
- Did IB Gateway restart? It auto-restarts daily around 11:45 PM ET

**Symptom**: `asyncio.TimeoutError` during `connectAsync`
- IB Gateway might be in the login screen (not authenticated)
- Firewall blocking localhost? Unlikely but check
- `timeout` setting too low in config (default 30s should be fine)

**Symptom**: Connected but no market data
```python
# ticker.bid is 0 or None
```
- Paper accounts need explicit market data subscription in IB Account Management
- You may be requesting data outside market hours (forex is 24/5, closed weekends)
- Did you call `ib.qualifyContracts(contract)` first?
- Delayed data is normal on paper — real-time requires subscription

**Symptom**: `Pacing violation` error from IB
```
# "Historical data request pacing violation"
```
- You've exceeded 60 historical data requests in 10 minutes
- The `PricingService._throttle()` method should handle this
- If it's not throttling, check if `_request_timestamps` is being shared across instances (class variable vs instance variable)

---

### Async Issues

**Symptom**: `RuntimeError: This event loop is already running`
```python
# Happens when calling asyncio.run() inside an already-running loop
```
- Don't call `asyncio.run()` from within async code
- In CLI commands, use `asyncio.run()` only at the top level
- In tests, use `@pytest.mark.asyncio` instead of `asyncio.run()`

**Symptom**: Code appears to hang / deadlock
```python
# Common cause — awaiting something that awaits you back
async def a():
    result = await b()  # b waits for a to finish first = deadlock

# Another cause — blocking call in async context
async def fetch():
    response = requests.get(url)  # BLOCKS the entire event loop
```
- Search for `requests.` (should be `httpx`), `time.sleep` (should be `asyncio.sleep`)
- Check for synchronous file I/O without `asyncio.to_thread()`

**Symptom**: `Task was destroyed but it is pending`
```python
# Fire-and-forget task that wasn't awaited or tracked
asyncio.create_task(some_coro())  # no reference kept, gets GC'd
```
- Store task references: `self._tasks.append(asyncio.create_task(...))`
- Use `task.add_done_callback()` to catch exceptions

---

### Data & Timezone Issues

**Symptom**: Events show up at wrong times, strategies fire too early/late
```python
# Common cause: mixing naive and aware datetimes
event.scheduled_at = datetime(2024, 1, 5, 8, 30)  # is this UTC? ET? local?
```
- All internal datetimes MUST be naive UTC
- Forex Factory times are ET — must convert: `et_time.astimezone(UTC).replace(tzinfo=None)`
- Display to user should convert back to ET: `utc_time.replace(tzinfo=UTC).astimezone(ET)`
- Check: `print(event.scheduled_at)` — does 8:30 AM NFP show as 13:30 (UTC)? If not, TZ is wrong.

**Symptom**: Duplicate events in database
```python
# Dedup check isn't matching because of timestamp precision
# 2024-01-05 13:30:00 != 2024-01-05 13:30:00.123456
```
- Check the dedup query — does it compare only `title + scheduled_at`?
- Are incoming timestamps consistent (always truncated to minute)?

**Symptom**: `get_settings()` returns stale config after editing YAML
```python
@lru_cache
def get_settings() -> Settings:
    return load_settings()  # cached forever after first call
```
- `@lru_cache` means the settings are loaded once and never refreshed
- In production this is correct (config doesn't change at runtime)
- In development, restart the bot after changing config
- In tests, use `get_settings.cache_clear()` in fixtures

---

### Strategy Issues

**Symptom**: No signals generated for an event
Walk through the chain:
1. Was the event fetched? Check `forex-bot events`
2. Did it match filters? Check `country == "USD"` and `impact == "high"`
3. Did it match a target? Check `events.yaml` aliases vs actual FF title
4. For surprise strategy: is `actual` populated? Is `surprise_pct > threshold`?
5. Was the spread too wide? Check `MaxSpread` rule

**Symptom**: Wrong trade direction on surprise
```python
# NFP beats forecast (positive surprise) but bot buys EURUSD instead of selling
```
The logic chain:
1. Positive NFP = USD strength → `usd_positive = True`
2. EURUSD: USD is quote currency → USD strength = SELL EURUSD
3. BUT: unemployment-type indicators are inverted — higher = USD weakness
4. Check: is `event.title` matching one of `["unemployment", "jobless", "claims"]`?
5. Check: is `instrument.startswith("USD")` returning the right value?

**Symptom**: Risk manager rejects every trade
```python
# "Risk violations for EURUSD: ['Stop loss is mandatory for all trades']"
```
- Strategy must set `signal.stop_loss` — check the strategy's signal construction
- Check `signal.quantity` — if 0, position sizing runs but needs `signal.price` and `signal.stop_loss`
- Check circuit breaker: `cb.state` might be HALTED from a previous session (state is in-memory, doesn't persist across restarts)

---

### Database Issues

**Symptom**: `sqlalchemy.exc.OperationalError: no such table: events`
```python
# init_db() was never called
```
- The orchestrator calls `await init_db()` on startup
- Scripts must call it too: `await init_db()` before any DB operations
- Check that `DATA_DIR` exists and is writable

**Symptom**: `IntegrityError` or constraint violations
- Check for duplicate inserts — the `save_events` method should dedup
- Check for NULL in NOT NULL columns — trace which field is missing from the source data

---

Read the relevant source code, trace the data flow, identify the root cause, propose the minimal fix, and write a test that prevents regression.
