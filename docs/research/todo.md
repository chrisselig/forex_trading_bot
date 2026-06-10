# Roadmap

## Priority Matrix

```
                        I M P A C T
                 Low          Medium          High
            ┌────────────┬────────────┬────────────┐
    High    │            │ Trump      │ Web        │
            │            │ Strategy   │ Dashboard  │
   E        ├────────────┼────────────┼────────────┤
   F        │ ✓ Multiple│ Model Drift│ ✓ Telegram │
   F        │  Testing  │ Detection  │  Alerts    │
   O        │  Correct. │            │            │
   R        ├────────────┼────────────┼────────────┤
   T        │ ✓ OCA    │ ✓ FOMC    │ ✓ 1-Min   │
            │  Modeling │  Split    │  Data Done │
    Low     │            │ Spread/    │ ✓ Re-run  │
            │            │ Slippage   │  MC done  │
            └────────────┴────────────┴────────────┘
```

## Do First (High Impact, Low Effort)

- ~~**1-min data recording**~~ — **DONE**: Dukascopy download script (`scripts/download_dukascopy.py`) fetches 1-min and 5-min bars for all 5 pairs around all events. See [Dukascopy Data](02-dukascopy-data.md).
- ~~**Re-run MC optimization**~~ — **DONE**: 1-min Dukascopy bars used. USDZAR strongest performer (walk-forward OOS E[P&L]=+47.1). See [Monte Carlo 1-min](03-monte-carlo-18mo.md).

## Do Next (High Impact, High Effort)

- **Web dashboard** — Professional trading dashboard for monitoring performance and upcoming events. Must support both paper and live accounts. Key pages:
    - **Trade journal**: All trades with entry/exit, P&L (pips and $), strategy, event, pair. Filterable by date range, pair, event type, paper/live. Running equity curve.
    - **Performance analytics**: Sharpe ratio, win rate, profit factor, max drawdown, P&L by pair/event/strategy, monthly/weekly breakdown. Compare paper vs live.
    - **Event schedule**: Upcoming events (FF + static calendar) with countdown timers, which pairs will trade, straddle params being used, event history with actual vs forecast.
    - **System status**: IB connection state, circuit breaker status, last heartbeat, active positions, pending orders.
    - **Design**: Hedge-fund-grade UI/UX — dark theme, data-dense, real-time updates, mobile-responsive. Think Bloomberg Terminal meets modern web design.
    - **Tech**: FastAPI backend (reads from existing SQLite DB), React or Next.js frontend, WebSocket for live updates. Deployed locally or on the same machine as the bot.
