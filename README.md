# Forex Trading Bot

> **Disclaimer:** This software is provided for educational and informational purposes only and does not constitute financial advice, investment advice, or a recommendation to trade. Foreign exchange trading carries a high level of risk and may not be suitable for all investors. Past performance, including backtested or simulated results, is not indicative of future results. You could sustain a loss of some or all of your investment. Use this software entirely at your own risk. The author accepts no liability for any financial losses incurred through its use.

**[Documentation](https://chrisselig.github.io/forex_trading_bot/)** | [Glossary](https://chrisselig.github.io/forex_trading_bot/trading/glossary/) | [Strategies](https://chrisselig.github.io/forex_trading_bot/trading/strategies/) | [Risk Management](https://chrisselig.github.io/forex_trading_bot/trading/risk-management/) | [Monte Carlo Analysis](https://chrisselig.github.io/forex_trading_bot/research/04-monte-carlo-6yr/) | [Roadmap](https://chrisselig.github.io/forex_trading_bot/research/todo/)

An event-driven forex trading bot that automatically trades major economic news releases — [NFP](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#nfp-non-farm-payrolls), [CPI](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#cpi-consumer-price-index), [FOMC](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#fomc-federal-open-market-committee), [PPI](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#ppi-producer-price-index), GDP, PCE, Unemployment Claims, ISM Manufacturing PMI, Retail Sales, plus non-US events (SARB, TCMB, SA CPI, BOJ, RBA, AU CPI, AU Employment) — using [Interactive Brokers](https://www.interactivebrokers.com). The bot places [straddle](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#straddle) orders around news events, evaluates post-release surprises, and runs a weekly carry trade strategy exploiting interest rate differentials. It enforces strict risk management, sends real-time [Telegram alerts](https://chrisselig.github.io/forex_trading_bot/operations/telegram-notifications/) to your phone, and logs everything to a trade journal.

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
5. Schedule weekly carry trade rebalance (every Sunday, 5 AM MT)
6. Run health checks every 5 minutes (auto-reconnects on disconnect)
7. Refresh the calendar every 6 hours
8. Shut down gracefully on `Ctrl+C`

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
       ┌──────────────┐                    ┌──────────────┐
       │ Forex Factory│                    │   FRED API   │
       │   Calendar   │                    │ Interest Rates│
       └──────┬───────┘                    └──────┬───────┘
              │ scrape + filter                   │ fetch rates
       ┌──────▼───────┐                           │
       │  Event Store │ (SQLite)                  │
       └──────┬───────┘                           │
              │ schedule jobs                     │
       ┌──────▼───────────────────────────────────▼──┐
       │            APScheduler Orchestrator          │
       └──────┬──────────────┬──────────────┬────────┘
              │              │              │
   ┌──────────▼───────┐ ┌───▼──────────┐ ┌─▼──────────────┐
   │ Pre-Event (T-30m)│ │Post-Event    │ │ Monthly (1st)   │
   │  Straddle Strat  │ │ Surprise     │ │  Carry Strat    │
   └──────────┬───────┘ └───┬──────────┘ └─┬──────────────┘
              │              │              │
              └──────────────┼──────────────┘
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

1. **Calendar scraper** fetches high-impact events from Forex Factory + static calendar for non-US events
2. **Scheduler** sets up jobs: pre-event (T-30 min) and post-event (T+5 sec)
3. **Strategies** generate trading signals — see [Trading Strategies](https://chrisselig.github.io/forex_trading_bot/trading/strategies/)
4. **Risk manager** validates every signal against 5 rules + circuit breaker — no exceptions
5. **Execution engine** places orders on IB with bracket [stop-loss](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#sl-stop-loss)/[take-profit](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#tp-take-profit)
6. **Trade journal** logs every order, fill, and close to SQLite
7. **Telegram notifier** sends real-time alerts to your phone

---

## Active Trading Pairs

Based on Monte Carlo walk-forward analysis with 6.5 years of 1-minute Dukascopy data (819+ event/pair combos, Jan 2020 — Jun 2026). Only pairs that pass out-of-sample walk-forward validation are enabled.

**Active pairs** trade up to 9 US events (NFP, CPI, FOMC, PPI, GDP, PCE, Unemployment Claims, ISM Manufacturing PMI, Retail Sales) plus non-US domestic events:

| Pair | Events | E[P&L] | [Sharpe](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#sharpe-ratio) | Params | MC Report |
|------|--------|--------|--------|--------|-----------|
| **USDZAR** | US (6) + SARB + SA CPI | +17.1 pips | 6.40 | 50/70/10 | [6.5yr MC](https://chrisselig.github.io/forex_trading_bot/research/04-monte-carlo-6yr/) |
| **USDTRY** | US (9) + TCMB | +13.6 pips | 6.51 | 50/70/10 (TCMB: 20/60/10) | [6.5yr MC](https://chrisselig.github.io/forex_trading_bot/research/04-monte-carlo-6yr/) |
| **USDJPY** | BOJ only (paper-trade) | +3.4 pips | 2.45 | 25/15/15 | [Non-US](https://chrisselig.github.io/forex_trading_bot/research/06-non-us-events/) |
| **AUDUSD** | US + AU (paper-trade) | +12.5 pips | 3.93 | 40/70/30 | [AUDUSD + AU](https://chrisselig.github.io/forex_trading_bot/research/11-mc-audusd-australia/) |

**Disabled pairs** — failed walk-forward validation:

| Pair | E[P&L] | OOS | Why disabled |
|------|--------|-----|--------------|
| GBPUSD | +3.4 | -8.6 | Below breakeven, fails walk-forward |
| GBPJPY | +1.4 | fail | Marginal CI, walk-forward failure |
| USDCAD | +0.7 | -14.3 | Fails on both US and Canadian events |
| EURUSD | +0.4 | -2.0 | CI spans zero [-1.3, +2.1] |
| CADJPY/EURCAD/GBPCAD | — | fail | [All CAD pairs fail](https://chrisselig.github.io/forex_trading_bot/research/10-mc-cad-pairs/) |

Pairs are only enabled when analysis supports them. See [Analysis-Driven Configuration](https://chrisselig.github.io/forex_trading_bot/research/04-monte-carlo-6yr/#recommended-settings) for details.

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
| Max Spread | 15 [pips](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#pip-percentage-in-point) (per-pair: USDZAR=60, USDTRY=80, USDJPY=20) | Rejects trades during wide [spreads](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#spread) |

The [circuit breaker](https://chrisselig.github.io/forex_trading_bot/trading/glossary/#circuit-breaker) has three states: **ACTIVE → COOLDOWN → HALTED**. HALTED requires manual reset — the bot will not auto-resume. This is intentional.

See [Risk Management](https://chrisselig.github.io/forex_trading_bot/trading/risk-management/) for the full breakdown.

---

## Project Structure

```
forex_trading_bot/
├── config/
│   ├── settings.yaml          # Trading params, risk limits, IB config
│   ├── events.yaml            # Target events (9 US + 7 non-US)
│   └── static_events.yaml    # Non-US event calendar (SARB, TCMB, BOJ, SA CPI)
├── src/forex_bot/
│   ├── cli.py                 # Typer CLI (7 commands)
│   ├── config.py              # Pydantic settings loader
│   ├── models/                # Pydantic data models
│   ├── broker/                # IB connection, orders, pricing, contracts
│   ├── calendar/              # Forex Factory scraper, FRED client
│   ├── strategy/              # BaseStrategy, straddle, surprise, carry
│   ├── risk/                  # Risk rules, circuit breaker
│   ├── execution/             # Signal → order pipeline
│   ├── data/                  # SQLAlchemy schemas, trade journal
│   ├── notifications/         # Telegram trade alerts
│   ├── scheduler/             # APScheduler orchestrator
│   └── reporting/             # Performance stats, Rich dashboard
├── scripts/
│   ├── download_dukascopy.py         # Historical data from Dukascopy (1-min bars)
│   ├── monte_carlo_dukascopy.py      # MC optimization — US events (1-min)
│   ├── mc_non_us.py                  # MC optimization — non-US events
│   ├── mc_event_split.py             # MC optimization — per-event-type split
│   ├── monte_carlo_straddle.py       # MC optimization (1-hour, legacy)
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
- [Trading Strategies](https://chrisselig.github.io/forex_trading_bot/trading/strategies/) — Straddle, surprise, and carry trade strategy details
- [Risk Management](https://chrisselig.github.io/forex_trading_bot/trading/risk-management/) — Rules, circuit breaker, position sizing
- [Installation](https://chrisselig.github.io/forex_trading_bot/getting-started/installation/) — Detailed setup guide
- [Auto-Start](https://chrisselig.github.io/forex_trading_bot/operations/auto-start/) — Unattended operation via cron + IBC
- [Telegram Notifications](https://chrisselig.github.io/forex_trading_bot/operations/telegram-notifications/) — Trade alert setup
- [Monte Carlo Analysis](https://chrisselig.github.io/forex_trading_bot/research/04-monte-carlo-6yr/) — 6.5-year parameter optimization results
- [Non-US Events](https://chrisselig.github.io/forex_trading_bot/research/06-non-us-events/) — SARB, TCMB, BOJ, SA CPI analysis
- [PPI Analysis](https://chrisselig.github.io/forex_trading_bot/research/08-mc-ppi/) — PPI m/m MC validation
- [GDP & PCE Analysis](https://chrisselig.github.io/forex_trading_bot/research/09-mc-gdp-pce/) — GDP and PCE MC validation
- [CAD Pairs](https://chrisselig.github.io/forex_trading_bot/research/10-mc-cad-pairs/) — CADJPY, EURCAD, GBPCAD exploration (all fail)
- [AUDUSD + Australian Events](https://chrisselig.github.io/forex_trading_bot/research/11-mc-audusd-australia/) — AUDUSD MC analysis with AU events (paper-trade candidate)
- [Remaining US Events](https://chrisselig.github.io/forex_trading_bot/research/12-mc-remaining-us/) — UC, ISM PMI, Retail Sales analysis (USDTRY only)
- [Dukascopy Data](https://chrisselig.github.io/forex_trading_bot/research/dukascopy-data/) — Historical data source
- [Roadmap](https://chrisselig.github.io/forex_trading_bot/research/todo/) — What's planned next

---

## License

Private project. Not for redistribution.
