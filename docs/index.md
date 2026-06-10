# Forex Trading Bot

An event-driven forex trading bot that trades major US economic news releases using Interactive Brokers.

!!! warning "Disclaimer"
    This software is provided for **educational and informational purposes only** and does not constitute financial advice, investment advice, or a recommendation to trade. Foreign exchange trading carries a high level of risk and may not be suitable for all investors. Past performance, including backtested or simulated results, is not indicative of future results. You could sustain a loss of some or all of your investment. Use this software entirely at your own risk. The author accepts no liability for any financial losses incurred through its use.

---

## What This Bot Does

The bot sleeps between events. When a scheduled release approaches — NFP, CPI, FOMC, GDP — it wakes up, executes pre-configured strategies, enforces strict risk management, and logs everything. Then it goes back to sleep.

It does not trade all day. It does not chase trends. It trades the most predictable moments in the forex market: the seconds around high-impact data releases.

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
     ┌────────▼──────────┐   ┌─────────▼─────────┐
     │ Pre-Event (T-30m)  │   │ Post-Event (T+5s)  │
     │   Straddle Strat   │   │  Surprise Strat    │
     └────────┬───────────┘   └─────────┬──────────┘
              │                         │
              └────────────┬────────────┘
                           │ Signal
                    ┌──────▼───────┐
                    │ Risk Manager │
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
                    │  TWS / IB    │
                    │  via ib_async│
                    └──────────────┘
```

## Quick Start

```bash
conda create -n forex-bot python=3.12 -y
conda activate forex-bot
pip install -e ".[dev]"
cp .env.example .env
# Edit .env with your IB credentials
forex-bot run
```

## Documentation

| Section | What You'll Learn |
|---------|-------------------|
| [Forex Trading](trading/index.md) | How forex markets work, why news moves prices, and how professionals manage risk |
| [Getting Started](getting-started/index.md) | Installation, IB setup, and configuration |
| [Trading Strategies](trading/strategies.md) | How the straddle and surprise strategies work |
| [Architecture](architecture/index.md) | System design and IB API integration |
| [Operations](operations/index.md) | Auto-start, process management, and daily operations |
| [Research](research/straddle-optimization.md) | Monte Carlo optimization results and methodology |
