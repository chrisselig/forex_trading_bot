# Operations

Running the bot day-to-day.

- [Auto-Start](auto-start.md) — Unattended startup via IBC and cron
- [Process Management](process-management.md) — Starting, stopping, and troubleshooting

## CLI Commands

```bash
forex-bot run              # Start autonomous trading
forex-bot status           # Show account summary and positions
forex-bot events           # Show upcoming high-impact USD events
forex-bot history          # Show recent trades
forex-bot performance      # Show P&L, win rate, Sharpe, per-strategy stats
forex-bot test-connection  # Verify IB Gateway connectivity
forex-bot backtest         # Run historical backtest
```

## Daily Workflow

### Automated (Recommended)

The cron job starts TWS and the bot at 5:00 AM MT (7:00 AM ET) on weekdays. No manual intervention needed for paper trading.

### Manual

1. Open TWS and log into your paper (or live) account
2. Ensure the API socket is enabled
3. Start the bot: `conda activate forex-bot && forex-bot run`
4. The bot auto-schedules jobs for upcoming events and handles reconnections