- ~~**Mobile dashboard app**~~ — **Replaced by Telegram alerts**: Real-time trade notifications (opens, fills, closes with P&L, risk rejections, circuit breaker, connection status). See [Telegram Notifications](../operations/telegram-notifications.md).
- **Trump post strategy (stocks, not forex)** — Academic research confirms statistically significant market moves from Trump's social media posts ([ScienceDirect 2025](https://www.sciencedirect.com/science/article/abs/pii/S0261560625000786), [Warwick Business School](https://www.wbs.ac.uk/news/did-trumps-tweets-move-the-currency-markets/)). Key findings: 51% of high-impact Truth Social posts land pre-market (6–9:30 AM ET); 70% of the move is done within 2 hours; April 2025 "GREAT TIME TO BUY" post preceded S&P +9.5%, Nasdaq +12.2%. **Stocks may be a better fit than forex** — tariff posts directly name companies/sectors, S&P/Nasdaq moves are larger and more tradeable via IB, and IB already supports US equities. **Challenges**: unpredictable timing, requires real-time Truth Social monitoring, NLP/sentiment filtering (50-100+ posts/day), 3-8 minute reaction window, and a May 2026 investigation found markets moving *before* posts (front-running/information leakage). Would be a separate sub-strategy module alongside the existing forex news straddle.
- **Add new currency pairs** — EURUSD (most liquid pair, reacts strongly to NFP/CPI/FOMC, tightest news spreads), USDJPY (very reactive to FOMC and rate differentials, carry trade dynamics), AUDUSD (risk-sensitive, sharp moves on US data surprises). Download Dukascopy data, run MC analysis, and only enable pairs that pass walk-forward validation.
- **Add new US event types** — PCE (Fed's preferred inflation gauge, increasingly more important than CPI), Retail Sales (consumer spending = 70% of US GDP, regular 30-50 pip moves), GDP Advance (quarterly, large moves on first estimate), ISM Manufacturing PMI (leading indicator, sharp moves near 50 threshold). Requires adding event dates to download script, calendar scraper, and re-running MC.
- ~~**Non-US event dates in download script**~~ — **DONE**: Added BOC, Canada CPI, Canada Employment, BOJ, Japan CPI, SARB, TCMB, South Africa CPI event dates (2020-2026) to `scripts/download_dukascopy.py`. Added USDJPY to pairs. Event-pair mapping ensures only relevant pairs download for each event. Use `--group canada,japan` to download specific groups.
- ~~**Non-US event MC analysis (Canada, Japan)**~~ — **DONE**: See [Non-US Events Analysis](06-non-us-events.md). Results: **USDCAD fails** (CI spans zero on all Canadian events, WF OOS=-10.6). **USDJPY is promising but borderline** — WF passes (OOS=+6.4, Sharpe 2.45) but CI barely touches zero [-0.3, +5.3]. BOJ Rate decisions are the strongest non-US event (E[P&L]=+3.4, 62% WR). Recommendation: paper-trade USDJPY on BOJ events, re-evaluate end of 2026.
- ~~**SARB + SA CPI → USDZAR MC analysis**~~ — **DONE**: See [Non-US Events Analysis](06-non-us-events.md). Results: **USDZAR passes** — E[P&L]=+17.3, CI=[+12.5, +22.4], Sharpe 6.75, WF OOS=+8.3. Same 50/70/10 params as US events. Both SARB Rate (+16.3) and SA CPI (+17.8) independently profitable. Adds ~14 trading days/year.
- ~~**TCMB → USDTRY MC analysis**~~ — **DONE**: See [Non-US Events Analysis](06-non-us-events.md). Results: **USDTRY passes** — E[P&L]=+10.5, CI=[+5.2, +16.2], Sharpe 3.63, WF OOS=+14.8. Different params from US events (20/60/10 vs 50/70/10) — requires per-event-source overrides. Adds ~8-12 trading days/year.
- **Explore CAD-denominated pairs** — USDCAD fails straddle on both US and Canadian events. Investigate alternative CAD pairs: CADJPY (cross with JPY carry dynamics), EURCAD (ECB vs BOC divergence), GBPCAD (BOE vs BOC). Goal: find a tradeable CAD pair so the account's home currency gets direct exposure. Requires Dukascopy data download, MC analysis, and walk-forward validation for each candidate.

## Schedule (Medium Impact)

- **Carry trade strategy** — Buy high-yield currencies, sell low-yield. Exploits the forward premium puzzle: high-rate currencies don't depreciate as theory predicts, so you pocket the interest differential. Sharpe ~0.82 over 200+ years of data ([Quantpedia](https://quantpedia.com/fx-carry-value-momentum-strategies-over-their-200-year-history/)). USDZAR and USDTRY are already classic carry pairs. Hold for weeks/months, collect swap interest — IB handles rollover natively. Complements the news straddle (minutes) with an uncorrelated longer-horizon return stream. **Main risk**: periodic violent reversals during crises (2008, 2024 JPY unwind). Existing circuit breaker infrastructure could manage crash risk. Implementation: separate strategy module, weekly/monthly rebalancing.
- **Currency momentum strategy** — Buy recent winners, sell recent losers (1-12 month look-back). Sharpe ~0.95, returns up to 10% p.a. ([BIS Working Paper 366](https://www.bis.org/publ/work366.pdf), [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0304405X12001353)). Uncorrelated with carry (even -31% during crises), so combining them diversifies risk ([Kellogg/Northwestern](https://www.kellogg.northwestern.edu/faculty/rebelo/htm/carry.pdf)). Likely driven by behavioral underreaction then overreaction. Implementation: monthly rebalancing of a currency basket ranked by trailing returns. IB supports all major and exotic pairs needed.
- Model drift detection
- ~~**FOMC-specific parameter split**~~ — **DONE**: All three event types (NFP, CPI, FOMC) are independently profitable for both active pairs. FOMC optimal TP is slightly tighter (55-65 vs 70 pips) due to press conference reversal risk, but the marginal improvement doesn't justify splitting params yet. All 6 walk-forwards pass. See [Event-Type Split Analysis](05-event-type-split.md).
- **Automatic event data download** — After each traded event, automatically download the 1-min Dukascopy data for that event's pairs and append to the local CSV files. Eliminates the manual quarterly `download_dukascopy.py` step. Could run as a post-event job in APScheduler (e.g., 2 hours after the event) or as a nightly batch. Keeps the MC dataset always up-to-date so re-runs use the latest data without manual intervention.
- Spread/slippage logging and modeling

## Backlog

- ~~**OCA modeling for straddle legs**~~ — **DONE**: Straddle buy/sell stops share an `ocaGroup` so IB cancels the unfilled leg on fill. See PR #14.
- ~~**Multiple testing correction (Bonferroni)**~~ — **DONE**: Both MC scripts report Bonferroni-adjusted CIs alongside raw 95% CIs. See PR #14.
- Expand sample size (ongoing, passive)
- **IBKR base currency trap** — Review and implement auto-conversion of residual foreign currency balances back to CAD after closing forex trades. IBKR leaves open FX balances when you trade (e.g., buying EUR/USD borrows USD to buy EUR). At small account scale, these residual balances should be swept back to CAD immediately so statements reflect true net CAD P&L. Investigate: (a) manual post-trade sweep via IB API, (b) IBKR "Virtual FX Position" setting, (c) auto-close via IdealPro conversion after each trade close.

---

## Live Trading Readiness

### 2FA Testing Required Before Going Live

Paper trading does not require 2FA, so the IBC auto-start pipeline is fully unattended. **Live trading will require 2FA via the IBKR Mobile app.** Before switching to live:

1. Test the IBC auto-start with live credentials and confirm the 2FA push notification arrives
2. Verify `TWOFA_TIMEOUT_ACTION=restart` correctly re-triggers the push if missed
3. Confirm `ReloginAfterSecondFactorAuthenticationTimeout=yes` works as expected
4. Time the full login flow (TWS launch > 2FA approval > API socket ready) to ensure the 1-hour pre-market window is sufficient
5. Consider whether the nightly TWS restart also requires 2FA re-authentication on live accounts
6. Update the cron schedule if the live login flow takes significantly longer than paper
