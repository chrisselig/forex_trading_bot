# API Integration Patterns

When I'm working with external APIs (IB, Forex Factory, FRED), follow these patterns:

## HTTP Client (httpx)
- Always use async client: `async with httpx.AsyncClient() as client`
- Set explicit timeouts: `timeout=30.0`
- Set a descriptive User-Agent header
- Handle rate limits with exponential backoff
- Log request/response at DEBUG level (never log sensitive headers)

## IB API (ib_async)
- Connection pattern: `ib = IB(); await ib.connectAsync(host, port, clientId)`
- Always check `ib.isConnected()` before operations
- Use `ib.qualifyContracts(contract)` before trading
- Subscribe to events: `ib.orderStatusEvent += handler`
- Handle the daily disconnect (~11:45 PM ET) gracefully
- Respect pacing limits (60 historical requests per 10 min)
- Forex contracts: `Forex('EURUSD')` — 6 chars, no separator

## Error Handling for APIs
- Retry transient failures (network timeouts, 5xx responses) with backoff
- Fail fast on client errors (4xx, invalid contracts)
- Circuit break on repeated failures (don't hammer a dead service)
- Always have a timeout — never wait indefinitely
- Log the full error context for debugging

## Data Parsing
- Parse external data into Pydantic models immediately at the boundary
- Normalize timestamps to UTC on ingestion
- Handle missing/null fields gracefully (Optional types)
- Validate numeric ranges (prices should be positive, quantities > 0)

## Caching
- Cache calendar data (refresh every 6 hours, not every request)
- Cache account summary (refresh every few minutes, not every order)
- Never cache real-time prices — always fetch fresh

## Testing APIs
- Unit tests: mock all HTTP/socket calls with `unittest.mock`
- Use recorded responses (fixtures) for deterministic tests
- Integration tests: mark with `@pytest.mark.integration`, run separately
- Never hit production APIs in automated tests

When I'm implementing or debugging API integrations, apply these patterns and flag any violations.
