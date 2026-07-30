# Spec 18 — Event-Strategy Net-of-Cost Audit

**Status**: TOP PRIORITY (pipeline 1.7). **Branch**: `feat/event-net-of-cost-audit`.
**Deliverable report**: `docs/research/18-event-net-of-cost.md`.

## The question

Reports 04–16 compute **gross** P&L: in `simulate_straddle`/`simulate_bracket`
the spread only shifts the entry trigger by spread/2 — it is never deducted
from realized P&L (verified in report 17's reviewer addendum). Under an honest
**one-full-spread-per-round-trip** cost (correct for bid-based backtest data:
a long fills at ask, exits at bid), even the event straddle looked
marginal-to-negative in report 17's spot check (USDZAR event ~−6.7, USDTRY
~−1.5 pips/trade).

**Decide, per active production combo, whether the live event straddle clears
its real spread cost.** This governs whether the currently-configured strategy
is economically viable at all — higher priority than any new candidate.

## Cost model

- Deduct **one full round-trip spread** per triggered leg from its realized
  P&L (the report-17 `[full]` convention already implemented in
  `scripts/mc_ambient_bracket.py`). Report BOTH gross (report-16 convention)
  and net side by side so the delta is explicit.
- **Spread values = REAL IDEALPRO event-time spreads**, NOT Dukascopy tick
  spreads (report 17 proved Dukascopy exotics are 3.6–15× too wide — wrong
  venue). Source, in priority order:
  1. The trade journal's `entry_spread_pips` on real straddle order attempts
     (data/forex_bot.db orders table) — these ARE event-time IDEALPRO spreads.
     Report 17 calibration: USDZAR mean 23.5 (n=5), USDTRY 12.1 (n=12).
  2. `scripts/data/ib_spread_samples.csv` if the live sampler has accumulated
     rows since 2026-07-29.
- **Base case**: USDZAR 24, USDTRY 12 pips. **Sensitivity**: also report at
  USDTRY 6 (the live-snapshot low) and a wide-stress point (USDZAR 40,
  USDTRY 30) so the verdict's spread-sensitivity is visible. State clearly
  that the IDEALPRO spread samples are thin (n≈5–12) — this is the audit's
  biggest caveat, and why `sample_ib_spreads.py` should keep collecting.

## Scope — every active production combo at configured params

From `config/settings.yaml` + `config/events.yaml` (post report-16 config):
- **USDZAR @ 50/70/10**: NFP, CPI, FOMC, PPI, GDP, PCE, SARB, SA CPI
- **USDTRY @ 50/70/10**: NFP, CPI, FOMC, PPI, GDP, PCE, Unemployment Claims,
  ISM Manufacturing PMI, Retail Sales; **@ 35/70/10**: TCMB
Use the CORRECTED (tz-fixed) Dukascopy 1-min windows from report 16's
re-download — do NOT reintroduce the shifted data.

## Method

- Reuse the report-16 / report-17 simulator and walk-forward machinery
  (train 2020-2024, test 2025-2026, 10,000× bootstrap). Extend
  `mc_ambient_bracket.py`'s event path or the existing event-split scripts —
  minimal new code, document any patch.
- Per combo, per spread point: gross E[P&L], net E[P&L], net 95% CI, net
  Sharpe, net walk-forward OOS. Aggregate to a per-pair net expectancy
  weighted by real event frequency (events/year) to get an honest
  net-pips/year and, using current margin-capped position sizing (~2,700
  USDTRY / ~8,000 USDZAR units), net CAD/year.

## Pass bar & report

A combo "clears cost" only if **net 95% CI > 0 at the base-case spread AND
net walk-forward OOS > 0**. Report `docs/research/18-event-net-of-cost.md`:
per-combo gross-vs-net table, spread sensitivity, per-pair net expectancy,
and an explicit **Production recommendation** — which combos to keep, which
to disable, and whether the strategy is viable net of costs at all. If the
answer is "the event edge does not survive real spreads," say so plainly;
that is the most valuable outcome this audit can produce. **No config or
src changes** — recommendations only; config is the user's call.

## Constraints

- FOREGROUND execution only — no background processes, no watchers (three
  prior pipeline stalls came from this). Bounded chunks, explicit timeouts,
  verify output after each, loop.
- `~/anaconda3/envs/forex-bot/bin/python` only; repo style; ruff-clean.
- No commits/pushes; leave work uncommitted for review. Bot/TWS untouched.
