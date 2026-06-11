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

- ~~**Generate tradeable events calendar for web dashboard**~~ — **DONE**: `forex-bot calendar` CLI command + auto-export every 6 hours to `~/00_data_projects/trading_dashboard/data/calendar.json`. JSON includes event name, datetime (UTC+ET), pairs, straddle params (with per-event overrides), source (FF/static), forecast/previous. See `src/forex_bot/calendar/export.py`.
- **Web dashboard** — Professional trading dashboard for monitoring performance and upcoming events. Must support both paper and live accounts. Key pages:
    - **Trade journal**: All trades with entry/exit, P&L (pips and $), strategy, event, pair. Filterable by date range, pair, event type, paper/live. Running equity curve.
    - **Performance analytics**: Sharpe ratio, win rate, profit factor, max drawdown, P&L by pair/event/strategy, monthly/weekly breakdown. Compare paper vs live.
    - **Event schedule**: Upcoming events (FF + static calendar) with countdown timers, which pairs will trade, straddle params being used, event history with actual vs forecast.
    - **System status**: IB connection state, circuit breaker status, last heartbeat, active positions, pending orders.
    - **Design**: Hedge-fund-grade UI/UX — dark theme, data-dense, real-time updates, mobile-responsive. Think Bloomberg Terminal meets modern web design.
    - **Tech**: FastAPI backend (reads from existing SQLite DB), React or Next.js frontend, WebSocket for live updates. Deployed locally or on the same machine as the bot.
- ~~**Mobile dashboard app**~~ — **Replaced by Telegram alerts**: Real-time trade notifications (opens, fills, closes with P&L, risk rejections, circuit breaker, connection status). See [Telegram Notifications](../operations/telegram-notifications.md).
- **Trump post strategy (stocks, not forex)** — Academic research confirms statistically significant market moves from Trump's social media posts ([ScienceDirect 2025](https://www.sciencedirect.com/science/article/abs/pii/S0261560625000786), [Warwick Business School](https://www.wbs.ac.uk/news/did-trumps-tweets-move-the-currency-markets/)). Key findings: 51% of high-impact Truth Social posts land pre-market (6–9:30 AM ET); 70% of the move is done within 2 hours; April 2025 "GREAT TIME TO BUY" post preceded S&P +9.5%, Nasdaq +12.2%. **Stocks may be a better fit than forex** — tariff posts directly name companies/sectors, S&P/Nasdaq moves are larger and more tradeable via IB, and IB already supports US equities. **Challenges**: unpredictable timing, requires real-time Truth Social monitoring, NLP/sentiment filtering (50-100+ posts/day), 3-8 minute reaction window, and a May 2026 investigation found markets moving *before* posts (front-running/information leakage). Would be a separate sub-strategy module alongside the existing forex news straddle.
- ~~**Add new currency pairs (EURUSD, AUDUSD)**~~ — **DONE (both fail)**: See [EURUSD & AUDUSD MC Analysis](07-mc-eurusd-audusd.md). EURUSD: E[P&L]=+0.4, CI spans zero [-1.3, +2.1], walk-forward fails (OOS=-2.0). AUDUSD: E[P&L]=+4.8 but N=19 (too few trades), CI spans zero. Neither pair passes — the straddle edge exists only in exotic pairs (USDZAR, USDTRY) where news-driven moves are larger relative to spreads. USDJPY on BOJ events is already being paper-traded separately.
- **MC-validate additional US event types** — These events are in `config/events.yaml` but **DISABLED** pending MC walk-forward analysis. Do NOT re-enable without a passing result:
    - ~~**PPI m/m**~~ — **DONE (PASSES)**: See [PPI MC Analysis](08-mc-ppi.md). E[P&L]=+17.1 (USDZAR), +11.1 (USDTRY). Both CIs above zero, both walk-forwards pass. Same 50/70/10 params. Re-enabled in events.yaml. Adds ~12 trading days/year.
    - ~~**GDP q/q**~~ — **DONE (PASSES)**: See [GDP & PCE MC Analysis](09-mc-gdp-pce.md). Both pairs pass. USDZAR E[P&L]=+15.8 CI=[+9.4,+22.3] WF OOS=+11.1. USDTRY E[P&L]=+8.5 CI=[+1.4,+15.5] WF OOS=+13.9. Adds ~12 trading days/year.
    - ~~**PCE**~~ — **DONE (PARTIAL)**: See [GDP & PCE MC Analysis](09-mc-gdp-pce.md). USDTRY passes (E[P&L]=+14.5, WF OOS=+11.1). **USDZAR fails walk-forward** (OOS=-0.7). Enabled for USDTRY only.
    - ~~**Unemployment Rate**~~ — **SKIPPED (redundant)**: Same BLS "Employment Situation" release as NFP. Straddle already triggers at identical time.
    - **Unemployment Claims** — Need to manually compile ~300+ weekly release dates from DOL (not available via FRED release API).
    - **ISM Manufacturing PMI** — Need to manually compile dates from ISM (private org, not on FRED).
    - **Retail Sales m/m** — Need correct Census Bureau release dates (FRED rid=63 returns revision dates, not monthly Advance release).
    - Each remaining event requires: (1) manual date compilation, (2) add to download script, (3) download Dukascopy data, (4) run MC, (5) walk-forward validate, (6) re-enable in events.yaml if passes.
