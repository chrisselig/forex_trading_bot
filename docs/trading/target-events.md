# Target Events

The bot watches these US economic releases:

| Event | Frequency | Why It Matters |
|-------|-----------|---------------|
| **Non-Farm Payrolls (NFP)** | Monthly (1st Friday) | The single most market-moving release. Net job creation. |
| **Unemployment Rate** | Monthly (with NFP) | Inverse indicator — higher is bad for USD. |
| **CPI (Inflation)** | Monthly | Primary inflation gauge. Directly affects rate expectations. |
| **FOMC Rate Decision** | 8x per year | The Fed's interest rate decision and forward guidance. |
| **GDP** | Quarterly | Broadest measure of economic growth. |
| **ISM Manufacturing PMI** | Monthly | Leading indicator. The 50 level creates binary reactions. |
| **Retail Sales** | Monthly | Consumer spending proxy (~70% of US GDP). |
| **PPI (Producer Prices)** | Monthly | Wholesale inflation. Leading indicator for CPI. |
| **Jobless Claims** | Weekly | High frequency, lower per-release impact. |

Events are configured in `config/events.yaml` with aliases for matching Forex Factory titles and FRED series IDs for historical data.
