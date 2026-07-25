# 16 — Full MC Re-validation on Timezone-Corrected Dukascopy Data

**Date**: July 2026
**Status**: DRAFT — pending user review. No config changes made.
**Spec**: `docs/research/specs/16-dukascopy-tz-revalidation-spec.md`
**Scripts**: `scripts/mc_event_split.py`, `scripts/mc_non_us.py`,
`scripts/mc_grids_fast.py` (grid substitute for the killed
`mc_remaining_us.py` / `mc_audusd_explore.py` reruns — see caveat 8),
`scripts/mc_fixed_params_check.py` (configured-param evals),
`scripts/mc_ambient_control.py` (control experiment)

---

## Why this report exists

Every prior Monte Carlo report (04-12) was computed on **timezone-shifted
data**. `scripts/download_dukascopy.py` passed naive datetimes to
`dukascopy_python.fetch()`, which interprets naive datetimes in the *system
local* timezone (America/Edmonton). Every event window was therefore fetched
+6h/+7h late: the "event window" actually contained bars from 6-7 hours after
the release, and the simulated "release burst" was in reality mid-afternoon
drift.

Two bugs were fixed for this re-validation:

1. **Downloader timezone bug** (`scripts/download_dukascopy.py`): `start`/`end`
   are now made UTC-aware (`.replace(tzinfo=UTC)`) immediately before
   `dp.fetch()`. Proof: the NFP 2023-02-03 GBPUSD window now spans 11:30-17:30
   UTC and contains an 86.0-pip 1-min bar exactly at 13:30:00 UTC (the release
   minute). The old file's window contained no such burst.
2. **Loader collision bug** (`scripts/monte_carlo_dukascopy.py`,
   `load_dukascopy_data`): events were grouped by `event_date` only. Two events
   on the same date (SARB + Unemployment Claims both land on Thursdays; GDP +
   Unemployment Claims share 13:30 UTC Thursdays) were merged into one group
   with an arbitrary label and duplicated bars. With the CSVs now containing
   all event types, this silently dropped 36 of 40 SARB events and contaminated
   per-event-type splits. Grouping is now by `(event_date, event_name)`.

All numbers below are from the corrected data **and** the corrected loader.
Old numbers are quoted from reports 04-12 (shifted data) for comparison only —
they describe a strategy that was never actually tested at release time.

**Data re-downloaded**: 11,692 event windows, 4.19M 1-min bars, 11 pairs,
Jan 2020 - Jun 2026. Old (shifted) CSVs preserved in
`scripts/data/dukascopy_SHIFTED_BAD/`. Old result JSON/reports preserved in
`scripts/data/OLD_RESULTS_SHIFTED_BAD/`.

---

## Executive summary

**USDZAR and USDTRY pass at their exact configured params on nearly every
configured event source** — often with better numbers than the shifted-data
reports claimed. **But the control experiment below shows the profit is NOT
primarily an event edge**: the same 50/70/10 straddle on 160 uniformly random
NON-event weekdays (Run D) earns +10.9 to +12.7 pips/trade with CIs entirely
above zero — statistically indistinguishable from the true event windows
(+15.1 USDZAR / +13.3 USDTRY), at both London/NY and Asia anchors. **The
strategy is ambient volatility harvesting on two EM pairs; the event calendar
is a scheduler, not the edge.** A PASS in the verdict table certifies that
this ambient volatility cleared the assumed spread through the 7:1 TP:SL
bracket, 2020-2026 including OOS — with at most a ~+2-3 pip event-specific
increment (CIs overlap). See "Why the shifted data looked plausible" for the
evidence and consequences.

**Two pair-level failures**:

- **USDJPY / BOJ** at configured 25/15/15: E[P&L]=+0.9, CI=[-3.1, +4.9] — no
  edge. Walk-forward on Japanese events fails (OOS -2.0). Recommend removing.
- **AUDUSD (all 9 configured combos)** at configured params: every US event
  fails at 40/15/25 (PPI is significantly *negative*: -10.4 [-16.3, -4.2]);
  every AU event fails at 40/70/30 (CIs span zero, tiny N). Fresh grids on
  all three event sources find no walk-forward-valid optimum. Recommend
  removing.

