# Trading Strategies

The bot runs three strategies. The **straddle** captures volatility regardless of direction around news events. The **surprise** trades in the direction post-release data implies. The **carry trade** exploits interest rate differentials on a monthly schedule. Straddle and surprise are event-driven and operate independently during the same event. Carry runs on its own schedule with a separate risk budget.

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

## Strategy 3: Carry Trade (Schedule-Driven)

### Concept

The carry trade exploits interest rate differentials between currencies. Buy (go long) the high-yield currency, sell (go short) the low-yield currency, and collect the swap interest difference. Unlike straddle and surprise, carry is **not event-driven** — it rebalances on a fixed monthly schedule (1st of each month).

Positions are held for weeks or months, not minutes. There is no take profit — the goal is to earn interest over time. A wide 5% stop loss protects against adverse moves while giving positions room to breathe.

### How It Differs from Event Strategies

| | Straddle | Surprise | Carry |
|---|---------|---------|-------|
| **Trigger** | Economic event (T-30 min) | Post-event surprise | Monthly schedule (1st of month) |
| **Duration** | Minutes to hours | Minutes | Weeks to months |
| **Profit source** | Price volatility | Directional move | Interest rate differential |
| **Take profit** | Yes (30-70 pips) | Yes (25 pips) | None (hold for interest) |
| **Stop loss** | Tight (10-15 pips) | Tight (15 pips) | Wide (5% of entry price) |
| **Risk budget** | Per-trade (1%) | Per-trade (1%) | Separate budget (5% total) |

### Execution Flow

1. **Fetch FRED rates** — queries central bank policy rates from FRED API (with configurable fallbacks for currencies like TRY where FRED data is unavailable)
2. **Score by differential** — calculates `quote_rate - base_rate` for each configured pair, filters out pairs below the minimum differential threshold
3. **Close stale positions** — closes any existing carry positions that are no longer in the target set or whose direction has flipped
4. **Enter new positions** — opens new positions via the standard risk pipeline (Signal → RiskManager → CircuitBreaker → ExecutionEngine)
5. **Telegram summary** — sends a rebalance report showing targets, new entries, closes, and held positions

### Direction Logic

The direction depends on which currency in the pair has the higher interest rate:

- **Positive differential** (quote rate > base rate) → **SELL the pair** (short base, long quote — earn interest on the higher-yielding quote currency)
- **Negative differential** (quote rate < base rate) → **BUY the pair** (long base, short quote — earn interest on the higher-yielding base currency)

### Example

USD/ZAR with USD rate = 5.33%, ZAR rate = 8.25%:

- Differential = 8.25% - 5.33% = **+2.92%** (positive → quote rate higher)
- Direction: **SELL USDZAR** (short USD, long ZAR — earn ZAR interest)
- Stop loss: entry price + 5% of entry price
- Hold until next rebalance or direction flip

### The Risk

Carry trades are exposed to **emerging market currency crashes**. A year of accumulated swap interest can be wiped out in a single session if the high-yield currency collapses (e.g., 2008 crisis, 2024 JPY carry unwind). The 5% stop loss caps downside but can still be a significant loss on exotic pairs.

Additional risks:

- **FRED data staleness** — if rate data is >60 days old, the strategy falls back to configured rates which may not reflect recent policy changes
- **Gap risk** — EM currencies can gap through stop loss levels over weekends
- **Correlation** — multiple EM carry positions can all move against you simultaneously

### Parameters

| Setting | Default | Controls |
|---------|---------|----------|
| `carry.enabled` | `true` | Master toggle for the carry strategy |
| `carry.instruments` | USDZAR, USDTRY, USDMXN, AUDJPY, NZDJPY | Pairs evaluated for carry trades |
| `carry.min_differential_pct` | 2.0% | Minimum interest rate differential to open a position |
| `carry.risk_budget_pct` | 5.0% | Total portfolio % allocated to all carry positions |
| `carry.max_concurrent_carry` | 5 | Maximum carry positions held simultaneously |
| `carry.max_risk_per_carry_pct` | 1.5% | Maximum risk per individual carry position |
| `carry.stop_loss_pct` | 5.0% | Stop loss as percentage of entry price |
| `carry.rebalance_day` | 1 | Day of month to rebalance (1-31) |
| `carry.rebalance_hour_utc` | 11 | UTC hour for rebalance (5 AM MT) |
| `carry.max_spread_pips` | 30.0 | Default max spread at entry |
| `carry.fallback_rates` | TRY: 50.0 | Fallback rates when FRED data unavailable |

---

## How They Work Together
