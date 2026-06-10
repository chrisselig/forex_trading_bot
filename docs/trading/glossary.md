# Glossary

A plain-language reference for every term, abbreviation, and metric used in this project. If you can read this page, you can read any report or config file in the bot.

---

## Core Forex Concepts

### Pip (Percentage in Point)

The smallest standard unit of price movement in a currency pair. For most pairs (e.g., GBPUSD), 1 pip = 0.0001. For JPY pairs (e.g., GBPJPY), 1 pip = 0.01.

**Example**: If GBPUSD moves from 1.2700 to 1.2715, that's a 15-pip move.

### Spread

The difference between the **bid** (what you can sell at) and the **ask** (what you can buy at). This is the broker's fee baked into every trade. Spreads widen during news events — a pair that normally has a 1-pip spread might jump to 10+ pips during NFP.

**Example**: Bid 1.2700 / Ask 1.2703 = 3-pip spread.

### Lot Size

The quantity of currency you're trading. A **standard lot** = 100,000 units of the base currency. A **mini lot** = 10,000. A **micro lot** = 1,000. At a standard lot, 1 pip ≈ $10 USD for most pairs.

### Leverage

Borrowed capital from the broker that lets you control a larger position than your account balance. 30:1 leverage means $1,000 of your money controls $30,000 of currency. Amplifies both gains and losses. IIROC (Canadian regulator) caps retail forex leverage — IB enforces this automatically.

### Base Currency vs Quote Currency

In GBPUSD, GBP is the **base** and USD is the **quote**. The price tells you how much quote currency you need to buy one unit of base. "Buying GBPUSD" means buying GBP and selling USD.

### Major vs Exotic Pairs

- **Majors**: Pairs involving USD and another G7 currency (GBPUSD, USDCAD, USDJPY, EURUSD). Tight spreads, deep liquidity.
- **Exotics**: Pairs involving an emerging market currency (USDZAR, USDTRY). Wider spreads, more volatile, can offer larger moves.

---

## Strategy Terms

### Straddle

Placing two pending orders on opposite sides of the current price before a news event — a **buy stop** above and a **sell stop** below. Whichever direction the market moves, one order triggers. The other is cancelled. This lets you trade the volatility without predicting the direction.

### Distance (Distance Pips)

How far above/below the current price the straddle orders are placed, in pips. A 35-pip distance means the buy stop is 35 pips above the current price and the sell stop is 35 pips below. Wider distance = more selective (fewer triggers), narrower = more triggers but more noise.

### TP (Take Profit)

A limit order that automatically closes your position at a target profit level. TP = 15 means the trade closes when it's 15 pips in profit.

### SL (Stop Loss)

A stop order that automatically closes your position to limit losses. SL = 10 means the trade closes if it moves 10 pips against you. Every trade in this bot **must** have a stop loss — this is a non-negotiable risk rule.

### R:R (Reward-to-Risk Ratio)

The ratio of your take profit to your stop loss. TP=70 / SL=10 = 7:1 R:R. A 7:1 trade only needs to win 12.5% of the time to break even. A 1:1 trade (TP=15 / SL=15) needs 50%.

### Breakeven Win Rate

The minimum win rate needed to avoid losing money, given the R:R ratio. Formula: `SL / (TP + SL)`. A strategy is profitable when the actual win rate exceeds the breakeven rate.

### OCA (One-Cancels-All)

An order group where filling one order automatically cancels the others. In IB's API, you assign the same `ocaGroup` string to multiple orders and set `ocaType=1` (cancel on fill).

**Why it matters for straddles**: Without OCA, both the buy stop and sell stop are independent — if the market whipsaws through both levels, you end up with two opposing positions (a hedged mess). With OCA, as soon as one leg fills, IB automatically cancels the other. This ensures you only ever take one directional trade per event.

