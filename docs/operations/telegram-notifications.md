# Telegram Notifications

Real-time trade alerts sent to your phone via Telegram Bot API.

## Setup

### 1. Create a Telegram Bot

1. Open Telegram and message **@BotFather**
2. Send `/newbot`
3. Choose a name (e.g. "Forex Trading Bot") and username (e.g. `your_forex_bot`)
4. Copy the **bot token** (format: `1234567890:AAH1bGci...`)

### 2. Get Your Chat ID

1. Open your new bot in Telegram and send it a message (e.g. "hi")
2. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser
3. Find `"chat": {"id": 123456789}` in the response — that number is your chat ID

### 3. Configure

Add to your `.env`:

```bash
TELEGRAM_BOT_TOKEN=1234567890:AAH1bGciOiJSUzI1NiIs...
TELEGRAM_CHAT_ID=123456789
```

The bot picks these up automatically on startup. No restart required if you add them before the first run.

## Alert Types

| Alert | Trigger | Key Info | Sound |
|-------|---------|----------|-------|
| **Trade Opened** | Order placed with IB | Pair, side, entry/SL/TP, R:R ratio, position size, spread, event context, account NLV | Yes |
| **Order Filled** | IB confirms fill | Pair, fill price, size, IB order ID | Yes |
| **Trade Closed** | Position exits | Entry/exit prices, P&L ($ and pips), exit reason (TP/SL/timeout), duration, event data + surprise %, daily P&L | Yes |
| **Signal Rejected** | Risk manager blocks a trade | Pair, strategy, list of violations, event context | Yes |
| **Circuit Breaker** | COOLDOWN or HALTED state | Reason, action required (manual reset for HALTED) | Yes |
| **Connection Lost** | IB Gateway disconnects | Reconnection in progress | Yes |
| **Connection Restored** | IB reconnects after drop | — | Silent |
| **Pre-flight Failed** | Can't reach IB before event | Event name, scheduled time, warning | Yes |
| **Event Upcoming** | Pre-event handler fires | Event name, forecast/previous, scheduled time | Silent |
| **Bot Started** | Bot process starts | Account ID, NLV, buying power | Yes |
| **Bot Stopped** | Graceful shutdown | Reason | Yes |

## Example Messages

### Trade Opened
```
NEW TRADE OPENED

GBPUSD LONG (STOP)
Strategy: straddle

Entry: 1.35260
Stop Loss: 1.35160 (10.0 pips)
Take Profit: 1.35660 (40.0 pips)
R:R: 4.0:1
Size: 20,000 units
Spread: 1.8 pips

Event: Nonfarm Payrolls
Scheduled: Jun 06 08:30:00 AM ET
Forecast: 180K  Prev: 177K

Account NLV: $87.43

Jun 06 08:00:00 AM ET
```

### Trade Closed
```
TRADE CLOSED — WIN

GBPUSD LONG
Strategy: straddle

Entry: 1.35260
Exit: 1.35660
Closed by: Take Profit
Duration: 12m

P&L: +$32.00 (+40.0 pips)

Event: Nonfarm Payrolls
Actual: 272K  Forecast: 180K  Prev: 177K
Surprise: +51.1%

Account NLV: $119.43
Daily P&L: +$32.00

Jun 06 08:12:00 AM ET
```

## Architecture

The `TelegramNotifier` class is in `src/forex_bot/notifications/telegram.py`. It is:

- **Fire-and-forget** — notification failures are logged but never crash the bot
- **Async** — uses `httpx` async HTTP client, no blocking
- **Optional** — if `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` are empty, notifications are silently disabled
- **Wired into the full pipeline** — orchestrator, execution engine, position monitor, trade journal, circuit breaker, and scheduler jobs all have access

All times are displayed in **Eastern Time** (industry standard for US economic releases).

## Disabling

To disable notifications without removing your credentials, you could set the enabled flag in `config/settings.yaml`:

```yaml
telegram:
  enabled: false
```

Or simply leave `TELEGRAM_BOT_TOKEN` empty in `.env`.
