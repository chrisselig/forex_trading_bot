# Installation

## Prerequisites

### 1. Interactive Brokers Account

Sign up at [interactivebrokers.com](https://www.interactivebrokers.com). Select paper trading to start.

IBKR is IIROC registered and available in all Canadian provinces, including Alberta.

### 2. TWS or IB Gateway

Download [TWS](https://www.interactivebrokers.com/en/trading/tws.php) (full desktop) or [IB Gateway](https://www.interactivebrokers.com/en/trading/ibgateway-stable.php) (lightweight headless).

Configure the API socket in TWS:

1. **File > Global Configuration > API > Settings**
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

## Install the Bot

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

## Verify Installation

```bash
# Test IB connectivity
forex-bot test-connection

# Or use the standalone script
python scripts/check_ib_connection.py
```

This connects to IB Gateway, prints your account summary, and fetches one historical bar to verify everything works.