**How it works in the bot**: The `StraddleStrategy` generates a unique OCA group ID (e.g., `straddle_USDZAR_20260605_1230_48291`) and assigns it to both the BUY and SELL stop signals. When these become bracket orders in IB, the parent entry orders share the OCA group. When one entry fills, IB cancels the other entry — and since TP/SL are children of the cancelled entry, they're cancelled too.

---

## Economic Events

### NFP (Non-Farm Payrolls)

The US jobs report, released on the first Friday of each month at 8:30 AM ET by the Bureau of Labor Statistics. Reports the number of jobs added/lost (excluding farms). The single most market-moving scheduled release in forex.

### CPI (Consumer Price Index)

The US inflation report, released mid-month at 8:30 AM ET. Measures the change in prices paid by consumers. Drives expectations for Fed interest rate decisions.

### FOMC (Federal Open Market Committee)

The branch of the Federal Reserve that sets US interest rate policy. Rate decisions are announced at 2:00 PM ET, 8 times per year. These are the "big three" events this bot trades.

### Surprise

The difference between the actual released number and the consensus forecast. A large surprise (e.g., NFP comes in at +300K vs forecast of +180K) typically causes the biggest price moves.

---

## Statistical & Monte Carlo Terms

### E[P&L] (Expected Profit & Loss)

The average profit or loss per trade, in pips. Calculated across all simulated or historical trades. Positive = profitable on average.

### Win Rate

The percentage of trades that hit take profit (winners) out of all triggered trades. A 30% win rate with a 7:1 R:R is highly profitable. Win rate alone means nothing without knowing the R:R.

### 95% CI (95% Confidence Interval)

A range that, with 95% probability, contains the true average P&L. Calculated via bootstrap resampling (10,000 random samples with replacement). **If the CI excludes zero** (e.g., [+10.0, +45.9]), we have strong statistical evidence the strategy is profitable. If it spans zero (e.g., [-2.9, +4.9]), we can't be confident.

### Sharpe Ratio

A measure of risk-adjusted return: `mean P&L / standard deviation of P&L`. Higher = better. Rules of thumb:

| Sharpe | Interpretation |
|--------|---------------|
| < 0.5 | Poor — returns don't justify the risk |
| 0.5–1.0 | Acceptable |
| 1.0–2.0 | Good |
| > 2.0 | Excellent |

### Profit Factor

Gross profits divided by gross losses. A profit factor of 3.0 means the strategy earns $3 for every $1 it loses. Must be > 1.0 to be profitable. Higher is better.

### CVaR(5%) (Conditional Value at Risk)

The average P&L of the **worst 5% of trades**. This is the tail risk metric — it tells you how bad a bad day gets. A CVaR(5%) of -10.0 means that in the worst 5% of cases, you lose an average of 10 pips per trade.

### N (Sample Size)

The number of trades that actually triggered at those parameters. More trades = more reliable statistics. Below ~30 trades, results should be treated with skepticism.

### Monte Carlo Simulation

A technique that uses random resampling to estimate the range of possible outcomes. Instead of relying on a single backtest result, we resample the trade history thousands of times (with replacement) to build a distribution of outcomes and confidence intervals.

### Bootstrap Resampling

The specific Monte Carlo method used here. Take the set of historical trade results, randomly draw N trades (with replacement) to create a "synthetic" history, calculate the mean P&L, repeat 10,000 times. The distribution of those 10,000 means gives you the confidence interval.

### Bonferroni Correction

A statistical adjustment for the **multiple comparisons problem**. When you test many hypotheses simultaneously (e.g., "is this strategy profitable on GBPUSD? on USDCAD? on USDZAR? ..."), the chance that *at least one* looks significant by pure luck increases with the number of tests. With 7 pairs at 95% confidence, there's a ~30% chance of at least one false positive.

**The fix**: Divide the significance level (alpha) by the number of comparisons. Testing 7 pairs at 95% confidence? The Bonferroni-adjusted CI uses alpha = 0.025/7 ≈ 0.36% per tail instead of 2.5% per tail. This widens the confidence interval, making it harder for a pair to appear significant — but any pair that still passes has survived a much stricter test.