**Two surprising reversals on disabled pairs** (quick check only, not deep
grids): EURUSD on US events and CADJPY on Japanese events now show CIs above
zero including out-of-sample. Not production recommendations — flagged for a
dedicated follow-up analysis.

---

## Why the shifted data looked plausible — and what it reveals

The old windows contained no releases, yet reports 04-12 produced numbers of
the same magnitude as this re-validation (USDZAR +17.1 then, +9.9..+23.5 now).
That demanded an explanation before trusting any PASS below.

### Mechanism: the simulator anchored on the window, not the clock

`simulate_straddle()` locates its entry bar with
`argmin(|bar_times - (event_utc - 30min)|)` — the bar *closest* to the
intended pre-event time, with no requirement that it precede the event. The
shifted CSVs contained bars spanning `[event+4h, event+10h]` (the -2h/+4h
request, shifted +6h). The closest bar to `event-30min` was therefore simply
the **first bar of the window**, and the guard (`pre_idx >= len(bars)-10`)
did not fire. Every old backtest silently simulated a straddle placed ~4h
after the release and held for up to the following 6 hours of (real, correctly
timestamped) bars. A consistent, well-defined window — just not the one
anyone intended.

### Replication + control experiment

`simulate_straddle` at 50/70/10 (configured spreads: USDZAR 25, USDTRY 30),
6-US-event scope, five anchors
(script: `scripts/mc_ambient_control.py`; Run D windows downloaded with the
fixed fetcher — 160 uniformly sampled weekdays per pair, 2020-2026, with no
tracked high-impact release for the pair that day per the pair's event CSV +
`ff_history.csv`, holiday weeks excluded):

| Run | Data | Anchor | USDZAR E[P&L] / CI | USDTRY E[P&L] / CI |
|-----|------|--------|--------------------|--------------------|
| A | old shifted CSV | stored event_utc (= window start, event+4h) | +16.0 [+12.9, +19.3] N=798 | +12.1 [+9.4, +14.8] N=644 |
| B | old shifted CSV | event+6.5h — no event in window, event day | +12.1 [+9.6, +14.6] N=761 | +17.3 [+12.7, +22.6] N=588 |
| C | corrected CSV | true event time | +15.1 [+12.5, +17.6] N=820 | +13.3 [+10.6, +16.1] N=648 |
| **D** | **non-event days** | **14:00 UTC (London/NY)** | **+11.7 [+7.9, +15.8]** N=291 | **+11.8 [+7.1, +16.7]** N=210 |
| **D** | **non-event days** | **03:00 UTC (Asia)** | **+12.7 [+8.5, +16.9]** N=285 | **+10.9 [+6.6, +15.5]** N=231 |

(NFP+CPI+FOMC scope, Run A: USDZAR +16.5, USDTRY +12.5 — matching report 04's
+17.1 / +13.6 almost exactly. Mechanism confirmed.)

### What this means

1. **Run D is conclusive: Run D ~ Run C.** On 160 uniformly random weekdays
   with no tracked release — at both a liquid London/NY anchor and an
   illiquid Asia anchor — the same bracket earns +10.9 to +12.7 pips/trade
   with CIs entirely above zero, statistically indistinguishable from the
   true event windows (+15.1 / +13.3; CIs overlap). Run B's ambiguity
   (residual post-event elevation) is resolved: post-release elevation is NOT
   needed. **The strategy is ambient volatility harvesting; the event
   calendar is acting as a scheduler, not as the edge.**
2. **It is volatility harvesting, not trend drift.** Per-leg breakdown on
   corrected event windows: USDZAR BUY +14.5 / SELL +15.8 (symmetric — not a
   rand-depreciation bet); USDTRY BUY +6.5 / SELL **+18.4** (the *short-USD*
   leg earns more, the opposite of the lira-collapse drift story). The 7:1
   TP:SL bracket wins whenever a 50-pip excursion runs another 70 pips before
   retracing 10 — which these pairs did, in any window, any session,
   ~27-31% of the time, 2020-2026.
