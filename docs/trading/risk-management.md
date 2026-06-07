# Risk Management

## The Only Thing That Matters

Strategy gets the attention. Risk management determines survival.

Every fund that has blown up — Long-Term Capital Management, Amaranth Advisors, the countless retail accounts liquidated daily — failed not because their strategies were wrong but because their risk management allowed a single bad outcome to become fatal.

In news trading specifically, the risk is concentrated: you are deliberately trading the most volatile moments in the market. A single NFP release can move GBP/JPY 150 pips in seconds. If you are on the wrong side of that move without a stop loss, with too much leverage, with too large a position — the trade can destroy months of accumulated profit in one event.

The bot enforces five risk rules. None of them are optional. None of them can be bypassed. This is by design.

## The Rules

### 1. Mandatory Stop Loss

Every trade must have a stop loss. No exceptions.

The stop loss defines your maximum loss on the trade *before* you enter. Without it, your maximum loss is your entire account. This is not hypothetical — it happens to retail traders every month.

```
Signal → RiskManager.validate() → CircuitBreaker.check() → ExecutionEngine → IB
```

The stop loss is checked at two points in the pipeline. If it is missing at either checkpoint, the trade is rejected. There is no code path that places an order without a stop loss.

### 2. Max Risk Per Trade: 1%

No single trade can risk more than 1% of your account equity.

This means if your account is $100,000, the maximum loss on any individual trade is $1,000. The bot calculates position size based on:

- Account equity
- Stop loss distance (in pips)
- Pip value for the specific currency pair

The math:

```
Position size = (Account equity × 0.01) / (SL pips × pip value)
```

If the calculated position size exceeds the max risk, the position is scaled down. Never up.

**Why 1%?** Because it takes 10 consecutive losing trades to lose 10% of your account. With the bot's win rates (30-35% on straddles with 2:1 to 4:1 reward:risk), a 10-trade losing streak is statistically rare but not impossible. At 1% risk, you survive it. At 5% risk, you don't.

### 3. Max Daily Drawdown: 3%

If the account loses 3% of its starting equity in a single day, the bot stops trading for the rest of the day.

Some days the market is adversarial. Whipsaws, gap reversals, spread blowouts. Continuing to trade during these conditions compounds losses. The 3% daily limit is a hard stop.

When this triggers, the circuit breaker enters **HALTED** state. The bot does not auto-resume. You must manually review what happened and reset the circuit breaker. This forces human review after bad days — exactly when you need it.

### 4. Max Concurrent Positions: 3

The bot will not open more than 3 positions simultaneously.

Correlation is invisible until it isn't. If you have 5 positions that are all effectively "long USD," a single adverse move hits all of them. The position limit caps aggregate exposure.

### 5. Max Spread Check

Before placing any trade, the bot checks the current bid-ask spread. If it exceeds the configured maximum, the trade is rejected.

Wide spreads eat directly into your profit. A 15-pip spread on a trade with a 25-pip take profit means the market needs to move 40 pips in your favor to hit your target. The economics don't work.

Spread limits are wider for exotic pairs (USD/ZAR, USD/TRY) because their normal spreads are higher. But even for exotics, there is a point where the cost of entry makes the trade negative expected value.

## The Circuit Breaker

The circuit breaker is a state machine with three states:

```
ACTIVE  ──(5 consecutive losses)──▶  COOLDOWN  ──(30 min)──▶  ACTIVE
                                        │
ACTIVE  ──(daily drawdown > 3%)───▶  HALTED  ──(manual reset)──▶  ACTIVE
```

**ACTIVE**: Normal operation. All trades pass through.

**COOLDOWN**: Triggered by 5 consecutive losing trades. The bot pauses for 30 minutes, then auto-resumes. The logic: if you've lost 5 in a row, either the market conditions are wrong for your strategy or something unusual is happening. A brief pause prevents compounding losses during adversarial conditions.

**HALTED**: Triggered by exceeding the daily drawdown limit. The bot stops and **does not auto-resume**. This requires a human to look at the trades, understand what happened, and make a conscious decision to resume. Auto-resuming after hitting a drawdown limit is how accounts get wiped.

!!! danger "HALTED requires manual reset"
    The bot will never auto-reset from HALTED state. This is the most important safety mechanism in the system. If you find yourself wanting to auto-reset it, reconsider — the drawdown limit exists because the market told you something was wrong today.

## Position Sizing

The bot sizes every position to risk exactly 1% of account equity (or less). Here's a worked example:

**Given:**
- Account equity: $50,000
- Pair: GBP/USD
- Stop loss: 15 pips
- Pip value for GBP/USD: $10 per pip per standard lot (100,000 units)

**Calculation:**
```
Max dollar risk = $50,000 × 0.01 = $500
Position size = $500 / (15 pips × $10/pip) = 3.33 standard lots
→ Round down to 3 lots (never round up)
→ Actual risk = 3 lots × 15 pips × $10 = $450 (0.9% of equity)
```

The rounding-down is deliberate. Risk limits are ceilings, not targets.

## Why These Specific Numbers

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Risk per trade | 1% | Survives 10-trade losing streak with 90% of capital intact |
| Daily drawdown | 3% | Allows 3 full-risk losing trades before halting. Prevents tilt. |
| Concurrent positions | 3 | Limits correlation exposure without being too restrictive for multi-event days |
| Consecutive losses for cooldown | 5 | Statistically unlikely under normal conditions (< 5% probability with 35% win rate). Signals something is off. |
| Cooldown duration | 30 min | Long enough for conditions to change, short enough to catch the next event |

These numbers are conservative by design. The goal is not to maximize returns — it is to stay in the game long enough for the strategy's edge to compound. A 30% annual return with controlled drawdowns beats a 100% year followed by a blown account.
