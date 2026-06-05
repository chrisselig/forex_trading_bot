# Trading Strategies Guide

This document explains the two trading strategies used by the bot, written for someone new to forex or algorithmic trading.

---

## The Core Idea

The bot only trades during **major US economic data releases** — events like the jobs report (NFP), inflation numbers (CPI), or interest rate decisions (FOMC). These events cause sudden, sharp price moves in currency pairs because they change how traders view the US economy.

The bot does **not** trade all day. It sleeps, wakes up minutes before a scheduled release, places trades, manages them, and goes back to sleep.

---

## Strategy 1: Straddle (Pre-Event)

### What it does

Before a data release, the bot places **two pending orders** — one above the current price and one below it. It doesn't know which direction the market will move, so it prepares for both.

### How it works (step by step)

1. **30 minutes before** the release, the bot checks the current price of each currency pair
2. It places a **buy stop order** 20 pips *above* the current price
3. It places a **sell stop order** 20 pips *below* the current price
4. Each order has a **take profit** (30 pips) and **stop loss** (15 pips) attached
5. When the data drops and the price spikes in one direction, that order gets triggered
6. The other order stays unfilled (and should be cancelled)

### Example

Say EUR/USD is at 1.0850 before NFP:
- **Buy stop** placed at 1.0870 (20 pips above)
  - Take profit: 1.0900 (30 pips above entry)
  - Stop loss: 1.0855 (15 pips below entry)
- **Sell stop** placed at 1.0830 (20 pips below)
  - Take profit: 1.0800 (30 pips below entry)
  - Stop loss: 1.0845 (15 pips above entry)

If NFP comes in strong and EUR/USD drops to 1.0830, the sell stop triggers. If the price keeps falling to 1.0800, the take profit closes the trade for +30 pips profit. If the price reverses and rises to 1.0845, the stop loss closes the trade for -15 pips loss.

### Why this works

- News releases cause **volatility** — prices move fast and far
- You don't need to predict the direction — you profit from the *size* of the move
- The reward-to-risk ratio is 2:1 (30 pip target vs 15 pip stop)

### Pros

- **No directional bias needed** — works regardless of whether the data is good or bad
- **Defined risk** — you know your maximum loss before the trade is placed
- **Automatic execution** — the bot handles everything; no manual clicking during fast markets
- **Good for volatile events** — the bigger the move, the more likely one leg hits its target

### Cons

- **Whipsaw risk** — if the price spikes up (triggering the buy), then reverses down, you can get stopped out on both legs for a double loss
- **Spread widening** — during news events, the bid/ask spread can widen dramatically, which may trigger your orders at worse prices (slippage)
- **Low-volatility events** — if the data comes in exactly as expected, the price may not move enough to trigger either order
- **Cost of the straddle** — if both legs trigger and stop out, you lose on both sides

### Key settings

| Setting | Default | What it controls |
|---------|---------|-----------------|
| `straddle_distance_pips` | 20 | How far from current price the orders are placed |
| `straddle_tp_pips` | 30 | Take profit distance |
| `straddle_sl_pips` | 15 | Stop loss distance |
| `pre_event_minutes` | 30 | How early before the event the orders are placed |

---

## Strategy 2: Surprise (Post-Event)

### What it does

After the data is released, the bot compares the **actual number** to what analysts **expected** (the forecast). If the difference is big enough (a "surprise"), the bot trades in the direction the surprise implies.

### How it works (step by step)

1. **5 seconds after** the release, the bot checks the actual value vs the forecast
2. It calculates the **surprise percentage**: `(actual - forecast) / forecast * 100`
3. If the surprise exceeds **10%**, the bot places a trade
4. It figures out the correct direction based on:
   - What the indicator means for the US dollar
   - Whether USD is the base or quote currency in the pair
5. The trade gets a **take profit** (25 pips) and **stop loss** (15 pips)

### Understanding the direction logic

**Most indicators** (NFP, GDP, retail sales, ISM):
- Better than expected = strong economy = **USD gets stronger**
- USD stronger = **BUY** pairs where USD is first (USD/CAD, USD/ZAR)
- USD stronger = **SELL** pairs where USD is second (GBP/USD)