3. **Event-specific increment**: USDZAR ~+3 pips/trade over ambient (C vs D,
   CIs overlap); USDTRY ~+2 (C vs D, CIs overlap). The per-event-type spread
   in the verdict table (FOMC +23.5 vs NFP +9.9 on USDZAR) is the strongest
   remaining evidence that release choice matters at all.
4. **Reinterpretation of every PASS below**: PASS = "this pair's 2020-2026
   ambient volatility cleared the assumed 25/30-pip spread through an
   asymmetric bracket, including in 2025-26 OOS." It does *not* certify a
   news-reaction edge. Consequences:
   - The strategy's true risk factor is a **volatility/spread regime** on two
     EM pairs, not a diversified set of 17 event edges. Event diversification
     is largely illusory — all 17 combos load on the same two underlying
     exposures.
   - Results are highly sensitive to the flat spread assumption (25/30
     pips). Event-time spreads on exotics can be far wider (config caps at
     60/80 pips); non-event spreads are typically narrower than event
     spreads, which if anything *flatters* the event windows in this
     comparison. Live slippage monitoring is the real test.
   - The economics of the current config are not invalidated — event days
     are as good as any other day, and the OOS numbers held up. But the
     *rationale* in reports 04-12 ("news-reaction straddle") is wrong.
   - **Follow-up (not this report)**: a dedicated "ambient bracket strategy"
     analysis — realistic non-event spreads, trade frequency and overlap
     limits, session effects, capacity, regime dependence (does this survive
     a ZAR/TRY low-vol regime?). This report does NOT recommend expanding
     trading hours; the current event schedule remains the tested
     configuration.

The USDJPY and AUDUSD failures below are unaffected by this nuance — they
fail even with ambient volatility included.

---

## Verdict table — every active production combo

Configured params from `config/settings.yaml` / `config/events.yaml`.
"OLD" = shifted-data reports 04-12. "NEW" = corrected data, corrected loader.
OOS = fixed configured params evaluated on 2025-2026 (not train-optimal).

