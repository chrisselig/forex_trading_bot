# Auto-Start

The bot can start fully unattended via a cron job + IBC (IB Controller).

## How It Works

1. Cron fires `scripts/start_tws_and_bot.sh` at 5:00 AM MT (7:00 AM ET) on weekdays, and 3:00 PM MT (5:00 PM ET) on Sundays for Australian events
2. The script reads IB credentials from `.env`
3. Writes credentials to IBC's `config.ini`
4. Launches TWS via IBC with auto-login and dialog dismissal
5. Waits for the API socket to be ready (up to 3 minutes)
6. Waits 15 seconds for TWS to finish initialization
7. Starts the forex bot and verifies it launched successfully

## Usage

```bash
# Normal start (skips if already running)
~/00_data_projects/forex_trading_bot/scripts/start_tws_and_bot.sh

# Kill everything and start from scratch
~/00_data_projects/forex_trading_bot/scripts/start_tws_and_bot.sh --fresh

# Kill everything and exit
~/00_data_projects/forex_trading_bot/scripts/start_tws_and_bot.sh --stop
```

## 2FA

**Paper trading does not require 2FA.** The auto-start is fully unattended for paper accounts.

**Live trading will require 2FA** via the IBKR Mobile app. You'll need to approve a push notification on your phone within 3 minutes. IBC auto-retries if you miss it. See the [TODO](../research/todo.md#live-trading-readiness) for the 2FA testing checklist.

## Cron Setup

```bash
# Weekdays: 5:00 AM MT (7:00 AM ET) — before US events (earliest 8:15 AM ET)
0 5 * * 1-5 /home/doopdeep/00_data_projects/forex_trading_bot/scripts/start_tws_and_bot.sh >> ~/ibc/logs/cron.log 2>&1

# Sundays: 3:00 PM MT (5:00 PM ET) — forex market open, for Monday AEST AU events
# Australian events (RBA 14:30 AEST, AU CPI/Employment 11:30 AEST) releasing on
# Monday AEST fire Sunday 5:30-10:30 PM ET. The start script is idempotent.
0 15 * * 0 /home/doopdeep/00_data_projects/forex_trading_bot/scripts/start_tws_and_bot.sh >> ~/ibc/logs/cron.log 2>&1
```

## IBC Configuration

IBC (IB Controller) is installed at `~/ibc/` with:

- `config.ini` — auto-login settings, dialog handling, 2FA timeout behavior
- `twsstart.sh` — launch wrapper with TWS version, paths, trading mode

Key settings in `config.ini`:

| Setting | Value | Purpose |
|---------|-------|---------|
| `TradingMode` | paper | Paper or live account |
| `AcceptNonBrokerageAccountWarning` | yes | Auto-dismiss paper trading warning |
| `ExistingSessionDetectedAction` | primary | Take over existing sessions |
| `AcceptIncomingConnectionAction` | accept | Auto-accept API connections |
| `ReloginAfterSecondFactorAuthenticationTimeout` | yes | Retry 2FA on timeout |