- ~~**Non-US event dates in download script**~~ — **DONE**: Added BOC, Canada CPI, Canada Employment, BOJ, Japan CPI, SARB, TCMB, South Africa CPI event dates (2020-2026) to `scripts/download_dukascopy.py`. Added USDJPY to pairs. Event-pair mapping ensures only relevant pairs download for each event. Use `--group canada,japan` to download specific groups.
- ~~**Non-US event MC analysis (Canada, Japan)**~~ — **DONE**: See [Non-US Events Analysis](06-non-us-events.md). Results: **USDCAD fails** (CI spans zero on all Canadian events, WF OOS=-10.6). **USDJPY is promising but borderline** — WF passes (OOS=+6.4, Sharpe 2.45) but CI barely touches zero [-0.3, +5.3]. BOJ Rate decisions are the strongest non-US event (E[P&L]=+3.4, 62% WR). Recommendation: paper-trade USDJPY on BOJ events, re-evaluate end of 2026.
- ~~**SARB + SA CPI → USDZAR MC analysis**~~ — **DONE**: See [Non-US Events Analysis](06-non-us-events.md). Results: **USDZAR passes** — E[P&L]=+17.3, CI=[+12.5, +22.4], Sharpe 6.75, WF OOS=+8.3. Same 50/70/10 params as US events. Both SARB Rate (+16.3) and SA CPI (+17.8) independently profitable. Adds ~14 trading days/year.
- ~~**TCMB → USDTRY MC analysis**~~ — **DONE**: See [Non-US Events Analysis](06-non-us-events.md). Results: **USDTRY passes** — E[P&L]=+10.5, CI=[+5.2, +16.2], Sharpe 3.63, WF OOS=+14.8. Different params from US events (20/60/10 vs 50/70/10) — requires per-event-source overrides. Adds ~8-12 trading days/year.
- **Keep all future event dates up to date** — The download scripts (`scripts/download_dukascopy.py`, `scripts/monte_carlo_dukascopy.py`) and static calendar (`config/static_events.yaml`) need future event dates maintained. Currently have dates through mid-2026. Before each quarter, add newly announced dates for: NFP, CPI, FOMC, PPI (US); SARB, SA CPI (ZAR); TCMB (TRY); BOJ (JPY). Sources: BLS release calendar, SARB, TCMB, BOJ websites. The web dashboard's 30-day calendar depends on this being current.
- **Explore CAD-denominated pairs** — USDCAD fails straddle on both US and Canadian events. Investigate alternative CAD pairs: CADJPY (cross with JPY carry dynamics), EURCAD (ECB vs BOC divergence), GBPCAD (BOE vs BOC). Goal: find a tradeable CAD pair so the account's home currency gets direct exposure. Requires Dukascopy data download, MC analysis, and walk-forward validation for each candidate.