| # | Combo | Params | OLD E[P&L] / CI | NEW E[P&L] / CI | NEW Sharpe | NEW OOS E (2025-26) | Verdict |
|---|-------|--------|-----------------|-----------------|------------|----------------------|---------|
| 1 | USDZAR / NFP | 50/70/10 | +23.1 [+12.2,+36.6] | +9.9 [+4.6,+15.6] | 3.49 | +15.1 | **SURVIVES** (weaker) |
| 2 | USDZAR / CPI | 50/70/10 | +13.7 [+8.0,+19.7] | +15.2 [+9.0,+21.3] | 4.86 | +7.0 | **SURVIVES** |
| 3 | USDZAR / FOMC | 50/70/10 | +13.8 [+6.2,+21.5] | +23.5 [+15.3,+31.6] | 5.87 | +13.3 | **SURVIVES** (stronger) |
| 4 | USDZAR / PPI | 50/70/10 | +17.1 [+10.3,+23.9] | +14.8 [+8.8,+20.9] | 4.80 | +4.5 | **SURVIVES** |
| 5 | USDZAR / GDP | 50/70/10 | +15.8 [+9.4,+22.3] | +17.0 [+10.8,+23.2] | 5.35 | +14.0 | **SURVIVES** |
| 6 | USDZAR / SARB | 50/70/10 | +16.3 [+7.9,+24.7] | +23.2 [+14.9,+32.6] | 5.15 | +12.2 | **SURVIVES** (stronger) |
| 7 | USDZAR / SA CPI | 50/70/10 | +17.8 [+11.7,+23.9] | +17.4 [+11.4,+23.4] | 5.53 | +14.4 | **SURVIVES** |
| 8 | USDTRY / NFP | 50/70/10 | +13.7 [+7.4,+20.2] | +12.3 [+6.3,+18.8] | 3.80 | +10.4 | **SURVIVES** |
| 9 | USDTRY / CPI | 50/70/10 | +12.5 [+6.2,+19.1] | +16.9 [+10.7,+23.8] | 4.81 | +7.4 | **SURVIVES** |
| 10 | USDTRY / FOMC | 50/70/10 | +16.1 [+6.6,+26.3] | +18.0 [+10.2,+25.9] | 4.52 | +30.0 | **SURVIVES** (stronger) |
| 11 | USDTRY / PPI | 50/70/10 | +11.1 [+4.7,+17.7] | +16.2 [+9.1,+23.4] | 4.34 | +17.0 | **SURVIVES** |
| 12 | USDTRY / GDP | 50/70/10 | +8.5 [+1.4,+15.5] | +9.8 [+3.0,+16.7] | 2.87 | +15.3 | **SURVIVES** |
| 13 | USDTRY / PCE | 50/70/10 | +14.5 [+7.6,+22.0] | +8.0 [+2.3,+14.5] | 2.48 | +12.2 | **SURVIVES** (weaker) |
| 14 | USDTRY / TCMB | 20/60/10 | +10.5 [+5.2,+16.2] | +9.0 [+3.7,+14.5] | 3.20 | +6.5 | **SURVIVES** (new optimum 35/70/10: +13.1) |
| 15 | USDTRY / Unemp. Claims | 50/70/10 | OOS +16.9..+22.7 | +9.8 [+6.8,+13.1] | 6.11 | +9.0 | **SURVIVES** |
| 16 | USDTRY / ISM PMI | 50/70/10 | OOS +6.3..+7.1 | +9.6 [+3.8,+16.2] | 2.89 | +3.3 | **SURVIVES, weakened** (WF OOS CI spans 0) |
| 17 | USDTRY / Retail Sales | 50/70/10 | OOS +9.6..+17.0 | +14.2 [+7.0,+21.5] | 3.81 | +11.1 | **SURVIVES** (WF OOS CI spans 0) |
| 18 | USDJPY / BOJ | 25/15/15 | +2.5 [-0.3,+5.3] | +0.9 [-3.1,+4.9] | 0.46 | +3.2 [-5.0,+11.4] | **FAILS** — no edge |
| 19 | AUDUSD / NFP | 40/15/25 | (r11 combined) | -1.8 [-7.5,+3.8] | -0.59 | +5.6 (N=6) | **FAILS** |
| 20 | AUDUSD / CPI | 40/15/25 | (r11 combined) | -2.2 [-7.6,+2.9] | -0.81 | -4.2 | **FAILS** |
| 21 | AUDUSD / FOMC | 40/15/25 | (r11 combined) | +4.3 [-1.2,+9.3] | 1.74 | -0.3 | **FAILS** (CI spans 0) |
| 22 | AUDUSD / PPI | 40/15/25 | (r11 combined) | -10.4 [-16.3,-4.2] | -3.50 | -14.6 | **FAILS** (significantly negative) |
| 23 | AUDUSD / GDP | 40/15/25 | (r11 combined) | -0.2 [-6.0,+5.4] | 0.03 | -0.9 | **FAILS** |
| 24 | AUDUSD / PCE | 40/15/25 | (r11 combined) | -2.7 [-9.0,+3.5] | -0.80 | -1.3 | **FAILS** |
| 25 | AUDUSD / RBA | 40/70/30 | +11.6 [-0.9,+25.6] | +3.3 [-5.6,+12.5] | 0.72 | +5.6 (N=2) | **FAILS** (CI spans 0) |
| 26 | AUDUSD / AU CPI | 40/70/30 | +19.2 [+8.1,+32.0] | +4.2 [-13.4,+14.9] | 2.76 | (N=1) | **FAILS** (CI spans 0, N=5) |
| 27 | AUDUSD / AU Empl. | 40/70/30 | +17.2 [+3.2,+31.9] | +1.4 [-6.1,+9.1] | 0.34 | -6.3 (N=2) | **FAILS** (CI spans 0) |

---

## USDZAR — detail (mc_event_split, clean rerun)

Configured 50/70/10, spread 25 pips. Walk-forward = grid-search train
2020-2024, evaluate train-best on 2025-2026 (same methodology as reports
05/08/09).

