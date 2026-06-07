# IB API Notes

Interactive Brokers uses a **socket-based API**, not REST. This has significant implications for how the bot is built and operated.

## Key Differences from REST APIs

- **IB Gateway/TWS must be running locally** — it's a Java app that the bot connects to on localhost
- **No API key or token** — authentication is handled by IB Gateway's own login
- **Event-driven** — IB pushes data via events; `ib_async` wraps them as awaitables
- **Forex contracts** — represented as `Forex('EURUSD')`, not string tickers. No separator, no slash.
- **Pacing limits** — max 60 historical data requests per 10 minutes. The pricing service throttles automatically.

## Ports

| Configuration | Port |
|---------------|------|
| TWS paper | 7497 |
| TWS live | 7496 |
| Gateway paper | 4002 |
| Gateway live | 4001 |

## Daily Reset

TWS/IB Gateway auto-disconnects at ~11:45 PM ET. This is an IB maintenance window and cannot be disabled. The bot's health check detects the disconnect, reconnects after the maintenance window, and re-schedules all event jobs.

## Paper vs Live

Same API, different port. Paper trading accounts:

- Do **not** require 2FA (fully unattended operation)
- Include delayed forex data by default
- Have different market data subscriptions than live accounts
- Use the same order types, contract definitions, and risk checks
