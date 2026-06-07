# Forex Trading Bot

**[Documentation](https://chrisselig.github.io/forex_trading_bot/)**

An event-driven forex trading bot that trades major US economic news releases (NFP, CPI, FOMC, GDP, etc.) using Interactive Brokers. Built for a Canadian trader in Alberta where OANDA is not available due to provincial regulatory constraints.

The bot sleeps between events, wakes up before scheduled releases, executes pre-configured strategies, enforces strict risk management, and logs everything for review.

---

## How It Works

```
                    ┌──────────────┐
                    │ Forex Factory│
                    │   Calendar   │
                    └──────┬───────┘
                           │ scrape + filter
                    ┌──────▼───────┐
                    │  Event Store │ (SQLite)
                    └──────┬───────┘
                           │ schedule jobs
                    ┌──────▼───────┐
                    │  APScheduler │
                    │ Orchestrator │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │                         │
     ┌────────▼─────────┐    ┌─────────▼────────┐
     │ Pre-Event (T-30m) │    │ Post-Event (T+5s) │
     │   Straddle Strat  │    │  Surprise Strat   │
     └────────┬──────────┘    └─────────┬─────────┘
              │                         │
              └────────────┬────────────┘
                           │ Signal
                    ┌──────▼───────┐
                    │ Risk Manager │ ← mandatory, no bypass
                    │ + Circuit    │
                    │   Breaker    │
                    └──────┬───────┘
                           │ validated
                    ┌──────▼───────┐
                    │  Execution   │
                    │   Engine     │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  TWS / IB    │ (localhost:7497)
                    │  via ib_async│
                    └──────────────┘
```

1. **Calendar scraper** fetches high-impact USD events from Forex Factory
2. **Scheduler** sets up jobs: pre-event (T minus 30 min) and post-event (T plus 5 sec)
3. **Strategies** generate trading signals based on price action and data surprises
4. **Risk manager** validates every signal against 5 rules + circuit breaker — no exceptions
5. **Execution engine** places orders on IB with bracket stop-loss/take-profit
6. **Trade journal** logs every order, fill, and close to SQLite for review

---

## Strategies

### Straddle (Pre-Event)

Places a buy-stop above and sell-stop below the current price before a scheduled release. Whichever direction the market breaks, one leg triggers with a bracket (TP + SL). The other leg gets cancelled.

- Activates 30 minutes before event (configurable)
- Distance, TP, and SL are configurable in pips
- Uses IB bracket orders with native OCA groups

### Surprise (Post-Event)

After the data is released, compares actual vs forecast. If the surprise magnitude exceeds a threshold, trades in the direction of the surprise.

- Positive NFP surprise → USD strength → SELL EUR/USD
- Handles inverse indicators (unemployment up = USD weakness)
- Configurable threshold, entry delay, TP, and SL

---

## Risk Management

Every trade must pass through the full validation pipeline. There are no shortcuts.

```
Signal → RiskManager.validate() → CircuitBreaker.check() → ExecutionEngine → IB
```

### Rules

| Rule | Default | Description |
|------|---------|-------------|
| Mandatory Stop Loss | always on | Every order must have a stop loss |
| Max Risk Per Trade | 1% | Max account risk per trade |
| Max Daily Drawdown | 3% | Halts trading for the day |
| Max Concurrent Positions | 3 | Limits open position count |
| Max Spread | 15 pips | Rejects trades during wide spreads (wider for exotics) |

### Circuit Breaker

Three states: **ACTIVE** → **COOLDOWN** → **HALTED**

- **COOLDOWN** triggers on consecutive losses (default: 5). Auto-recovers after 30 minutes.
- **HALTED** triggers when daily drawdown exceeds the limit. Requires manual reset — the bot will not auto-resume. This is intentional.

---

## Project Structure

```
forex_trading_bot/
├── config/
│   ├── settings.yaml          # Trading params, risk limits, IB config
│   └── events.yaml            # Target events (NFP, CPI, FOMC, etc.)
├── src/forex_bot/
│   ├── cli.py                 # Typer CLI (7 commands)
│   ├── config.py              # Pydantic settings loader
│   ├── models/                # Pydantic data models
│   ├── broker/                # IB connection, orders, pricing, contracts
│   ├── calendar/              # Forex Factory scraper, FRED client
│   ├── strategy/              # BaseStrategy, straddle, surprise
│   ├── risk/                  # Risk rules, circuit breaker
│   ├── execution/             # Signal → order pipeline
│   ├── data/                  # SQLAlchemy schemas, trade journal
│   ├── scheduler/             # APScheduler orchestrator
│   └── reporting/             # Performance stats, Rich dashboard
├── tests/
│   ├── unit/                  # 42 tests, all mocked, fast
│   ├── integration/           # Live IB tests (requires Gateway)
│   └── backtest/              # Historical event replay
├── scripts/
│   ├── check_ib_connection.py
│   └── fetch_historical_events.py
├── CLAUDE.md                  # Project conventions for AI assistance
└── .claude/commands/          # Slash command skills
```

---

## Prerequisites

### 1. Interactive Brokers Account

Sign up at [interactivebrokers.com](https://www.interactivebrokers.com). Select paper trading to start.

IBKR is IIROC registered and available in all Canadian provinces, including Alberta.

### 2. TWS or IB Gateway

Download [TWS](https://www.interactivebrokers.com/en/trading/tws.php) (full desktop) or [IB Gateway](https://www.interactivebrokers.com/en/trading/ibgateway-stable.php) (lightweight headless).

Configure the API socket in TWS:
1. **File → Global Configuration → API → Settings**
2. Check **"Enable ActiveX and Socket Clients"**
3. Confirm socket port: **7497** (TWS paper) / **7496** (TWS live) / **4002** (Gateway paper) / **4001** (Gateway live)
4. Uncheck **"Read-Only API"** (required for order placement)
5. Click **Apply / OK**

### 3. FRED API Key (Optional)

For historical economic data, get a free key at [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html).

### 4. Python 3.11+

```bash
python3 --version  # must be 3.11 or higher
```

---

## Installation

```bash
# Clone
git clone git@github.com:chrisselig/forex_trading_bot.git
cd forex_trading_bot

# Create conda environment
conda create -n forex-bot python=3.12 -y
conda activate forex-bot

# Install
pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env — set IB_PORT and FRED_API_KEY
```

### .env setup

```bash
FRED_API_KEY=your_key_here   # Free from fred.stlouisfed.org
IB_HOST=127.0.0.1
IB_PORT=7497                 # 7497=TWS paper, 7496=TWS live, 4002=Gateway paper
IB_CLIENT_ID=1

# IB Login Credentials (used by IBC auto-start)
IB_USERNAME=your_ib_username
IB_PASSWORD=your_ib_password
```

---

## Configuration

### config/settings.yaml

```yaml
broker:
  host: "127.0.0.1"
  port: 4002          # Overridden by IB_PORT in .env
  client_id: 1
  timeout: 30

trading:
  instruments:
    - USDZAR
    - USDTRY
    - GBPJPY
    - GBPUSD
    - USDCAD
  default_timeframe: "5 mins"

risk:
  max_risk_per_trade_pct: 1.0
  max_daily_drawdown_pct: 3.0
  max_concurrent_positions: 3
  mandatory_stop_loss: true
  max_spread_pips: 15.0       # Wider for exotic pairs (USDZAR, USDTRY)

strategy:
  pre_event_minutes: 30
  post_event_minutes: 60
  straddle_distance_pips: 20
  straddle_tp_pips: 30
  straddle_sl_pips: 15
  surprise_threshold_pct: 10.0
  surprise_entry_delay_seconds: 5
  surprise_tp_pips: 25
  surprise_sl_pips: 15
  max_holding_minutes: 120
```

### config/events.yaml

Defines which economic events to trade. Each event has a name, aliases (for matching Forex Factory titles), FRED series ID, and affected currency pairs.

Pre-configured events: NFP, CPI, FOMC, GDP, Jobless Claims, ISM Manufacturing, PPI, Retail Sales, Unemployment Rate.

### .env

Environment variables override YAML settings. See the [Installation](#installation) section for setup.

---

## Usage

### Start the Bot

```bash
conda activate forex-bot
forex-bot run
```

The bot will:
1. Connect to TWS/IB Gateway
2. Reconcile any open positions/orders
3. Fetch the economic calendar
4. Schedule pre/post event jobs
5. Run health checks every 5 minutes (auto-reconnects and re-schedules jobs on disconnect)
6. Refresh the calendar every 6 hours
7. Gracefully shutdown on Ctrl+C

### Auto-Start (Recommended)

The bot can start fully unattended via a cron job + IBC (IB Controller). A startup script handles the full sequence:

1. Reads IB credentials from `.env` (`IB_USERNAME`, `IB_PASSWORD`)
2. Launches TWS via IBC with auto-login and auto-dialog dismissal
3. Waits for the API socket to be ready
4. Starts the forex bot

**Cron**: runs at 5:00 AM MT (7:00 AM ET) on weekdays — well before the earliest US data releases.

**2FA**: Paper trading accounts do **not** require 2FA, so auto-start is fully unattended. Live trading accounts will require 2FA via the IBKR Mobile app — you'll need to approve the push notification on your phone within 3 minutes (IBC auto-retries if you miss it).

To run manually:
```bash
~/00_data_projects/forex_trading_bot/scripts/start_tws_and_bot.sh
```

### Before a Trading Day (Manual Start)

1. Open TWS and log into your paper (or live) account
2. Ensure the API socket is enabled (File → Global Configuration → API → Settings)
3. Start the bot: `conda activate forex-bot && forex-bot run`
4. The bot will auto-schedule jobs for upcoming events and handle reconnections

### Reconnection Behavior

- TWS disconnects nightly at ~11:45 PM ET
- The bot's health check (every 5 min) detects the drop, reconnects, refreshes the calendar, and re-schedules event jobs
- If TWS is restarted manually, the bot will reconnect on the next health check cycle
- Pre-flight connection check runs 2 minutes before each event to ensure IB is connected
- Event handlers retry with backoff (5s, 15s, 30s) if IB is disconnected when they fire

### Managing Processes

**When to kill processes:**
- Before running the startup script if an old bot or TWS instance is still running
- When the bot is stuck or unresponsive
- When you want to restart with new configuration

**How to kill processes:**

```bash
# Kill the forex bot
pkill -9 -f "forex-bot run"

# Kill TWS / IBC
pkill -9 -f "java.*jts"

# Verify nothing is running
ps aux | grep -E "forex-bot|java.*jts" | grep -v grep

# Check if the API socket is still open
ss -tlnp | grep 7497
```

**Process lifecycle:**
- `forex-bot run` — the Python trading bot process. Handles SIGTERM gracefully, but sometimes needs `kill -9`
- `java.*jts` — the TWS Java process launched by IBC. Kill this to fully stop TWS
- The startup script checks for existing processes and skips launch if they're already running, so kill old processes first if you want a fresh start

### Resetting the Paper Account

To clear all positions and reset the paper account balance:
1. Go to the [IB Client Portal](https://www.interactivebrokers.com/portal)
2. Log in → **Settings → Account Settings → Paper Trading Account → Reset**
3. The reset takes a few minutes to process

### CLI Commands

```bash
forex-bot run              # Start autonomous trading
forex-bot status           # Show account summary and positions
forex-bot events           # Show upcoming high-impact USD events
forex-bot history          # Show recent trades
forex-bot performance      # Show P&L, win rate, Sharpe, per-strategy stats
forex-bot test-connection  # Verify IB Gateway connectivity
forex-bot backtest         # Run historical backtest
```

### Quick Connectivity Check

```bash
# Or use the standalone script:
python scripts/check_ib_connection.py
```

This connects to IB Gateway, prints your account summary, and fetches one historical bar to verify everything works.

---

## Testing

```bash
# Run all unit tests (fast, no IB required)
pytest tests/unit/ -v

# Run with coverage
pytest tests/unit/ --cov=forex_bot --cov-report=term-missing

# Run integration tests (requires IB Gateway on port 4002)
pytest tests/integration/ -v -m integration
```

59 unit tests cover: models, contracts, config loading, risk rules, circuit breaker state machine, straddle signal generation, surprise direction logic, unemployment indicator inversion, per-pair straddle overrides, and event handler retry/pre-flight logic.

---

## Technology Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python 3.11+ | Best ecosystem for trading bots, async support |
| Broker API | `ib_async` | Actively maintained IB TWS wrapper (successor to `ib_insync`) |
| HTTP Client | `httpx` | Async HTTP for calendar scraping and FRED |
| Calendar | Forex Factory + FRED | FF is the gold standard for retail forex calendars |
| Database | SQLite via SQLAlchemy 2.0 | No external DB to manage for a single-user bot |
| Scheduling | APScheduler | Mature, supports cron + event-driven job patterns |
| CLI | Typer + Rich | Professional terminal interface |
| Config | YAML + Pydantic Settings | Type-safe, layered configuration |
| Logging | Loguru | Structured logging with rotation |
| Testing | pytest + pytest-asyncio | Full async test support with mocking |

---

## IB API Notes

Interactive Brokers uses a **socket-based API**, not REST. Key differences:

- **IB Gateway must be running locally** — it's a Java app that the bot connects to on localhost
- **No API key or token** — authentication is handled by IB Gateway's own login
- **Event-driven** — IB pushes data via events, `ib_async` wraps them as awaitables
- **Forex contracts** — represented as `Forex('EURUSD')`, not string tickers
- **Daily reset** — TWS/IB Gateway auto-disconnects at ~11:45 PM ET. The bot's health check detects this, reconnects, and re-schedules event jobs
- **Pacing limits** — max 60 historical data requests per 10 minutes. The pricing service throttles automatically
- **Paper trading** — same API, different port. TWS: 7497 (paper) / 7496 (live). Gateway: 4002 (paper) / 4001 (live)

---

## Canadian Notes

- **Broker**: Interactive Brokers Canada, IIROC registered, available in all provinces including Alberta
- **OANDA**: Not available in Alberta due to provincial regulatory constraints
- **Leverage**: IIROC caps leverage. IB enforces margin requirements per IIROC rules automatically
- **Paper account**: Free, same API as live, port 4002
- **Market data**: Paper accounts include delayed forex data by default. Real-time forex data is free on live accounts but requires a market data subscription on paper
- **Tax**: Forex gains may be reported as capital gains (50% inclusion rate) or business income depending on CRA assessment. This bot does not provide tax advice — consult a tax professional

---

## Timezone Strategy

| Context | Timezone |
|---------|----------|
| Internal storage | UTC (always) |
| Database | UTC |
| APScheduler | UTC |
| Forex Factory source | Eastern Time (America/New_York) |
| IB timestamps | Normalized to UTC on ingestion |
| User display | Converted to ET (industry standard for US releases) |

Timezone conversion uses Python's `zoneinfo` module which handles EST/EDT transitions automatically.

---

## License

Private project. Not for redistribution.
