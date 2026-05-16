# Debug Helper

Help me debug an issue with: $ARGUMENTS

## Debugging Approach
1. **Reproduce** — identify the exact error message, stack trace, or unexpected behavior
2. **Isolate** — narrow down which module/function is causing the issue
3. **Hypothesize** — form a theory about the root cause based on the code
4. **Verify** — read the relevant source code, check types, trace data flow
5. **Fix** — make the minimal change that resolves the issue
6. **Prevent** — add a test that catches this regression

## Common Issues in This Project

### IB Connection
- Is IB Gateway running? Check port 4002 (paper) or 4001 (live)
- Client ID conflict? Only one connection per clientId
- Market data subscription? Paper accounts may need explicit subscription
- Daily disconnect? Check if time is near 11:45 PM ET

### Async Issues
- Event loop already running? Use `nest_asyncio` or restructure
- Deadlock? Check for awaiting something that awaits back
- Task cancelled? Check shutdown handlers and signal handling

### Data Issues
- Timezone mismatch? FF is ET, IB can be local or UTC, we store UTC
- Stale cache? `get_settings()` uses `@lru_cache` — won't pick up runtime changes
- Missing DB tables? Run `await init_db()` first

### Strategy Issues
- No signals? Check: event matched filters? surprise above threshold? spread under limit?
- Risk rejection? Check circuit breaker state and all rule validations
- Wrong direction? Verify USD base/quote logic in surprise strategy

Read the relevant code, trace the issue, and propose a fix.
