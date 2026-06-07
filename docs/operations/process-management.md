# Process Management

## When to Kill Processes

- Before running the startup script if an old bot or TWS instance is stuck
- When the bot is unresponsive
- When you want to restart with new configuration

## How to Kill Processes

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

Or use the startup script:

```bash
# Kill everything cleanly
./scripts/start_tws_and_bot.sh --stop

# Kill everything and restart
./scripts/start_tws_and_bot.sh --fresh
```

## Process Lifecycle

| Process | What It Is | Notes |
|---------|-----------|-------|
| `forex-bot run` | The Python trading bot | Handles SIGTERM gracefully, but sometimes needs `kill -9` |
| `java.*jts` | TWS Java process launched by IBC | Kill this to fully stop TWS |
| `ibcstart` | IBC launcher | Usually exits after TWS starts |

The startup script checks for existing processes and skips launch if they're already running. Use `--fresh` if you want a clean restart.

## Resetting the Paper Account

To clear all positions and reset the paper account balance:

1. Go to the [IB Client Portal](https://www.interactivebrokers.com/portal)
2. Log in > **Settings > Account Settings > Paper Trading Account > Reset**
3. The reset takes a few minutes to process
