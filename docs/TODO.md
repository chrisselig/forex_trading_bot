# To Do List

## Priority Matrix

Items are prioritized by **Impact** (how much it improves profitability/reliability) vs **Effort** (time and complexity to implement).

```
                        I M P A C T
                 Low          Medium          High
            ┌────────────┬────────────┬────────────┐
    High    │            │ Trump      │            │
            │            │ Strategy   │            │
   E        ├────────────┼────────────┼────────────┤
   F        │ Multiple   │ Model Drift│ Mobile     │
   F        │ Testing    │ Detection  │ Dashboard  │
   O        │ Correction │            │            │
   R        ├────────────┼────────────┼────────────┤
   T        │ OCA        │ FOMC Split │ 1-Min Data │
            │ Modeling   │ Analysis   │ Recording  │
    Low     │            │ Spread/    │ Re-run MC  │
            │            │ Slippage   │ w/ 1-min   │
            └────────────┴────────────┴────────────┘
```

### Do First (High Impact, Low Effort)
- 1-min data recording — unlocks better Monte Carlo
- Re-run MC optimization with 1-min bars once data exists

### Do Next (High Impact, High Effort)
- Mobile dashboard app
- Trump tweet strategy

### Schedule (Medium Impact)
- Model drift detection
- FOMC-specific parameter split
- Spread/slippage logging & modeling

### Backlog (Low Impact or Low Urgency)
- OCA modeling for straddle legs
- Multiple testing correction (Bonferroni)
- Expand sample size (ongoing, passive)

---

## Monte Carlo / Straddle Optimization Improvements

### 1. Hourly Bar Resolution
IB paper accounts only provide 1-hour bars for historical forex data. Intra-hour price paths cannot be observed. When both TP and SL could be hit in the same bar, SL is assumed first (pessimistic). Results may improve with finer granularity (live account with 1-min data). Trades should ideally exit in less than an hour and often within minutes — hourly bars can't capture this.

**Action**: Re-run optimization with 1-min bars once live account data is available, or record per-minute data going forward (see item below).

### 2. Small Sample Size
~48 events over 18 months. Bootstrap CIs account for sampling uncertainty, but structural regime changes (e.g., shift from tightening to easing) are not captured.

**Action**: Expand the event set over time. Consider adding more event types or extending the historical window as data accumulates.

### 3. Spread Approximation
Event-time spreads are modeled as fixed estimates. Actual spreads vary by broker, time, and event magnitude. Exotic pairs (USDZAR, USDTRY) spreads can exceed 50 pips during NFP.

**Action**: Record actual spreads during live events and feed them back into the simulation for more realistic modeling.

### 4. Slippage Not Modeled
Stop orders can gap through during fast markets. Actual fills may be worse than simulated, especially for the straddle entry.

**Action**: Log actual fill prices vs expected prices during live trading. Use the slippage distribution to add a slippage model to the simulation.

### 5. No OCA Modeling
Both straddle legs can trigger independently. In the worst case (whipsaw), both legs trigger and both stop out. This is modeled accurately — it contributes to the tail risk in CVaR.

**Action**: Investigate IB OCA (One-Cancels-All) group orders to auto-cancel the unfilled leg when one triggers.

### 6. Multiple Testing
Grid search over ~500 parameter combinations inflates the chance of finding spuriously good parameters. Walk-forward validation is the primary guard against this, but with only ~6 months of test data, out-of-sample results have wide confidence intervals.

**Action**: As more data accumulates, expand the out-of-sample window. Consider Bonferroni correction or other multiple-testing adjustments.

### 7. FOMC Has Different Dynamics
Rate decisions move markets differently from data releases (NFP/CPI). The optimal straddle parameters may differ for FOMC. Consider splitting the analysis by event type for production use.

**Action**: Split the Monte Carlo grid search by event type (NFP, CPI, FOMC separately) and compare optimal parameters.

---

## New Strategy: Trump Tweet Trading

**Branch**: Create a new feature branch. Do NOT open a PR until the whole process is confirmed good.

### Goal
Donald Trump tweets move markets. Use a tweet feed to trigger forex trades on major currency pairs. Same concept as the straddle/surprise strategies — detect the event, execute a trade with defined risk.

### Data Source
- Prioritise free sources
- Unusual Whales Trump Tracker: https://unusualwhales.com/trump-tracker (believed to be free)
- Filter out non-sensical tweets — focus on macroeconomic or market-mover tweets only

### Scope
- Watch only major currency pairs
- Look for spikes based on what Trump says
- Use lower amounts of paper currency (riskier strategy)
- Build as a professional, PhD-level mathematician working on Wall Street

### Process
1. Identify and integrate a free Trump tweet data source
2. Build a tweet filter (macro/market-relevant vs noise)
3. Implement the strategy (signal generation on relevant tweets)
4. Backtest against historical tweet data + price data
5. Run Monte Carlo simulation to optimize trade variables
6. Walk-forward validate

### Philosophy
The goal is NOT to make all the money — execute small, profitable, frequent (if need be) trades with limited loss potential.

---

## Data Collection: Record Per-Minute Bars

Look into recording per-minute forex data while the bot is running and saving it for future analysis. This would solve the hourly bar resolution limitation for future Monte Carlo runs.

**Action**: Investigate streaming 1-min bars from IB during events and persisting them (DuckDB or SQLite). This data would enable re-running the straddle optimization with much finer granularity.

---

## Mobile Dashboard / Tracking App

### Problem
The IBKR mobile app is annoying to use for tracking bot performance. Need a simple way to monitor wins/losses and overall profitability from an Android phone.

### Requirements
- Track wins/losses per trade, per strategy, per pair
- Show rolling P&L, win rate, Sharpe, drawdown — anything that helps keep this profitable over time
- Accessible from Android phone
- Simple and focused — not a full trading terminal, just a monitoring dashboard

### Options to Explore
- **Shiny for Python (shinylive)** — deploy on shinyapps.io, free tier available
- **Streamlit** — simple Python dashboards, can host on Streamlit Cloud (free)
- **Flask/FastAPI + lightweight frontend** — more control, host on a free tier (Render, Railway)
- **Telegram bot** — push notifications + quick stats on demand, no app to build

### Data Source
Read from the bot's SQLite trade journal (`data/forex_bot.db`). Could sync to a cloud DB or expose via a simple API.

---

## Model Drift Detection

### Problem
Market regimes change (tightening → easing, low vol → high vol). The optimized straddle parameters may degrade over time without detection.

### Approach
- Track rolling out-of-sample performance (e.g., last 20 trades vs historical baseline)
- Alert when win rate, mean P&L, or Sharpe drops below a threshold
- Flag when actual spreads or slippage diverge significantly from modeled assumptions
- Consider automated re-optimization on a quarterly cadence (re-run Monte Carlo with latest data)

### Integration
- Could feed into the mobile dashboard as a "strategy health" indicator
- Circuit breaker could incorporate drift signals (e.g., auto-cooldown if drift detected)
