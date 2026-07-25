# Spec 17 — Ambient Bracket Strategy Analysis (USDZAR / USDTRY)

**Status**: Pipeline 1.6 (user-prioritized). **Branch**: `feat/ambient-bracket-analysis`.
**Deliverable report**: `docs/research/17-ambient-bracket.md`.

## Background

Report 16's Run D proved the flagship straddle's P&L is ambient volatility
harvesting: the 50/70/10 bracket earns +10.9..+12.7 pips/trade on random
non-event weekdays, indistinguishable from event windows, both sessions.
The event calendar is a scheduler. Every prior number rests on a FLAT spread
assumption (USDZAR 25 / USDTRY 30 pips, one full spread per round trip) —
that assumption is the load-bearing wall. This analysis decides whether an
ambient variant (trading daily, not just ~2-4x/month on events) is worth
building, using MEASURED spreads instead of assumed ones.

## Phase A — Real spread measurement (the point of this spec)

1. **Dukascopy tick data** (`dukascopy_python` supports tick interval with
   bid+ask): fetch tick windows for a stratified sample of ~200 days/pair
   (2020-2026, all weekdays, holiday weeks excluded; reuse the Run D day
   list plus extend). For each sampled day, fetch ticks for two 30-min
   probe windows per session anchor (03:00, 09:00, 14:00, 20:00 UTC).
   Foreground chunked downloads, resume-safe, loud failures.
2. Produce the **spread profile**: per pair, per hour-anchor, per year —
   median/p75/p95 spread in pips. Flag regime shifts (e.g. TRY spreads
   post-2023 elections).
3. **Calibration check**: compare Dukascopy-measured spreads against (a)
   the ~30 real IDEALPRO `entry_spread_pips` values in the trade journal
   (data/forex_bot.db, orders table) and (b) report 16's assumptions.
   State honestly whether Dukascopy under/over-states what IB shows.
4. **Live sampler (deliverable, starts collecting for a future report)**:
   `scripts/sample_ib_spreads.py` — standalone, connects to TWS with
   clientId=9 (NEVER 1 — that's the bot), snapshots IDEALPRO bid/ask for
   USDZAR/USDTRY, appends to `scripts/data/ib_spread_samples.csv`, exits.
   Add a cron line suggestion (hourly, weekdays) to the report — do NOT
   install the cron yourself.

## Phase B — Ambient P&L with measured spreads

1. Extend the Run D framework: ~300 non-event days/pair (download more
   1-min windows as needed), anchors at 03:00/09:00/14:00/20:00 UTC.
2. Simulate the bracket charging each trade its MEASURED spread (per pair,
   per anchor-hour, per year from Phase A; use p75 as the base case, p95
   as stress) instead of flat 25/30.
3. Re-run the event windows (report 16 Run C) under the same measured-
   spread model for a fair event-vs-ambient comparison.
4. Parameter grid around 50/70/10 (distance {35,50,65}, TP {50,70,90},
   SL {10,15}) with walk-forward (train 2020-2024, test 2025-2026) — does
   50/70/10 remain optimal in ambient context?

## Phase C — Portfolio design questions

1. **Frequency/overlap**: one bracket per pair per anchor vs per day; no
   concurrent trades in the same pair; max hold 6h (mirror report 16
   mechanics). Trades/year at each design point.
2. **Aggregate stats per design**: E[P&L]/trade and /year (pips), Sharpe,
   max drawdown (bootstrap path percentiles), yearly sub-period table
   (2020..2026 — no cherry-picking), pair correlation.
3. **Margin reality**: with the margin cap (25% of AvailableFunds/order,
   ~$4.9K account), both pairs can't always run concurrently — state the
   practical position budget and per-trade CAD P&L at current sizing.
4. **Vol-regime sensitivity**: split days by realized-vol terciles
   (prior-day ATR) — is the edge concentrated in high-vol regimes?

## Pass bar and report

Same discipline as prior reports: an ambient design point "passes" only if
95% CI > 0 at p75 measured spreads AND WF OOS positive AND survives p95
spread stress. Report `docs/research/17-ambient-bracket.md`: spread
profile tables, measured-vs-assumed calibration, event-vs-ambient under
identical cost model, design-point table, yearly stability, explicit
**Production recommendation** (build ambient module / don't / collect live
spreads first). Building any module is a LATER phase gated on user
approval — this report changes no config and no src code.

## Constraints

- Foreground chunked downloads only; no background watchers. Loud failures.
- `~/anaconda3/envs/forex-bot/bin/python` only; repo style; ruff-clean.
- No changes under `src/` or `config/`. No commits/pushes. Bot/TWS untouched
  (the live sampler script is created but only run once as a smoke test,
  with clientId=9, only if TWS is currently listening).
- Tick data volumes are large — sample, don't bulk-download; cache to
  `scripts/data/_cache/ticks/`; document total download size.