| Event | NEW E[P&L] | 95% CI | WR | Sharpe | N | WF train-best | WF OOS | Cfg-params OOS |
|-------|-----------|--------|----|--------|---|---------------|--------|-----------------|
| NFP | +9.9 | [+4.6, +15.6] | 24.8% | 3.49 | 153 | 40/70/10 | +18.9 | +15.1 |
| CPI | +15.2 | [+9.0, +21.3] | 31.5% | 4.86 | 143 | 40/65/10 | +5.0 | +7.0 |
| FOMC | +23.5 | [+15.3, +31.6] | 41.8% | 5.87 | 98 | 50/70/10 | +13.3 | +13.3 |
| PPI | +14.8 | [+8.8, +20.9] | 31.0% | 4.80 | 145 | 50/70/10 | +4.5 | +4.5 |
| GDP | +17.0 | [+10.8, +23.2] | 33.8% | 5.35 | 142 | 50/65/10 | +12.5 | +14.0 |
| PCE (not in prod) | +13.4 | [+7.7, +19.7] | 29.3% | 4.33 | 140 | 25/40/10 | -2.2 | **+19.3** |

Optimal params per event type all cluster around 40-50 / 65-70 / 10 — the
unified 50/70/10 production setting remains reasonable for every event type.

Note on PCE: it was excluded from USDZAR production because the old
walk-forward failed (OOS -0.7). On corrected data the train-optimal WF still
fails (-2.2) but the *configured-params* OOS is +19.3 [+6.0, +32.7] — the WF
failure is a param-selection artifact (train picks tight 25/40/10, which
doesn't generalize; 50/70/10 does). Re-enabling USDZAR/PCE is worth
considering — user decision.

## USDTRY — detail (mc_event_split + mc_non_us + fixed-param evals)

Configured 50/70/10 (US events), 20/60/10 (TCMB), spread 30 pips.

| Event | NEW E[P&L] | 95% CI | WR | Sharpe | N | WF train-best | WF OOS | Cfg-params OOS |
|-------|-----------|--------|----|--------|---|---------------|--------|-----------------|
| NFP | +12.3 | [+6.3, +18.8] | 28.5% | 3.80 | 123 | 40/65/10 | +12.8 | +10.4 |
| CPI | +16.9 | [+10.7, +23.8] | 33.6% | 4.81 | 116 | 40/70/10 | +7.4 | +7.4 |
| FOMC | +18.0 | [+10.2, +25.9] | 35.9% | 4.52 | 92 | 50/70/10 | +30.0 | +30.0 |
| PPI | +16.2 | [+9.1, +23.4] | 33.3% | 4.34 | 102 | 25/60/10 | -3.6 | **+17.0** |
| GDP | +9.8 | [+3.0, +16.7] | 24.8% | 2.87 | 105 | 40/70/10 | +10.0 | +15.3 |
| PCE | +8.0 | [+2.3, +14.5] | 22.5% | 2.48 | 111 | 30/65/10 | +13.9 | +12.2 |
| TCMB @ 20/60/10 | +9.0 | [+3.7, +14.5] | 27.6% | 3.20 | 123 | 30/65/10 | +8.8 | +6.5 |
| Unemp. Claims @ 50/70/10 | +9.8 | [+6.8, +13.1] | 24.9% | 6.11 | 461 | — | — | +9.0 |
| ISM PMI @ 50/70/10 | +9.6 | [+3.8, +16.2] | 24.5% | 2.89 | 110 | — | — | +3.3 |
| Retail Sales @ 50/70/10 | +14.2 | [+7.0, +21.5] | 30.3% | 3.81 | 99 | — | — | +11.1 |

USDTRY PPI's WF "failure" (-3.6) is again a train-optimal artifact: the
configured 50/70/10 params deliver +17.0 [+0.1, +33.8] OOS.

TCMB: full-sample grid optimum moved from 20/60/10 (old) to 35/70/10
(E=+13.1 [+7.2, +19.8], Sharpe 3.96). Configured 20/60/10 still passes
(+9.0 [+3.7, +14.5]). Optionally update the TCMB event override to 35/70/10 —
user decision.

### Remaining US events — grid + walk-forward detail (report-12 methodology)

Spread 50 (report 12's default for USDTRY), WF split 2020-2023 / 2024-2026
(matching report 12). Full 540-cell grids; top cells re-ranked by bootstrap
CI-low. (The stock `mc_remaining_us.py` rerun was killed by the environment
mid-run twice; these grids reproduce its methodology in a slimmer harness —
see caveats.)

| Event | Grid best | FULL E / CI | WF train-best | WF OOS E / CI | Cfg 50/70/10 @ sp50 | Best cell @ spread 30 / 80 |
|-------|-----------|-------------|----------------|----------------|----------------------|------------------------------|
| Unemp. Claims | 45/70/10 | +10.4 [+7.2, +13.6] | 45/70/10 | **+11.4 [+5.9, +16.8]** | +10.1 [+6.9, +13.4] | +8.9 / +11.0 (CI>0 both) |
| ISM PMI | 15/45/10 | +11.5 [+7.0, +16.6] | 35/65/10 | +2.2 [-4.8, +10.9] | +10.4 [+4.3, +17.2] | +8.1 / +6.3 (CI>0 both) |
| Retail Sales | 35/70/10 | +14.7 [+7.7, +21.7] | 35/70/15 | +9.1 [-2.7, +21.8] | +15.0 [+7.5, +22.5] | +12.2 / +15.0 (CI>0 both) |

Unemployment Claims is the strongest (weekly N=456, OOS CI entirely above
zero, robust across spread 30-80). ISM and Retail Sales pass full-sample at
all spreads but their WF OOS CIs span zero — weaker than report 12 claimed,
though OOS point estimates remain positive. Given the ambient-volatility
finding, all three are consistent with "USDTRY vol harvesting works on any
day" rather than event-specific edges.

## USDJPY / BOJ — FAILS on corrected data

Configured 25/15/15, spread 2.0:

- Full sample: E[P&L]=+0.9, CI=[-3.1, +4.9], WR 52.0%, Sharpe 0.46, N=50
- OOS 2025-26: +3.2 [-5.0, +11.4], N=11

mc_non_us grid (BOJ + Japan CPI): full-sample optimum 50/60/10 gives +8.9
[+0.8, +17.8] (N=47, barely clears zero) but **walk-forward fails**:
train-best 30/70/25 → OOS **-2.0** (Sharpe -0.60, N=23).

The old report 06 verdict was already borderline ("CI barely touches zero,
paper-trade, re-evaluate end of 2026"). On corrected data there is no
detectable edge at configured params and no walk-forward-valid alternative.
**Recommendation: remove USDJPY/BOJ from production.**

## AUDUSD — FAILS at all configured params

Configured: US events 40/15/25, AU events 40/70/30, spread 1.5.

Every one of the 9 configured combos fails on corrected data (see verdict
table rows 19-27). AUDUSD/PPI is *significantly negative* (-10.4
[-16.3, -4.2]) — actively losing money at configured params.

### Fresh grids (report-11 methodology: US / Australia / Combined, spread 1.5, WF 2020-2023 / 2024-2026)

| Source | Grid best | FULL E / CI | WF train-best | WF OOS E / CI | Spread sweep 1.0-4.0 (best cell) |
|--------|-----------|-------------|----------------|----------------|-----------------------------------|
| US (6 events, 436) | 50/65/10 | +5.5 [+1.0, +10.3] | 50/65/20 | +3.4 [-5.4, +12.8] | +5.3..+5.9, CI>0 all spreads |
| Australia (3 events, 173) | 50/15/15 | +6.1 [+1.5, +10.2] | 45/20/10 | **-1.4 [-10.0, +10.6]** | +5.3..+6.8, CI>0 all spreads |
| Combined (609) | 50/65/20 | +5.8 [+1.3, +10.6] | 50/65/20 | +2.9 [-5.5, +11.7] | +5.5..+7.1, CI>0 all spreads |

No source produces a walk-forward-valid optimum: Australia OOS is negative;
US and Combined OOS point estimates are positive but their CIs span zero
(OOS Sharpe 0.65 / 0.59, N=27-29). Report 11's "Combined passes at spread
>=3.0" does not reproduce on corrected data — and its configured parameters
(40/15/25 US, 40/70/30 AU) fail outright at every event source. New optima
cluster at 50/65/20-ish with E[P&L] ~+5-7 — less than half the per-trade
expectancy of USDZAR/USDTRY, on a pair whose ambient volatility (unlike the
exotics) does not carry the bracket.

**Recommendation: remove AUDUSD from production.** No passing cell at
configured params; no walk-forward-valid new optimum found ("no passing
cell" in spec terms).

---

## Disabled pairs — quick check (old-report optimal params, corrected data)

Fixed-param evaluation only (no fresh grids), per spec. FULL = 2020-2026,
OOS = 2025-2026.

| Pair / events | Old params | NEW FULL E / CI | NEW OOS E / CI | Old verdict | Holds? |
|---------------|-----------|------------------|----------------|-------------|--------|
| GBPUSD / NFP+CPI+FOMC | 35/15/25 | +1.7 [-0.8, +4.1] | +4.6 [-1.3, +10.0] | avoid | **HOLDS** |
| USDCAD / NFP+CPI+FOMC | 10/15/15 | +1.1 [-0.5, +2.7] | +1.3 [-1.9, +4.5] | avoid | **HOLDS** |
| GBPJPY / NFP+CPI+FOMC | 10/15/10 | -2.4 [-3.5, -1.2] | -1.2 [-3.8, +1.5] | avoid | **HOLDS** |
| USDCAD / Canada events | 10/15/10 (new grid) | +2.2 [+0.9, +3.6] | WF OOS **-3.7** | avoid | **HOLDS** (WF fails) |
| EURUSD / 6 US events | 10/20/10 | **+2.3 [+1.2, +3.4]**, Sh 4.14 | **+2.6 [+0.3, +5.1]** | avoid | **QUESTIONABLE** — now passes both full-sample and OOS |
| CADJPY / Canada events | 45/20/15 | -3.4 [-4.9, -1.8] | -3.3 [-6.4, -0.2] | avoid | **HOLDS** |
| CADJPY / Japan events | 50/50/10 | **+8.5 [+5.3, +11.9]**, Sh 4.94 | **+8.4 [+1.6, +15.2]** | avoid | **QUESTIONABLE** — now passes both full-sample and OOS |
| CADJPY / US events | 50/15/30 | -14.8 [-16.2, -13.3] | -14.5 | avoid | **HOLDS** |
| EURCAD / Canada events | 25/15/15 | +0.4 [-1.5, +2.3] | -0.0 | avoid | **HOLDS** |
| EURCAD / US events | 10/15/20 | -0.6 [-1.9, +0.7] | +0.1 | avoid | **HOLDS** |
| GBPCAD / Canada events | 10/15/10 | +0.8 [-0.5, +2.1] | -0.9 | avoid | **HOLDS** |
| GBPCAD / US events | 15/15/10 | -1.1 [-2.0, -0.1] | -0.6 | avoid | **HOLDS** |

**EURUSD and CADJPY/Japan flags**: these are *quick checks at old-report
params*, evaluated once — no grid search, no multiple-comparison correction,
no spread sensitivity. E[P&L] per trade is small (EURUSD +2.3 pips vs 1.5-pip
spread assumption; sensitive to spread estimate error). Do NOT enable either
without a dedicated full analysis (grid + walk-forward + spread sweep +
Bonferroni). Old "avoid" verdicts were computed on shifted data, so they carry
no evidentiary weight either way.

---

## Production recommendation

Justified by corrected-data analysis (all at current configured params).
Standing caveat from the control experiment: these PASSes certify
ambient-volatility profitability on event days, not a news-reaction edge.
The current config is **not invalidated economically** — event days perform
like any other day and OOS holds up — **but its rationale is wrong** (it is
a vol-harvesting bracket, not a news straddle). The proper follow-up is a
dedicated "ambient bracket strategy" analysis (realistic off-event spreads,
trade frequency, session effects); this report does NOT recommend expanding
trading hours beyond the tested event schedule:

- **KEEP** `USDZAR` in `trading.instruments`; keep 50/70/10 override; keep all
  5 US event sources (NFP, CPI, FOMC, PPI, GDP) + SARB + SA CPI in
  `config/events.yaml`.
- **KEEP** `USDTRY` in `trading.instruments`; keep 50/70/10 override; keep all
  9 US event sources + TCMB. TCMB override 20/60/10 still valid; 35/70/10 is
  the new full-sample optimum (optional change).
- **REMOVE** `USDJPY` from `trading.instruments` and BOJ Policy Rate from
  `config/events.yaml` — no edge at configured params, walk-forward fails.
- **REMOVE** `AUDUSD` from `trading.instruments` and RBA/AU CPI/AU
  Employment + AUDUSD from US event pair lists — all 9 combos fail at
  configured params; PPI actively negative.
- **OPTIONAL / user decision**: consider re-enabling USDZAR/PCE (configured
  params OOS +19.3 [+6.0, +32.7]; old exclusion was based on a train-optimal
  WF artifact).
- **DO NOT** enable EURUSD or CADJPY without a dedicated follow-up analysis
  (see flags above).

Per the Analysis-Driven Configuration rule, none of these changes have been
applied to `config/settings.yaml` — they await user confirmation.

---

## Methodology notes & caveats

1. **Fixed-param OOS vs train-optimal WF**: the stock scripts' walk-forward
   picks train-period-optimal params and evaluates them OOS. When the
   train-optimal cell differs from the production cell, WF results describe
   the wrong strategy. Both numbers are reported; the "Cfg-params OOS" column
   is the production-relevant one.
2. **Loader fix changes all comparisons**: old reports 04-12 ran with the
   date-collision loader on smaller CSVs (fewer event types → fewer
   collisions). Old numbers are therefore not exactly reproducible even on old
   data; treat OLD columns as approximate context.
3. **Spread assumptions unchanged** from prior reports (USDZAR 25, USDTRY 30,
   USDJPY 2.0, AUDUSD 1.5, majors 1.5-4.0 pips event-time half-spread).
4. **Bootstrap**: 10,000 resamples, 95% CI, no Bonferroni correction on
   single-combo evaluations (matches original per-combo methodology).
5. **AU CPI / RBA sample sizes are tiny** at distance 40 (N=5-25 triggered
   trades) — the AUDUSD AU-event verdicts are driven as much by lack of
   evidence as by negative evidence.
6. **5-min data not re-downloaded** — no current MC script consumes it.
7. Unemployment Claims windows for 2025-12-25 and 2026-01-01 are genuinely
   absent from Dukascopy (holiday weeks, "No data") — 2 windows per pair
   missing, immaterial.
8. **Stock-script substitution**: `mc_remaining_us.py` and
   `mc_audusd_explore.py` reruns were killed by the environment twice
   (~55 min in, no output). Their grids were reproduced with
   `scripts/mc_grids_fast.py` — same 540-cell grid, same CI-low ranking
   criterion, same 2020-2023/2024-2026 WF split; the only deviation is that
   cells are pre-ranked by a normal-approximation CI-low and only the top 25
   are re-ranked with the full 10k bootstrap (the winner is bootstrap-ranked,
   so the reported optimum is bootstrap-validated). Consequently
   `scripts/data/MC_REMAINING_US_REPORT.md` and `MC_AUDUSD_EXPLORE_REPORT.md`
   still contain the STALE June (shifted-data) text — superseded by this
   report; raw new grid output is in
   `scripts/data/revalidation_grids_usdtry.txt` / `revalidation_grids_audusd.txt`.
9. **`scripts/data/MC_NON_US_REPORT.md` and `event_split_results.json` were
   regenerated** by the clean reruns. The auto-generated "Recommendation"
   text in MC_NON_US_REPORT.md (e.g. "USDCAD recommended") applies naive
   CI-only thresholds and is superseded by this report's verdicts (USDCAD
   fails walk-forward: OOS -3.7).
10. **Evidence files**: shifted CSVs in `scripts/data/dukascopy_SHIFTED_BAD/`;
    pre-fix result JSON/reports in `scripts/data/OLD_RESULTS_SHIFTED_BAD/`;
    configured-param evals in `scripts/data/revalidation_fixed_params.txt`
    (script `scripts/mc_fixed_params_check.py`); ambient control output in
    `scripts/data/revalidation_ambient_control.txt`
    (script `scripts/mc_ambient_control.py`; Run D data in
    `scripts/data/dukascopy/{PAIR}_ambient_1min.csv`).
