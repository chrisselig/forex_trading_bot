# Currency Pairs

The bot trades pairs that react most to US economic data:

| Pair | Type | Why It's Included |
|------|------|-------------------|
| **GBP/USD** | Major | High liquidity. Strong NFP/FOMC reactions. Tight spreads. |
| **USD/CAD** | Major | Directly tied to US economy — shared border, trade dependency, energy correlation. |
| **GBP/JPY** | Cross | Known as "the beast" for its volatility. Amplifies global risk sentiment shifts triggered by US data. |
| **USD/ZAR** | Exotic | Extremely volatile on US news. South African Rand is a risk-off currency. |
| **USD/TRY** | Exotic | Highly sensitive to USD strength. Turkish Lira heavily influenced by US monetary policy. |

## Exotic Pair Considerations

USD/ZAR and USD/TRY offer larger moves but come with higher costs:

- **Wider spreads** — 10-50+ pips during events vs 0.3-3 pips for majors
- **Lower liquidity** — prices can gap without trading in between
- **Higher max spread setting** — the bot uses 15 pips (vs typical 3 for majors)
- **Amplified risk** — moves of 100+ pips on a single event are common

The Monte Carlo optimization uses pair-specific parameters to account for these differences. See the [optimization report](../research/01-straddle-hourly.md).
