# Trading Strategies

The bot runs two complementary strategies. The straddle captures volatility regardless of direction. The surprise trades in the direction the data implies. They operate independently and can both be active during the same event.

## Strategy 1: Straddle (Pre-Event)

### Concept

Before a data release, the bot places two pending orders — a buy stop above and a sell stop below the current price. It does not predict direction. Whichever way the market breaks, one leg triggers with a bracket order (take profit + stop loss). The other leg should be cancelled.

### Execution Flow

1. **30 minutes before** the release, the bot checks the current price of each currency pair
2. Places a **buy stop** at `current price + straddle_distance_pips`
3. Places a **sell stop** at `current price - straddle_distance_pips`
4. Each order has a **take profit** and **stop loss** attached as a bracket
5. When data drops and price spikes, one order triggers
6. The other order stays unfilled

### Example

EUR/USD is at 1.0850 before NFP:

| Order | Entry | Take Profit | Stop Loss |
|-------|-------|-------------|-----------|
| Buy stop | 1.0870 (+20 pips) | 1.0900 (+30 pips from entry) | 1.0855 (-15 pips from entry) |
| Sell stop | 1.0830 (-20 pips) | 1.0800 (-30 pips from entry) | 1.0845 (+15 pips from entry) |

If NFP is strong and EUR/USD drops to 1.0830, the sell stop triggers. Price continues to 1.0800 → take profit hit → +30 pips.

### Why It Works

- News releases reliably produce volatility — the event is scheduled, the move is not
- No directional bias needed — you profit from the *magnitude* of the move
- Default reward:risk ratio is 2:1 (30 pip TP vs 15 pip SL)

### The Risk: Whipsaw

If price spikes up (triggering the buy), then reverses sharply down, you get stopped out on the buy *and* the sell stop triggers and also stops out. Double loss. This is the worst case and it does happen — particularly on mixed data (strong headline, weak details).

The Monte Carlo optimization accounts for this. See the [optimization report](../research/straddle-optimization.md) for the statistical analysis.

### Parameters

| Setting | Default | Controls |
|---------|---------|----------|
| `straddle_distance_pips` | 20 | How far from current price the orders are placed |
| `straddle_tp_pips` | 30 | Take profit distance |
| `straddle_sl_pips` | 15 | Stop loss distance |
| `pre_event_minutes` | 30 | How early before the event the orders are placed |

Per-pair overrides are supported — see `config/settings.yaml`.

---

## Strategy 2: Surprise (Post-Event)

### Concept

After the data is released, the bot compares the actual number to the forecast. If the surprise exceeds a threshold, it trades in the direction the surprise implies for the US dollar.

### Direction Logic

**Most indicators** (NFP, GDP, retail sales, ISM):

- Better than expected → strong economy → USD strengthens
- USD is base (USD/CAD): **BUY**
- USD is quote (GBP/USD): **SELL**

**Inverse indicators** (unemployment rate, jobless claims):

- Higher than expected → weak economy → USD weakens
- Direction flips vs normal indicators

### Example

NFP forecast: 200K. Actual: 250K. Surprise: +25%.

| Pair | USD Position | Direction | Reason |
|------|-------------|-----------|--------|
| GBP/USD | Quote | SELL | USD strength pushes pair down |
| USD/CAD | Base | BUY | USD strength pushes pair up |
| USD/ZAR | Base | BUY | USD strength pushes pair up |

### Parameters

| Setting | Default | Controls |
|---------|---------|----------|
| `surprise_threshold_pct` | 10.0% | Minimum surprise to trigger a trade |
| `surprise_entry_delay_seconds` | 5 | Wait time after release before entry |
| `surprise_tp_pips` | 25 | Take profit distance |
| `surprise_sl_pips` | 15 | Stop loss distance |

---

## How They Work Together

| | Straddle | Surprise |
|---|---------|---------|
| **Timing** | Before the event | After the event |
| **Approach** | Bet on volatility (either direction) | Bet on direction (based on data) |
| **Trigger** | Price movement | Data surprise magnitude |
| **Order type** | Pending stop orders | Market orders |

During a single event:

1. **T-30 min** — Straddle places buy stop + sell stop
2. **T+0** — Data releases, price moves, one straddle leg triggers
3. **T+5 sec** — Surprise strategy evaluates data, may place additional trade

Both strategies operate independently and can produce signals on the same event.
