# Forex Trading Bot — Project Instructions

## Project Overview

Event-driven forex trading bot for major US economic news releases. Uses Interactive Brokers (IBKR) via `ib_async`. Runs on paper trading (port 4002) or live (port 4001).

## Architecture

- **Language**: Python 3.12+
- **Broker**: Interactive Brokers via `ib_async` (socket API, not REST)
- **Database**: SQLite via SQLAlchemy 2.0 (async with aiosqlite)
- **Scheduling**: APScheduler (AsyncIOScheduler)
- **CLI**: Typer + Rich
- **Config**: YAML + Pydantic Settings + .env

## Directory Layout

```
src/forex_bot/       # All source code
  broker/            # IB connection, orders, pricing, contracts
  calendar/          # Forex Factory scraper, FRED client, event store
  strategy/          # BaseStrategy ABC, straddle, surprise
  risk/              # RiskManager, CircuitBreaker, rules
  execution/         # Signal -> validated order -> IB pipeline
  data/              # SQLAlchemy schemas, trade journal
  scheduler/         # Orchestrator, jobs, shutdown
  reporting/         # Performance stats, Rich dashboard
config/              # settings.yaml, events.yaml
tests/               # unit/, integration/, backtest/
scripts/             # Standalone utility scripts
```

## Key Conventions

### Git Workflow (NON-NEGOTIABLE)
- **Always create a feature branch** for new features, bug fixes, and refactors. Never commit directly to `main` unless the user explicitly says "commit to main" or "push directly".
- Branch naming: `feat/short-description`, `fix/short-description`, `docs/short-description`
- Open a PR via `gh pr create` when the branch is ready for review/merge.
- Small doc-only changes or config tweaks may go directly to `main` if the user requests it.

### Code Style
- Use `from __future__ import annotations` in all modules
- Type hints on all function signatures
- Pydantic models for all data structures (not dataclasses for domain models)
- `StrEnum` for enumerations
- Async/await throughout — never use synchronous blocking calls in the event loop
- `loguru` for all logging (not stdlib `logging`)

### Naming
- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions/methods: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private: prefix with `_`

### Imports
- Group: stdlib, third-party, local (separated by blank lines)
- Absolute imports within the package: `from forex_bot.broker.client import IBClient`

### Error Handling
- All custom exceptions inherit from `ForexBotError` (in `broker/exceptions.py`)
- Never catch bare `Exception` in production paths — be specific
- Log errors with context before re-raising

### Testing
- Unit tests mock IB with `unittest.mock` — never hit real IB in unit tests
- Integration tests marked with `@pytest.mark.integration` (require IB Gateway)
- All async tests use `pytest-asyncio`
- Fixtures in `tests/conftest.py`

### Risk Management (NON-NEGOTIABLE)
- Every trade MUST pass through: `Signal -> RiskManager.validate() -> CircuitBreaker.check() -> ExecutionEngine`
- Never bypass risk checks. No shortcut paths to order placement.
- All orders MUST have a stop loss (MandatoryStopLoss rule)
- Circuit breaker HALTED state requires manual reset — never auto-reset

### Analysis-Driven Configuration (NON-NEGOTIABLE)
- **Never enable a pair or set strategy parameters that contradict the latest Monte Carlo analysis.** The most recent analysis report lives in `docs/research/monte-carlo-2020-2026.md`. The "Recommended Settings" and "Production recommendation" sections are the source of truth.
- If analysis says "avoid" or "do not trade" a pair, do NOT add it to `trading.instruments` or `strategy.straddle_pair_overrides` in `config/settings.yaml`.
- If you are about to enable a pair or change parameters that the analysis warns against, **STOP and warn the user** before making the change. Explain what the analysis says and ask for explicit confirmation.
- When a new Monte Carlo analysis is run, update `config/settings.yaml` to match — but only for pairs the analysis recommends trading.

### Timestamps
- Internal: always UTC (naive datetime or timezone-aware UTC)
- Forex Factory: Eastern Time — convert with `zoneinfo.ZoneInfo("America/New_York")`
- Display to user: Eastern Time (industry standard for US releases)
- Database: UTC
- APScheduler: UTC timezone

### Configuration
- Never hardcode connection params, risk limits, or strategy params
- All tunables go in `config/settings.yaml`
- Secrets (FRED_API_KEY) go in `.env` (never committed)
- Access config via `get_settings()` (cached singleton)

## Common Commands

```bash
# Run all unit tests
pytest tests/unit/ -v

# Run the bot (requires IB Gateway on port 4002)
forex-bot run

# Test IB connectivity
forex-bot test-connection

# Show upcoming events
forex-bot events

# Show performance stats
forex-bot performance
```

## IB-Specific Notes

- IB Gateway must be running locally before the bot can connect
- Paper: port 4002, Live: port 4001
- No API keys — auth is via IB Gateway login
- Daily disconnect at ~11:45 PM ET — bot auto-reconnects
- Forex contracts: `Forex('EURUSD')` — no separator, no slash
- Pacing: max 60 historical data requests per 10 minutes

## Alberta/Canada Notes

- OANDA is NOT available in Alberta — never suggest it
- IBKR is IIROC registered, available in all Canadian provinces
- IIROC enforces leverage caps — IB handles this automatically
