# Configuration

## .env

Environment variables for secrets and connection parameters. Never committed to git.

```bash
FRED_API_KEY=your_key_here   # Free from fred.stlouisfed.org
IB_HOST=127.0.0.1
IB_PORT=7497                 # 7497=TWS paper, 7496=TWS live, 4002=Gateway paper
IB_CLIENT_ID=1

# IB Login Credentials (used by IBC auto-start)
IB_USERNAME=your_ib_username
IB_PASSWORD=your_ib_password
```

## config/settings.yaml

All trading parameters, risk limits, and strategy settings.

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
  max_spread_pips: 15.0

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

## config/events.yaml

Defines which economic events to trade. Each event has a name, aliases (for matching Forex Factory titles), FRED series ID, and affected currency pairs.

Pre-configured events: NFP, CPI, FOMC, GDP, Jobless Claims, ISM Manufacturing, PPI, Retail Sales, Unemployment Rate.

## Configuration Precedence

1. `.env` variables override `settings.yaml` values
2. `settings.yaml` is the source of truth for all tunables
3. Secrets always go in `.env`, never in YAML

## Timezone Strategy

| Context | Timezone |
|---------|----------|
| Internal storage | UTC (always) |
| Database | UTC |
| APScheduler | UTC |
| Forex Factory source | Eastern Time |
| IB timestamps | Normalized to UTC on ingestion |
| User display | Eastern Time (industry standard) |
