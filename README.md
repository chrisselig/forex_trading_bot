# Forex Trading Bot

**[Documentation](https://chrisselig.github.io/forex_trading_bot/)** | [Glossary](https://chrisselig.github.io/forex_trading_bot/trading/glossary/) | [Strategies](https://chrisselig.github.io/forex_trading_bot/trading/strategies/) | [Risk Management](https://chrisselig.github.io/forex_trading_bot/trading/risk-management/) | [Monte Carlo Analysis](https://chrisselig.github.io/forex_trading_bot/research/monte-carlo-1min/) | [Roadmap](https://chrisselig.github.io/forex_trading_bot/research/todo/)

An event-driven forex trading bot that automatically trades major US economic news releases — [NFP](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#nfp-non-farm-payrolls), [CPI](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#cpi-consumer-price-index), and [FOMC](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#fomc-federal-open-market-committee) — using [Interactive Brokers](https://www.interactivebrokers.com). The bot sleeps between events, wakes up before scheduled releases, places [straddle](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#straddle) orders, enforces strict risk management, sends real-time [Telegram alerts](https://chrisselig.github.io/forex_trading_bot/operations/telegram-notifications/) to your phone, and logs everything to a trade journal.

Built for a Canadian trader in Alberta where OANDA is not available due to provincial regulatory constraints.

---

## Installation

### Prerequisites

Before installing the bot, you need three things: an Interactive Brokers account, their trading platform, and Python.

#### 1. Interactive Brokers Account

Sign up at [interactivebrokers.com](https://www.interactivebrokers.com). Start with a **paper trading account** (simulated money, same API, zero risk).

IBKR is [IIROC](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#iiroc-investment-industry-regulatory-organization-of-canada) registered and available in all Canadian provinces, including Alberta.

#### 2. TWS or IB Gateway

The bot connects to IB through a local application running on your machine. You have two options:

| Option | Best for | Download |
|--------|----------|----------|
| **TWS** (Trader Workstation) | Beginners — has a GUI to see what's happening | [Download TWS](https://www.interactivebrokers.com/en/trading/tws.php) |
| **IB Gateway** | Headless/server — lightweight, no GUI | [Download IB Gateway](https://www.interactivebrokers.com/en/trading/ibgateway-stable.php) |

After installing, configure the API socket:

1. Open TWS (or Gateway) and log in
2. Go to **File → Global Configuration → API → Settings**
3. Check **"Enable ActiveX and Socket Clients"**
4. Set the socket port:
   - `7497` — TWS paper trading
   - `7496` — TWS live trading
   - `4002` — Gateway paper trading
   - `4001` — Gateway live trading
5. Uncheck **"Read-Only API"** (the bot needs to place orders)
6. Click **Apply / OK**

#### 3. Python 3.11+

=== "Linux (Ubuntu/Debian)"

    ```bash
    sudo apt update
    sudo apt install python3.12 python3.12-venv python3-pip git
    python3.12 --version
    ```

=== "Windows"

    Download and install [Python 3.12](https://www.python.org/downloads/) from python.org.

    **Important**: During installation, check **"Add Python to PATH"**.

    Verify in PowerShell or Command Prompt:

    ```powershell
    python --version
    ```

#### 4. FRED API Key (Optional)

For historical economic data comparisons, get a free key at [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html). The bot works without it, but surprise detection is more accurate with FRED data.

---

### Clone and Install

=== "Linux"

    ```bash
    # Clone the repository
    git clone git@github.com:chrisselig/forex_trading_bot.git
    cd forex_trading_bot

    # Create a virtual environment
    python3.12 -m venv .venv
    source .venv/bin/activate

    # Install dependencies + the bot
    pip install -r requirements.txt
    pip install -e ".[dev]"
    ```

=== "Windows (PowerShell)"

    ```powershell
    # Clone the repository
    git clone git@github.com:chrisselig/forex_trading_bot.git
    cd forex_trading_bot

    # Create a virtual environment
    python -m venv .venv
    .venv\Scripts\Activate.ps1

    # Install dependencies + the bot
    pip install -r requirements.txt
    pip install -e ".[dev]"
    ```

    If you get an execution policy error on Windows, run:
    ```powershell
    Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
    ```

=== "Conda (Linux or Windows)"

    ```bash
    git clone git@github.com:chrisselig/forex_trading_bot.git
    cd forex_trading_bot

    conda create -n forex-bot python=3.12 -y
    conda activate forex-bot

    pip install -r requirements.txt
    pip install -e ".[dev]"
    ```

The `requirements.txt` has exact pinned versions from a tested environment. The `pyproject.toml` lists unpinned dependencies if you prefer flexibility.

---

### Configure

```bash
cp .env.example .env
```

Edit `.env` with your details:

```bash
# Interactive Brokers connection
IB_HOST=127.0.0.1
IB_PORT=4002                  # 7497=TWS paper, 7496=TWS live, 4002=Gateway paper, 4001=Gateway live
IB_CLIENT_ID=1

# IB Login Credentials (used by IBC auto-start script — see docs)
IB_USERNAME=your_ib_username
IB_PASSWORD=your_ib_password

# FRED API (free from https://fred.stlouisfed.org/docs/api/api_key.html)
FRED_API_KEY=your_fred_api_key_here

# Telegram Notifications (optional — leave empty to disable)
# Setup: message @BotFather on Telegram to create a bot and get a token
# Then message your bot and visit https://api.telegram.org/bot<TOKEN>/getUpdates to get your chat ID
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

See the [Telegram Notifications guide](https://chrisselig.github.io/forex_trading_bot/operations/telegram-notifications/) for step-by-step setup.

---

### Verify Installation

Make sure TWS or IB Gateway is running and logged in, then:

```bash
# Test IB connectivity
forex-bot test-connection

# Or use the standalone script
python scripts/check_ib_connection.py
```

This connects to IB, prints your account summary, and fetches one historical bar to verify everything works. If it fails, check that TWS/Gateway is running and the port in `.env` matches your TWS API settings.

---

## Quick Start

```bash
# Start the bot
forex-bot run
```

The bot will:

1. Connect to TWS/IB Gateway
2. Reconcile any open positions/orders
3. Fetch the economic calendar from Forex Factory
4. Schedule jobs for upcoming events (pre-event straddle + post-event surprise)
5. Run health checks every 5 minutes (auto-reconnects on disconnect)
6. Refresh the calendar every 6 hours
7. Shut down gracefully on `Ctrl+C`

For unattended operation, see the [Auto-Start guide](https://chrisselig.github.io/forex_trading_bot/operations/auto-start/).

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
                    │  Execution   │──→ Telegram Alerts
                    │   Engine     │    (opens, fills, P&L)
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  TWS / IB    │ (localhost)
                    │  via ib_async│
                    └──────────────┘
```

1. **Calendar scraper** fetches high-impact USD events from Forex Factory
2. **Scheduler** sets up jobs: pre-event (T-30 min) and post-event (T+5 sec)
3. **Strategies** generate trading signals — see [Trading Strategies](https://chrisselig.github.io/forex_trading_bot/trading/strategies/)
4. **Risk manager** validates every signal against 5 rules + circuit breaker — no exceptions
5. **Execution engine** places orders on IB with bracket [stop-loss](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#sl-stop-loss)/[take-profit](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#tp-take-profit)
6. **Trade journal** logs every order, fill, and close to SQLite
7. **Telegram notifier** sends real-time alerts to your phone

---

## Active Trading Pairs

Based on [Monte Carlo analysis](https://chrisselig.github.io/forex_trading_bot/research/monte-carlo-1min/) with 1-minute Dukascopy data (June 2026):

| Pair | Status | E[P&L] | Why |
|------|--------|--------|-----|
| **USDZAR** | Active | +25.4 pips | Strongest performer, passed [walk-forward](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#walk-forward-validation) (OOS=+47.1) |
| **USDTRY** | Active | +13.9 pips | Strong full-sample, [Sharpe](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#sharpe-ratio) 3.14 |
| **GBPUSD** | Active | +6.1 pips | Promising but small sample (7 trades) |
| GBPJPY | Disabled | — | Severely overfit in walk-forward |
| USDCAD | Disabled | — | Marginal, [CI](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#95-ci-95-confidence-interval) spans zero |

Pairs are only enabled when analysis supports them. See [Analysis-Driven Configuration](https://chrisselig.github.io/forex_trading_bot/research/monte-carlo-1min/#walk-forward-validation) for details.

---

## Risk Management

Every trade must pass through the full validation pipeline. There are no shortcuts.

```
Signal → RiskManager.validate() → CircuitBreaker.check() → ExecutionEngine → IB
```

| Rule | Default | Description |
|------|---------|-------------|
| Mandatory Stop Loss | always on | Every order must have a [stop loss](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#sl-stop-loss) |
| Max Risk Per Trade | 1% | Max account risk per trade |
| Max Daily Drawdown | 3% | Halts trading for the day |
| Max Concurrent Positions | 3 | Limits open position count |
| Max Spread | 15 [pips](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#pip-percentage-in-point) | Rejects trades during wide [spreads](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#spread) |

The [circuit breaker](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#circuit-breaker) has three states: **ACTIVE → COOLDOWN → HALTED**. HALTED requires manual reset — the bot will not auto-resume. This is intentional.

See [Risk Management](https://chrisselig.github.io/forex_trading_bot/trading/risk-management/) for the full breakdown.

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
│   ├── notifications/         # Telegram trade alerts
│   ├── scheduler/             # APScheduler orchestrator
│   └── reporting/             # Performance stats, Rich dashboard
├── scripts/
│   ├── download_dukascopy.py         # Historical data from Dukascopy (1-min bars)
│   ├── monte_carlo_dukascopy.py      # Straddle parameter optimization (1-min)
│   ├── monte_carlo_straddle.py       # Straddle parameter optimization (1-hour)
│   ├── check_ib_connection.py        # Standalone connectivity test
│   └── start_tws_and_bot.sh         # Auto-start script for cron
├── tests/
│   ├── unit/                  # Fast, all mocked, no IB required
│   ├── integration/           # Live IB tests (requires Gateway)
│   └── backtest/              # Historical event replay
├── docs/                      # MkDocs Material documentation source
├── requirements.txt           # Pinned dependencies
├── pyproject.toml             # Package config + unpinned dependencies
└── CLAUDE.md                  # Project conventions for AI assistance
```

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

---

## Technology Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python 3.12+ | Best ecosystem for trading bots, async support |
| Broker API | [`ib_async`](https://github.com/ib-api-reloaded/ib_async) | Actively maintained IB TWS wrapper |
| HTTP Client | `httpx` | Async HTTP for calendar scraping, FRED, Telegram |
| Calendar | Forex Factory + FRED | FF is the gold standard for retail forex calendars |
| Database | SQLite via SQLAlchemy 2.0 | No external DB to manage for a single-user bot |
| Scheduling | APScheduler | Mature, supports cron + event-driven jobs |
| CLI | Typer + Rich | Professional terminal interface |
| Config | YAML + Pydantic Settings | Type-safe, layered configuration |
| Logging | Loguru | Structured logging with rotation |
| Notifications | Telegram Bot API | Free, real-time alerts to your phone |
| Testing | pytest + pytest-asyncio | Full async test support with mocking |
| Historical Data | [Dukascopy](https://www.dukascopy.com/) | Free 1-min OHLCV bars, no account needed |
| Docs | MkDocs Material | Auto-deploys to GitHub Pages on push |

---

## Documentation

The full documentation is at **[chrisselig.github.io/forex_trading_bot](https://chrisselig.github.io/forex_trading_bot/)**. Key pages:

- [Glossary](https://chrisselig.github.io/forex_trading_bot/trading/glossary/) — Every term, abbreviation, and metric explained in plain language
- [Market Structure](https://chrisselig.github.io/forex_trading_bot/trading/market-structure/) — How forex works
- [News Trading](https://chrisselig.github.io/forex_trading_bot/trading/news-trading/) — Why economic releases are the highest-edge opportunity
- [Trading Strategies](https://chrisselig.github.io/forex_trading_bot/trading/strategies/) — Straddle and surprise strategy details
- [Risk Management](https://chrisselig.github.io/forex_trading_bot/trading/risk-management/) — Rules, circuit breaker, position sizing
- [Installation](https://chrisselig.github.io/forex_trading_bot/getting-started/installation/) — Detailed setup guide
- [Auto-Start](https://chrisselig.github.io/forex_trading_bot/operations/auto-start/) — Unattended operation via cron + IBC
- [Telegram Notifications](https://chrisselig.github.io/forex_trading_bot/operations/telegram-notifications/) — Trade alert setup
- [Monte Carlo Analysis](https://chrisselig.github.io/forex_trading_bot/research/monte-carlo-1min/) — Parameter optimization results
- [Dukascopy Data](https://chrisselig.github.io/forex_trading_bot/research/dukascopy-data/) — Historical data source
- [Roadmap](https://chrisselig.github.io/forex_trading_bot/research/todo/) — What's planned next

---

## License

Private project. Not for redistribution.