**Unemployment-type indicators** (unemployment rate, jobless claims):
- These work in **reverse** — higher unemployment is *bad* for USD
- Higher than expected unemployment = **USD gets weaker**
- So the direction flips compared to other indicators

### Example

NFP forecast: 200K jobs. Actual: 250K jobs.
- Surprise: +25% (well above the 10% threshold)
- Positive surprise on NFP = USD strength
- For GBP/USD (USD is quote): **SELL** (USD up = pair down)
- For USD/CAD (USD is base): **BUY** (USD up = pair up)
- For USD/ZAR (USD is base): **BUY** (USD up = pair up)

Unemployment forecast: 4.0%. Actual: 4.5%.
- Surprise: +12.5% (above threshold)
- But unemployment is an **inverse indicator** — higher is bad for USD
- So this is actually USD negative
- For GBP/USD: **BUY** (USD down = pair up)
- For USD/CAD: **SELL** (USD down = pair down)

### Why this works

- Markets react to **surprises**, not to the data itself
- A number that matches the forecast is already "priced in" — no reaction
- The bigger the surprise, the bigger and more sustained the price move
- The 5-second delay lets the initial spike settle slightly, reducing the chance of entering at the absolute worst price

### Pros

- **Trades with the fundamentals** — you're betting on the logical market reaction to new information
- **High-probability when it triggers** — large surprises tend to produce follow-through moves
- **Filters out noise** — the 10% threshold means you only trade when the data is genuinely unexpected
- **Clear logic** — the reason for every trade is logged (e.g., "Surprise +25.0% on NFP -> SELL GBPUSD")

### Cons

- **Data availability** — the bot needs the actual value quickly after release; delays can mean a worse entry price
- **Already priced in** — by the time the bot enters (T+5 sec), fast institutional traders may have already moved the market
- **Reversals** — sometimes the initial reaction reverses as traders digest the full report (e.g., strong headline NFP but weak wage growth)
- **Threshold sensitivity** — a 9.9% surprise doesn't trade but a 10.1% surprise does, which is somewhat arbitrary
- **Doesn't account for context** — a +25% NFP surprise might not matter if the Fed already signaled they won't change policy

### Key settings

| Setting | Default | What it controls |
|---------|---------|-----------------|
| `surprise_threshold_pct` | 10.0% | Minimum surprise magnitude to trigger a trade |
| `surprise_entry_delay_seconds` | 5 | Wait time after release before entering |
| `surprise_tp_pips` | 25 | Take profit distance |
| `surprise_sl_pips` | 15 | Stop loss distance |

---

## How the Two Strategies Work Together

The straddle and surprise strategies are **complementary**:

| | Straddle | Surprise |
|---|---------|---------|
| **When** | Before the event | After the event |
| **Approach** | Bet on volatility (either direction) | Bet on direction (based on data) |
| **Trigger** | Price movement | Data surprise magnitude |
| **Order type** | Pending stop orders | Market orders |

In practice during a single event:
1. **T-30 min**: Straddle places buy stop + sell stop
2. **T+0**: Data is released, price moves, one straddle leg triggers
3. **T+5 sec**: Surprise strategy evaluates the data and may place an additional trade

Both strategies can be active at the same time. They operate independently.

---

## Target Events

The bot watches these US economic releases:

| Event | Frequency | Why it matters |
|-------|-----------|---------------|
| **Non-Farm Payrolls (NFP)** | Monthly (1st Friday) | The single most market-moving data release. Shows how many jobs the US economy added. |
| **Unemployment Rate** | Monthly (with NFP) | What percentage of people who want jobs can't find them. |
| **CPI (Inflation)** | Monthly | Measures how fast prices are rising. Directly affects interest rate expectations. |
| **FOMC / Fed Rate Decision** | 8x per year | The Federal Reserve's interest rate decision. Moves every market globally. |
| **GDP** | Quarterly | The broadest measure of economic growth. |
| **ISM Manufacturing PMI** | Monthly | Survey of factory activity. Above 50 = expansion, below 50 = contraction. |
| **Retail Sales** | Monthly | How much consumers are spending. Consumer spending is ~70% of US GDP. |
| **PPI (Producer Prices)** | Monthly | Inflation at the wholesale level. Leading indicator for CPI. |
| **Jobless Claims** | Weekly | How many people filed for unemployment for the first time. |

