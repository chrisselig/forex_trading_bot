# Roadmap

## Priority Matrix

```
                        I M P A C T
                 Low          Medium          High
            ┌────────────┬────────────┬────────────┐
    High    │            │ Trump      │            │
            │            │ Strategy   │            │
   E        ├────────────┼────────────┼────────────┤
   F        │ Multiple   │ Model Drift│ ✓ Telegram │
   F        │ Testing    │ Detection  │  Alerts    │
   O        │ Correction │            │            │
   R        ├────────────┼────────────┼────────────┤
   T        │ OCA        │ FOMC Split │ ✓ 1-Min   │
            │ Modeling   │ Analysis   │  Data Done │
    Low     │            │ Spread/    │ Re-run MC  │
            │            │ Slippage   │ w/ 1-min   │
            └────────────┴────────────┴────────────┘
```

## Do First (High Impact, Low Effort)

- ~~**1-min data recording**~~ — **DONE**: Dukascopy download script (`scripts/download_dukascopy.py`) fetches 1-min and 5-min bars for all 5 pairs around all events. See [Dukascopy Data](dukascopy-data.md).
- ~~**Re-run MC optimization**~~ — **DONE**: 1-min Dukascopy bars used. USDZAR strongest performer (walk-forward OOS E[P&L]=+47.1). See [Monte Carlo 1-min](monte-carlo-1min.md).

## Do Next (High Impact, High Effort)

- ~~**Mobile dashboard app**~~ — **Replaced by Telegram alerts**: Real-time trade notifications (opens, fills, closes with P&L, risk rejections, circuit breaker, connection status). See [Telegram Notifications](../operations/telegram-notifications.md).
- **Trump tweet strategy**
- **Add new currency pairs** — EURUSD (most liquid pair, reacts strongly to NFP/CPI/FOMC, tightest news spreads), USDJPY (very reactive to FOMC and rate differentials, carry trade dynamics), AUDUSD (risk-sensitive, sharp moves on US data surprises). Download Dukascopy data, run MC analysis, and only enable pairs that pass walk-forward validation.
- **Add new event types** — PCE (Fed's preferred inflation gauge, increasingly more important than CPI), Retail Sales (consumer spending = 70% of US GDP, regular 30-50 pip moves), GDP Advance (quarterly, large moves on first estimate), ISM Manufacturing PMI (leading indicator, sharp moves near 50 threshold). Requires adding event dates to download script, calendar scraper, and re-running MC.

## Schedule (Medium Impact)

- Model drift detection
- FOMC-specific parameter split
- Spread/slippage logging and modeling

## Backlog

- OCA modeling for straddle legs
- Multiple testing correction (Bonferroni)
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