**In the MC reports**: You'll see two CI columns — the raw 95% CI and the Bonferroni-adjusted CI. A pair that passes the Bonferroni CI is very unlikely to be a false positive. A pair that passes raw CI but fails Bonferroni (e.g., USDJPY) deserves paper trading and further monitoring but not immediate production.

**Limitation**: Bonferroni is conservative — it controls the probability of *any* false positive (family-wise error rate). It can make real edges look insignificant, especially with many comparisons. Walk-forward validation is the complementary guard: even if a CI is borderline, a pair that passes walk-forward on held-out data is showing a real out-of-sample edge.

### Walk-Forward Validation

The primary guard against overfitting. Optimize parameters on older data (in-sample), then test those exact parameters on newer data the optimizer never saw (out-of-sample). If performance holds, the edge is real. If it collapses, you were curve-fitting noise. See the [Monte Carlo 1-min report](../research/03-monte-carlo-18mo.md#walk-forward-validation) for details.

### Overfitting

When optimized parameters fit the noise in historical data rather than a genuine repeatable pattern. The classic sign: amazing backtest results that fall apart in live trading. Walk-forward validation is the primary defense.

### In-Sample vs Out-of-Sample

- **In-sample (IS)**: The data period used to optimize parameters (training set).
- **Out-of-sample (OOS)**: The held-out data period used to test those parameters (validation set). OOS performance is what matters.

### Max Drawdown

The largest peak-to-trough decline in cumulative P&L during a simulation. Tells you the worst losing streak you should expect. A 100-pip max drawdown means at some point your account was 100 pips below its previous high.

---

## Broker & Infrastructure Terms

### IB / IBKR (Interactive Brokers)

The brokerage used by this bot. IIROC-registered, available in all Canadian provinces including Alberta. Provides a socket API for automated trading.

### TWS (Trader Workstation)

IB's desktop trading platform. The bot connects to TWS via a local socket (port 7497 for paper, 7496 for live).

### IB Gateway

A lightweight headless version of TWS. Same API, no GUI. Uses port 4002 (paper) or 4001 (live).

### IBC

A third-party tool that auto-launches TWS/Gateway with saved credentials, handling login dialogs automatically. Enables fully unattended operation.

### Paper Trading

Simulated trading with fake money. Same market data, same order types, but no real money at risk. Port 4002 (Gateway) or 7497 (TWS).

### 2FA (Two-Factor Authentication)

A second verification step (push notification to IBKR Mobile) required for live trading login. Paper trading does not require 2FA.

### IIROC (Investment Industry Regulatory Organization of Canada)

Canada's investment industry self-regulatory body. Sets leverage limits and trading rules that IB enforces automatically.

---

## Abbreviations Quick Reference

| Abbreviation | Meaning |
|-------------|---------|
| Bonf. CI | Bonferroni-adjusted Confidence Interval |
| CI | Confidence Interval |
| CPI | Consumer Price Index |
| CVaR | Conditional Value at Risk |
| E[P&L] | Expected Profit and Loss |
| ET | Eastern Time (America/New_York) |
| FOMC | Federal Open Market Committee |
| IB / IBKR | Interactive Brokers |
| IBC | IB Controller (auto-login tool) |
| IIROC | Investment Industry Regulatory Organization of Canada |
| IS | In-Sample |
| MC | Monte Carlo |
| NFP | Non-Farm Payrolls |
| NLV | Net Liquidation Value (account balance) |
| OCA | One-Cancels-All |
| OHLCV | Open, High, Low, Close, Volume |
| OOS | Out-of-Sample |
| R:R | Reward-to-Risk Ratio |
| SL | Stop Loss |
| TP | Take Profit |
| TWS | Trader Workstation |
| 2FA | Two-Factor Authentication |