---

## Currency Pairs Traded

The bot focuses on pairs that react most to US economic data:

| Pair | Type | Why it's included |
|------|------|-------------------|
| **USD/ZAR** | Exotic | Extremely volatile on US news. The South African Rand is a "risk-off" currency — it moves dramatically when US data shifts global risk sentiment. Spreads are wider. |
| **USD/TRY** | Exotic | Very sensitive to USD strength. The Turkish Lira is heavily influenced by US monetary policy and dollar demand. High volatility, wider spreads. |
| **GBP/JPY** | Cross | Highly sensitive to global risk sentiment triggered by US data. Known as "the beast" for its volatility. Moves fast on NFP and FOMC. |
| **GBP/USD** | Major | One of the most liquid pairs. Frequently experiences high volatility during NFP and FOMC. Tighter spreads. |
| **USD/CAD** | Major | Directly affected by US economic data, especially energy and employment numbers. Canada's economy is closely tied to the US. |

### Important notes on exotic pairs

- **USD/ZAR and USD/TRY have wider spreads** (the gap between the buy and sell price). This costs more to enter and exit trades
- **Wider spreads mean the max spread setting is higher** (15 pips vs the typical 3 pips for majors)
- **Exotics can move hundreds of pips** on a single news event — both opportunity and risk are amplified
- **Liquidity is lower** — during off-hours or extreme events, prices can "gap" (jump without trading in between)

---

## Risk Management (Why Every Trade Has a Stop Loss)

Every single trade placed by this bot **must** have a stop loss. This is enforced at two levels:

1. **RiskManager** — checks every signal before it becomes an order. If there's no stop loss, the signal is rejected.
2. **ExecutionEngine** — checks again right before sending to the broker. If somehow a signal got through without a stop loss, it's blocked here.

This is non-negotiable. No stop loss = no trade. The reason is simple: **a single runaway loss can wipe out months of gains**. In fast-moving news events, prices can move against you by 100+ pips in seconds. Without a stop loss, there is no limit to how much you can lose on a single trade.

### Other risk rules

| Rule | Purpose |
|------|---------|
| **Max 1% risk per trade** | No single trade can risk more than 1% of your account balance |
| **Max 3% daily drawdown** | If you lose 3% in a day, the bot stops trading until tomorrow |
| **Max 3 concurrent positions** | Limits exposure — you can't have unlimited open trades |
| **Circuit breaker** | 5 consecutive losses = 30 min cooldown. Daily drawdown exceeded = **full halt** (manual reset required) |

---

## Glossary

| Term | Meaning |
|------|---------|
| **Pip** | The smallest standard price move in forex. For most pairs, it's 0.0001 (e.g., EUR/USD moving from 1.0850 to 1.0851 = 1 pip). For JPY pairs, it's 0.01. |
| **Stop loss (SL)** | An order that automatically closes your trade if the price moves against you by a set amount. Limits your loss. |
| **Take profit (TP)** | An order that automatically closes your trade when it reaches a target profit. Locks in gains. |
| **Spread** | The difference between the buy price (ask) and sell price (bid). This is a cost — the wider the spread, the more the price needs to move in your favor before you're profitable. |
| **Slippage** | When your order fills at a different price than expected. Common during fast-moving news events. |
| **Bracket order** | A group of orders: an entry order + a take profit + a stop loss, all linked together. When the entry fills, the TP and SL become active. |
| **Straddle** | Placing orders on both sides of the current price to capture a move in either direction. |
| **Surprise** | The difference between what analysts expected (forecast) and what actually happened (actual). A big surprise = a big market reaction. |
| **Whipsaw** | When the price moves sharply in one direction, triggers your order, then immediately reverses. You get stopped out even though the eventual move was in your favor. |
| **Forecast** | The consensus estimate from economists about what a data release will show. Published before the event. |
| **Actual** | The real number reported when the data is released. |
| **Base currency** | The first currency in a pair. In USD/CAD, USD is the base. |
| **Quote currency** | The second currency in a pair. In USD/CAD, CAD is the quote. |
| **Exotic pair** | A currency pair involving a major currency and a developing country's currency (e.g., USD/ZAR). Higher volatility and wider spreads than major pairs. |