## Schedule (Medium Impact)

- **Carry trade strategy** — Buy high-yield currencies, sell low-yield. Exploits the forward premium puzzle: high-rate currencies don't depreciate as theory predicts, so you pocket the interest differential. Sharpe ~0.82 over 200+ years of data ([Quantpedia](https://quantpedia.com/fx-carry-value-momentum-strategies-over-their-200-year-history/)). USDZAR and USDTRY are already classic carry pairs. Hold for weeks/months, collect swap interest — IB handles rollover natively. Complements the news straddle (minutes) with an uncorrelated longer-horizon return stream. **Main risk**: periodic violent reversals during crises (2008, 2024 JPY unwind). Existing circuit breaker infrastructure could manage crash risk. Implementation: separate strategy module, weekly/monthly rebalancing.
- **Currency momentum strategy** — Buy recent winners, sell recent losers (1-12 month look-back). Sharpe ~0.95, returns up to 10% p.a. ([BIS Working Paper 366](https://www.bis.org/publ/work366.pdf), [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0304405X12001353)). Uncorrelated with carry (even -31% during crises), so combining them diversifies risk ([Kellogg/Northwestern](https://www.kellogg.northwestern.edu/faculty/rebelo/htm/carry.pdf)). Likely driven by behavioral underreaction then overreaction. Implementation: monthly rebalancing of a currency basket ranked by trailing returns. IB supports all major and exotic pairs needed.
- Model drift detection
- ~~**FOMC-specific parameter split**~~ — **DONE**: All three event types (NFP, CPI, FOMC) are independently profitable for both active pairs. FOMC optimal TP is slightly tighter (55-65 vs 70 pips) due to press conference reversal risk, but the marginal improvement doesn't justify splitting params yet. All 6 walk-forwards pass. See [Event-Type Split Analysis](05-event-type-split.md).
- ~~**Automatic event data download**~~ — **DONE**: Nightly cron job at 04:00 UTC (11 PM ET) runs `download_dukascopy.py --skip-existing --timeframe 1min` via `asyncio.create_subprocess_exec`. Appends new event data to existing CSVs automatically. See `src/forex_bot/data/dukascopy.py`.
- ~~**Remove Telegram alerts for IB connect/disconnect**~~ — **DONE**: Demoted to log-only. Daily TWS restart no longer sends Telegram alerts.
- ~~**Spread/slippage logging and modeling**~~ — **DONE**: `entry_spread_pips`, `fill_price`, `slippage_pips` tracked on every order. Spread captured at submission, slippage calculated on IB fill. Performance dashboard shows avg spread, avg slippage, total slippage. Auto-migrates existing SQLite DB.

## Backlog

- ~~**OCA modeling for straddle legs**~~ — **DONE**: Straddle buy/sell stops share an `ocaGroup` so IB cancels the unfilled leg on fill. See PR #14.
- ~~**Multiple testing correction (Bonferroni)**~~ — **DONE**: Both MC scripts report Bonferroni-adjusted CIs alongside raw 95% CIs. See PR #14.
- Expand sample size (ongoing, passive)
- ~~**IBKR base currency trap**~~ — **DONE**: Nightly currency sweep at 03:30 UTC (10:30 PM ET) converts all non-CAD residual cash balances back to CAD via IdealPro market orders. Handles majors (USD, JPY, EUR, GBP, AUD) directly, exotics (ZAR, TRY) via two-leg conversion through USD. See `src/forex_bot/broker/sweep.py`.

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
