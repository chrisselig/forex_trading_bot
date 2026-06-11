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

USD/ZAR is at 18.5000 before NFP:

| Order | Entry | Take Profit | Stop Loss |
|-------|-------|-------------|-----------|
| Buy stop | 18.5050 (+50 pips) | 18.5120 (+70 pips from entry) | 18.5040 (-10 pips from entry) |
| Sell stop | 18.4950 (-50 pips) | 18.4880 (-70 pips from entry) | 18.4960 (+10 pips from entry) |

If NFP is strong and USD/ZAR spikes to 18.5050, the buy stop triggers. Price continues to 18.5120 → take profit hit → +70 pips.

### Why It Works

- News releases reliably produce volatility — the event is scheduled, the move is not
- No directional bias needed — you profit from the *magnitude* of the move
- Default reward:risk ratio is 7:1 (70 pip TP vs 10 pip SL)
- Both straddle legs share an OCA (One-Cancels-All) group — IB automatically cancels the unfilled leg when one triggers

### The Risk: Whipsaw

If price spikes up (triggering the buy), then reverses sharply down, you get stopped out for -10 pips. With OCA groups, the other leg is cancelled automatically so double-loss is avoided.

The Monte Carlo optimization accounts for whipsaw events. See the [6.5-year optimization report](../research/04-monte-carlo-6yr.md) for the statistical analysis across 207+ events.

### Parameters

| Setting | Default | Controls |
|---------|---------|----------|
| `straddle_distance_pips` | 50 | How far from current price the orders are placed |
| `straddle_tp_pips` | 70 | Take profit distance |
| `straddle_sl_pips` | 10 | Stop loss distance |
| `pre_event_minutes` | 30 | How early before the event the orders are placed |

These defaults are from the [6.5-year Monte Carlo analysis](../research/04-monte-carlo-6yr.md). Per-pair and per-event overrides are supported — see `config/settings.yaml`. For example, TCMB events on USDTRY use 20/60/10 instead of the default 50/70/10.

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
