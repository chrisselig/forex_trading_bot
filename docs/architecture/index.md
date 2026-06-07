# Architecture

## System Design

The bot is event-driven. It does not poll or trade continuously. It schedules jobs around known economic events and executes them with strict risk controls.

```
src/forex_bot/
  broker/            # IB connection, orders, pricing, contracts
  calendar/          # Forex Factory scraper, FRED client, event store
  strategy/          # BaseStrategy ABC, straddle, surprise
  risk/              # RiskManager, CircuitBreaker, rules
  execution/         # Signal → validated order → IB pipeline
  data/              # SQLAlchemy schemas, trade journal
  scheduler/         # Orchestrator, jobs, shutdown
  reporting/         # Performance stats, Rich dashboard
```

## Pipeline

Every trade follows the same path. There are no shortcuts.

```
Calendar Event
    → Scheduler fires pre-event or post-event job
    → Strategy generates Signal
    → RiskManager.validate(signal)
    → CircuitBreaker.check()
    → ExecutionEngine places order on IB
    → Trade Journal logs result
```

## Technology Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python 3.11+ | Best ecosystem for trading bots, async support |
| Broker API | `ib_async` | Actively maintained IB TWS wrapper |
| HTTP Client | `httpx` | Async HTTP for calendar scraping and FRED |
| Calendar | Forex Factory + FRED | FF is the gold standard for retail forex calendars |
| Database | SQLite via SQLAlchemy 2.0 | No external DB to manage |
| Scheduling | APScheduler | Supports cron + event-driven job patterns |
| CLI | Typer + Rich | Professional terminal interface |
| Config | YAML + Pydantic Settings | Type-safe, layered configuration |
| Logging | Loguru | Structured logging with rotation |
| Testing | pytest + pytest-asyncio | Full async test support |

## Reconnection Behavior

- TWS disconnects nightly at ~11:45 PM ET
- Health check (every 5 min) detects the drop, reconnects, refreshes calendar, re-schedules jobs
- Pre-flight connection check runs 2 minutes before each event
- Event handlers retry with backoff (5s, 15s, 30s) if IB is disconnected when they fire
