# Target Events

## Active US Events (MC-Validated)

These events are enabled in `config/events.yaml` and have passed Monte Carlo walk-forward validation:

| Event | Frequency | Pairs | MC Report |
|-------|-----------|-------|-----------|
| **Non-Farm Payrolls (NFP)** | Monthly (1st Friday, 8:30 AM ET) | USDZAR, USDTRY | [6.5yr MC](../research/04-monte-carlo-6yr.md) |
| **CPI m/m** | Monthly (mid-month, 8:30 AM ET) | USDZAR, USDTRY | [6.5yr MC](../research/04-monte-carlo-6yr.md) |
| **FOMC Rate Decision** | 8x/year (2:00 PM ET) | USDZAR, USDTRY | [6.5yr MC](../research/04-monte-carlo-6yr.md) |
| **PPI m/m** | Monthly (mid-month, 8:30 AM ET) | USDZAR, USDTRY | [PPI MC](../research/08-mc-ppi.md) |
| **GDP q/q** | ~12x/year (Advance/Prelim/Final, 8:30 AM ET) | USDZAR, USDTRY | [GDP & PCE MC](../research/09-mc-gdp-pce.md) |
| **Core PCE Price Index** | Monthly (end of month, 8:30 AM ET) | USDTRY only | [GDP & PCE MC](../research/09-mc-gdp-pce.md) |

## Active Non-US Events

| Event | Frequency | Pairs | MC Report |
|-------|-----------|-------|-----------|
| **SARB Rate Decision** | 6x/year (1:00 PM UTC) | USDZAR | [Non-US Events](../research/06-non-us-events.md) |
| **South Africa CPI y/y** | Monthly (8:00 AM UTC) | USDZAR | [Non-US Events](../research/06-non-us-events.md) |
| **TCMB Rate Decision** | 8-12x/year (11:00 AM UTC) | USDTRY | [Non-US Events](../research/06-non-us-events.md) |
| **BOJ Policy Rate** | 8x/year (~3:00 AM UTC) | USDJPY (paper-trade) | [Non-US Events](../research/06-non-us-events.md) |

## Disabled / Pending Validation

| Event | Status | Reason |
|-------|--------|--------|
| Unemployment Rate | Redundant | Same BLS release as NFP — straddle already triggers |
| PCE (USDZAR) | Failed | Walk-forward OOS = -0.7 ([report](../research/09-mc-gdp-pce.md)) |
| ISM Manufacturing PMI | Pending | Need to manually compile release dates (ISM, not on FRED) |
| Retail Sales m/m | Pending | Need correct Census Bureau release dates |
| Unemployment Claims | Pending | Need to compile ~300+ weekly dates from DOL |

Events are configured in `config/events.yaml` with aliases for matching Forex Factory titles and FRED series IDs for historical data. Non-US events use a static calendar (`config/static_events.yaml`) since Forex Factory only covers major economies.
