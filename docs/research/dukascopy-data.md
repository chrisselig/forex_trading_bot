# Dukascopy Historical Data

## Overview

[Dukascopy Bank SA](https://www.dukascopy.com) provides free historical forex data at tick, second, and minute granularity. This is a major upgrade from the IB paper account, which only provides 1-hour bars for forex pairs.

## Why Dukascopy?

| Source | Granularity | Exotic Pairs | Account Required | History Depth |
|--------|-------------|--------------|------------------|---------------|
| **Dukascopy** | Tick to monthly | USDZAR, USDTRY, GBPJPY | No | 10+ years |
| IB Paper | 1-hour only | Yes | Yes | Limited |
| Histdata.com | Tick, 1-min | Majors only | No | 2000+ |
| Yahoo Finance | 1-min (7 days) | Yes | No | Very limited |
| FXCM | 1-min | Limited exotics | Demo account | ~10 years |

Dukascopy is the best free source that covers all 5 of our pairs — including the exotics (USDZAR, USDTRY) — at 1-minute resolution.

## Download Script

The download script lives at `scripts/download_dukascopy.py` and uses the [`dukascopy-python`](https://pypi.org/project/dukascopy-python/) library.

### What It Downloads

- **Pairs**: GBPUSD, USDCAD, GBPJPY, USDZAR, USDTRY
- **Timeframes**: 1-minute and 5-minute OHLCV bars
- **Window**: 2 hours before to 4 hours after each event
- **Events**: NFP (18), CPI (17), FOMC (12) — Jan 2025 through Jun 2026
- **Output**: Per-pair CSV files in `scripts/data/dukascopy/`

### Usage

```bash
# Full download (all 5 pairs, both 1min and 5min)
~/anaconda3/envs/forex-bot/bin/python scripts/download_dukascopy.py --timeframe both

# Single pair
~/anaconda3/envs/forex-bot/bin/python scripts/download_dukascopy.py --pair GBPUSD --timeframe 1min

# Resume interrupted download
~/anaconda3/envs/forex-bot/bin/python scripts/download_dukascopy.py --skip-existing

# Custom window (e.g., 1h before, 2h after)
~/anaconda3/envs/forex-bot/bin/python scripts/download_dukascopy.py --pre-hours 1 --post-hours 2
```

### Output Files

```
scripts/data/dukascopy/
  GBPUSD_1min.csv    GBPUSD_5min.csv
  USDCAD_1min.csv    USDCAD_5min.csv
  GBPJPY_1min.csv    GBPJPY_5min.csv
  USDZAR_1min.csv    USDZAR_5min.csv
  USDTRY_1min.csv    USDTRY_5min.csv
```

Each CSV contains columns: `open`, `high`, `low`, `close`, `volume`, `pair`, `event_name`, `event_date`, `event_utc`. The index is a UTC timestamp.

### Data Volume

Per pair at 1-min resolution: ~14,000 rows (~1.5 MB) covering 46 past events with 360 bars each (6-hour window).

## Impact on Monte Carlo Optimization

The original Monte Carlo straddle optimization (`scripts/monte_carlo_straddle.py`) used 1-hour bars from IB. This had a significant limitation:

!!! warning "Hourly bar limitation"
    When both TP and SL could be hit within the same 1-hour bar, the simulation had to assume SL was hit first (pessimistic). This biased results downward and made it impossible to accurately model fast news spikes.

With 1-minute data from Dukascopy, we can:

1. **Observe intra-bar price paths** — know the actual sequence of price movements after news
2. **Accurately determine TP vs SL** — no more guessing which was hit first
3. **Model realistic fill timing** — see exactly when straddle triggers fire
4. **Detect whipsaw patterns** — identify events where price reverses within minutes

The next step is to re-run the Monte Carlo optimization with 1-min bars to get more accurate parameter estimates.

## Dukascopy Data Notes

- Data is bid-side OHLCV (no ask bars downloaded — spread must still be estimated)
- Timestamps are UTC
- Weekend gaps are expected (no data from Friday ~5 PM ET to Sunday ~5 PM ET)
- Some bars may be missing during low-liquidity hours for exotic pairs
- The `--skip-existing` flag prevents re-downloading already-fetched events
