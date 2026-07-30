# 17 — Ambient Bracket Strategy Analysis (USDZAR / USDTRY)

**Date**: July 2026
**Status**: REVIEWED & APPROVED (Fable, 2026-07-29) — cost model verified
independently (see reviewer addendum at end). No config changes made. No src/ changes.
**Spec**: `docs/research/specs/17-ambient-bracket-spec.md`
**Builds on**: `docs/research/16-mc-revalidation.md` (Run D ambient control)
**Scripts**:
`scripts/mc_spread_profile.py` (Phase A — Dukascopy tick spread profile + calibration),
`scripts/mc_ambient_bracket.py` (Phases B/C — ambient/event sim, grid, portfolio),
`scripts/sample_ib_spreads.py` (live IDEALPRO sampler, created + smoke-tested once).

---

## TL;DR / Production recommendation

**Do NOT build the ambient (trade-daily) bracket variant.** The analysis
does not clear the pass bar under any honest cost model, and — more
importantly — it exposed that **the load-bearing input the whole idea
rests on (the spread) cannot be measured from the data we have, and the
one 6.5-year source we do have (Dukascopy exotic tick spreads) is a
retail-feed artifact 3–15× wider than the real IDEALPRO spread the bot
actually pays.**

The clean, valuable answer the spec asked for: **measured spreads kill the
ambient edge.** Specifically —

1. In report 16's own bracket cost model, spread only *gates which trades
   trigger*; it is never deducted from realized P&L. So "passing at p75/p95
   measured spreads" in that model is **hollow** — E[P&L]/trade actually
   *rises* as the spread widens (wider trigger selects stronger breakouts).
2. Under an honest **one-full-spread-per-round-trip** cost (correct for
   bid-based backtest data), the ambient design is **deeply negative at
   Dukascopy measured spreads** (−74 to −259 pips/trade) and **still
   negative-to-marginal at the real IDEALPRO spread** (USDZAR −11, USDTRY
   −1.3 pips/trade; walk-forward OOS USDZAR −13, USDTRY +2.4 with a CI that
   spans zero).
3. The pair whose economics are not hopeless is **USDTRY**, and only
   because its true IDEALPRO spread is genuinely tight (~6–12 pips), and
   only in the two liquid sessions (09:00 / 14:00 UTC) — its overnight
   spread blows out to 130–300 pips. USDZAR's ~24-pip spread is larger than
   the gross per-trade edge of a 50/70/10 bracket, so it cannot profit
   from trading daily.

Keep the current **event-scheduled** configuration exactly as report 16
left it. This report does **not** recommend expanding trading hours.

**Standing caveat with teeth**: the honest full-spread cost model also
turns report 16's *event* numbers negative at real spreads (USDZAR event
−6.7, USDTRY event −1.5 pips/trade). That is because reports 04–16 never
charged the spread as a P&L deduction — only as a trigger shift. Whether
the live event strategy truly clears its spread is a separate question
that needs the live sampler's data; it is out of scope here, but the same
scrutiny applies. Do not read report 16's "+15 pips/trade on event days"
as net of costs — it is gross.

---

## Phase A — Measured spread profile (Dukascopy tick data)

### Method

- Tick data (`dukascopy_python`, `INTERVAL_TICK`, both bid+ask in one call),
  fetched with **tz-aware UTC** datetimes only (the report-16 catastrophic
  naive-datetime bug is not reintroduced; verified in `mc_spread_profile.py`).
- **200 sampled weekdays/pair**, 2020–2026, holiday weeks excluded: report
  16's 160 Run-D non-event days + 40 non-overlapping extension days (seed 43).
- Four **30-min probe windows/day** at anchors **03:00 / 09:00 / 14:00 /
  20:00 UTC** (Asia / early London / London–NY overlap / NY-only).
- Spread per tick = (askPrice − bidPrice) / pip. **All four anchors were
  downloaded** (the 20:00 anchor was NOT skipped). 55 windows returned no
  ticks (genuine USDTRY overnight illiquidity — marker files written).
- **Total tick data downloaded: 184 MB** (cached under
  `scripts/data/_cache/ticks/`). Full-day 1-min bars for Phase B: 32 MB
  (`scripts/data/_cache/ambient1m/`).

### Spread profile — overall by anchor (pips)

| Pair | Anchor (UTC) | median | p75 | p95 | days |
|------|--------------|--------|-----|-----|------|
| USDZAR | 03:00 | 102.2 | 130.7 | 186.6 | 200 |
| USDZAR | 09:00 | 57.9 | 67.3 | 87.5 | 200 |
| USDZAR | 14:00 | 59.0 | 68.4 | 101.4 | 200 |
| USDZAR | 20:00 | 77.9 | 89.8 | 137.4 | 200 |
| USDTRY | 03:00 | 168.2 | 259.7 | 478.6 | 160 |
| USDTRY | 09:00 | 48.8 | 77.4 | 194.3 | 200 |
| USDTRY | 14:00 | 48.1 | 89.5 | 220.9 | 200 |
| USDTRY | 20:00 | 136.1 | 304.7 | 480.2 | 185 |

**Session structure**: for both pairs the two liquid European/US sessions
(09:00, 14:00) are 2–4× tighter than the Asia (03:00) and NY-close (20:00)
windows. Any ambient strategy that trades all four anchors is trading its
worst spreads half the time.

### Yearly trend & regime shifts

- **USDZAR is tightening**: 03:00 median 129 (2020) → 71 (2026); 14:00
  median 71 → 45. Structural liquidity improvement over the window.
- **USDTRY widened sharply post-2023 election / CBRT policy pivot**
  (flagged split 2023-06-01): pooled median 33.7 → 92.8 pips, p75 78.8 →
  168.9. The 03:00/14:00 medians confirm it (14:00: 21→98 pips into 2022,
  still 56–94 in 2024–26). TRY spread is regime-dependent and elevated
  versus its pre-2022 self.

### Calibration — the headline finding

| Pair | Journal mean (n) | Live IDEALPRO smoke | Report 16 assumed | Dukascopy p75 (avg anchor) | Dukascopy ÷ real |
|------|------------------|---------------------|-------------------|----------------------------|------------------|
| USDZAR | **23.5** (n=5) | **24.9** | 25.0 | 89.0 | ~3.6× |
| USDTRY | **12.1** (n=12) | **5.9** | 30.0 | 182.8 | ~8–15× |

- The trade journal's real IDEALPRO `entry_spread_pips` and a one-shot live
  snapshot (`sample_ib_spreads.py`, clientId=9, port 7497, read-only) both
  land **right on report 16's USDZAR assumption (25)** and **well below its
  USDTRY assumption (30)**. Report 16's flat 25/30 was well-calibrated
  (USDZAR) to conservative (USDTRY) **for the IBKR venue**.
- **Dukascopy exotic tick spreads are NOT the spread the bot trades.**
  Dukascopy's retail feed marks exotics 3.6× (ZAR) to 8–15× (TRY) wider
  than IDEALPRO. Using Dukascopy spreads as "the measured cost" would model
  a broker the user does not and cannot trade with (OANDA-class retail
  markup; recall OANDA is unavailable in Alberta anyway).
- **Consequence for the spec**: "use measured spreads instead of assumed"
  presumed Dukascopy ticks would be the realistic measure. They are not.
  The realistic measure is the IDEALPRO spread, and the only trustworthy
  IDEALPRO data is ~17 journal fills from a single month plus one live
  snapshot — far too little to characterize a daily all-session strategy.
  That is why `sample_ib_spreads.py` exists (see Phase A.4).

### Phase A.4 — live IDEALPRO sampler

`scripts/sample_ib_spreads.py`: standalone `ib_async` client, **clientId=9
only** (never 1 — that is the live bot), read-only snapshots, appends to
`scripts/data/ib_spread_samples.csv`, disconnects, exits. Smoke-tested once
against the running paper TWS (port 7497): USDZAR 24.9 pips, USDTRY 5.9 pips
appended successfully. Intended to run hourly on weekdays (cron stanza in
the script docstring — **not installed automatically**) to build the
multi-session IDEALPRO spread series this analysis lacked.

---

## Phase B — Ambient vs event under measured spreads (50/70/10)

`simulate_bracket()` was verified **bit-identical to report 16's
`simulate_straddle()`** on 315 real windows (`--selftest`), using the same
`[anchor−2h, anchor+4h]` window and mechanics as report 16 Run D.

Two cost conventions are reported:

- **[r16]** = report 16's model. The spread shifts the entry-trigger level
  (`buy_stop = mid + distance + spread/2`) but TP/SL are measured *from that
  entry*, so realized P&L is exactly +tp / −sl / timeout and **never
  reflects the spread**. Empirically E[P&L] *rises* with spread (wider
  trigger ⇒ fewer, stronger breakouts; N falls). This model charges **no net
  transaction cost**.
- **[full]** = [r16] minus **one full spread per round trip**, the standard
  conservative convention for bid-based backtest data (you buy at the ask,
  the trigger was measured on the bid, so realized P&L overstates by one
  spread). This is not double-counting the spread/2 trigger shift — that
  shift is a selection effect, the full spread is the transaction cost.

### Ambient (50/70/10, all anchors, 2020–2026)

| Pair | Spread source | [r16] E / CI | [full] E / CI | N |
|------|---------------|--------------|---------------|---|
| USDZAR | flat 25 (r16) | +12.7 [+10.9,+14.6] | **−12.3 [−14.1,−10.4]** | 1437 |
| USDZAR | IDEALPRO 23.5 | +12.4 [+10.6,+14.3] | **−11.1 [−12.9,−9.2]** | 1441 |
| USDZAR | Dukascopy p75 | +13.8 [+11.8,+15.7] | **−73.9 [−76.4,−71.5]** | 1348 |
| USDZAR | Dukascopy p95 | +14.8 [+12.8,+16.8] | **−109.2 [−113.0,−105.5]** | 1296 |
| USDTRY | flat 30 (r16) | +11.2 [+9.1,+13.3] | **−18.8 [−20.9,−16.7]** | 1055 |
| USDTRY | IDEALPRO 12.1 | +10.8 [+8.8,+13.0] | **−1.3 [−3.3,+0.9]** | 1103 |
| USDTRY | Dukascopy p75 | +15.0 [+12.3,+17.8] | **−135.9 [−145.0,−126.9]** | 746 |
| USDTRY | Dukascopy p95 | +15.7 [+12.8,+18.7] | **−259.0 [−276.2,−242.3]** | 597 |

### Event windows (report 16 Run C scope, identical cost model)

| Pair | Spread source | [r16] E / CI | [full] E / CI | N |
|------|---------------|--------------|---------------|---|
| USDZAR | IDEALPRO 23.5 | +16.8 [+14.3,+19.2] | **−6.7 [−9.2,−4.3]** | 905 |
| USDZAR | Dukascopy p75 | +17.5 [+15.1,+20.1] | **−53.2 [−55.7,−50.7]** | 889 |
| USDTRY | IDEALPRO 12.1 | +10.6 [+8.8,+12.4] | **−1.5 [−3.3,+0.3]** | 1488 |
| USDTRY | Dukascopy p75 | +12.4 [+10.4,+14.4] | **−84.1 [−88.3,−79.9]** | 1258 |

**Event vs ambient**: under the identical cost model they are
indistinguishable (event ~+2–3 pips over ambient in [r16], CIs overlap) —
confirming report 16's core finding that this is ambient volatility
harvesting, not a news-reaction edge. The event schedule adds no cost-
clearing advantage; it just trades less often.

### Parameter grid + walk-forward (train 2020–2024, test 2025–2026)

18-cell grid (distance {35,50,65} × TP {50,70,90} × SL {10,15}) at
Dukascopy p75, ranked by bootstrap CI-low. Because [r16] is spread-
insensitive, the grid optimum drifts to the widest cell (**65/90/10** for
both pairs — more selective trigger, bigger conditional win). Walk-forward
OOS:

| Pair | WF OOS 50/70/10 [r16] @p75 | @p95 | [full] @p75 | [full] @p95 | [full] @ IDEALPRO |
|------|---------------------------|------|-------------|-------------|-------------------|
| USDZAR | +12.0 [+8.2,+15.8] | +11.5 [+7.8,+15.3] | −64.3 | −93.0 | **−13.1 [−16.6,−9.3]** |
| USDTRY | +14.5 [+8.3,+21.1] | +16.8 [+9.8,+24.2] | −157.7 | −237.1 | **+2.4 [−2.2,+7.2]** |

50/70/10 stays a reasonable cell in the [r16] model (no OOS collapse), so
the *geometry* is fine; the strategy dies on **cost**, not on parameter
overfit.

---

## Phase C — Portfolio design

One bracket per pair per anchor per day, no concurrent same-pair trades
(overlap guard on exit time), ~4.5h max hold (report-16 window). Frequency
is high because it trades daily across up to 4 anchors. Metrics shown for
[r16] (no cost) and [full] (−1 spread) at Dukascopy p75; **the [full]
column is the decision-relevant one.**

| Design | trades/yr | [r16] E/trade | [full] E/trade | [r16] E/yr | [full] E/yr | annSharpe (daily, r16) | DD95 [r16]/[full] |
|--------|-----------|---------------|----------------|-----------|-------------|------------------------|--------------------|
| D1 both, 4 anchors | ~1552 | +14.2 | **−96.0** | +22,076 | −148,959 | 13.5 | 220 / 210,260 |
| D2 both, 14:00 only | ~454 | +13.1 | **−62.5** | +5,929 | −28,377 | 7.5 | 240 / 38,822 |
| D3 both, 09:00+14:00 | ~875 | +13.5 | **−58.8** | +11,788 | −51,483 | 10.8 | 240 / 71,160 |
| D4 USDZAR, 4 anchors | ~1698 | +13.8 | **−73.9** | +23,389 | −125,536 | 14.9 | 230 / 102,520 |
| D5 USDTRY, 4 anchors | ~964 | +15.0 | **−135.9** | +14,503 | −130,969 | 11.2 | 200 / 109,831 |

At Dukascopy spreads every design is catastrophic under [full]. The [r16]
numbers look spectacular (annualized daily Sharpe 7–15, tens of thousands
of pips/yr) precisely *because* [r16] charges no cost — do not be seduced by
them. Pair daily-P&L correlation is low (**r = 0.22**, n=55 common days),
so diversification is real but irrelevant if each leg is unprofitable.

### Vol-regime terciles (prior-day 5-day realized vol; ATR proxy)

Daily Dukascopy CSVs carry close only, so "prior-day ATR" is the 5-day
rolling std of daily log returns ending the prior day.

| Pair | Regime | [r16] E / CI | [full] E / CI (Duka p75) |
|------|--------|--------------|--------------------------|
| USDZAR | low | +10.7 [+7.5,+13.9] | −75.3 |
| USDZAR | mid | +12.2 [+8.9,+15.5] | −76.1 |
| USDZAR | high | **+18.3 [+14.8,+21.8]** | −70.5 |
| USDTRY | low | +13.6 [+7.9,+19.7] | −172.5 |
| USDTRY | mid | +11.8 [+7.5,+16.3] | −146.9 |
| USDTRY | high | **+18.5 [+14.4,+22.6]** | −105.8 |

The gross ([r16]) edge is **concentrated in high-vol regimes** (+18 vs +11
in low-vol) for both pairs — consistent with volatility harvesting. But
high vol also comes with wider spreads, and under [full] even the high-vol
tercile is deeply negative at Dukascopy spreads. A high-vol-only ambient
filter would help gross P&L but does not rescue the cost problem.

### Margin reality (~$4.9K CAD account, 25%-of-AvailableFunds/order cap)

Exotic margin rates (USDTRY ~30%, USDZAR ~10%) and the `max_margin_pct_
per_trade: 25.0` cap mean a single risk-sized straddle already consumes
most of one order's margin budget. With `max_concurrent_positions: 4` and
each straddle holding two legs, **the account cannot run both pairs across
4 daily anchors concurrently** — a daily ambient schedule (D1: ~6
placements/day, up to 4 legs open) would routinely hit the margin cap and
have orders scaled down or rejected (Error 201). Practical budget: ~1–2
concurrent straddle legs. The high trades/yr counts in the table above are
therefore **not simultaneously executable** at this account size; the
ambient design is also **capacity-constrained**, independent of the cost
verdict.

---

## Pass bar (from spec) and verdict

> A design point passes only if **95% CI > 0 at p75 measured spreads AND
> walk-forward OOS positive AND survives p95 spread stress.**

| Reading of "measured spread" | USDZAR | USDTRY |
|------------------------------|--------|--------|
| Dukascopy p75/p95, [r16] model (literal) | passes hollowly | passes hollowly |
| Dukascopy p75/p95, [full] honest cost | **FAIL** (−74/−109) | **FAIL** (−136/−259) |
| IDEALPRO real spread, [full] honest cost | **FAIL** (−11; OOS −13) | **FAIL** (−1.3; OOS +2.4, CI spans 0) |

- The only reading that "passes" is the one where the cost model charges
  nothing (report 16's own model). That certifies the *bracket geometry
  clears no cost*, which is not a tradeable claim.
- Every reading that charges a real transaction cost **fails the bar** — at
  Dukascopy spreads by a mile, and at the real IDEALPRO spread still
  negative (USDZAR) or a CI that spans zero (USDTRY OOS +2.4 [−2.2,+7.2]).

**No ambient design point passes the full bar.**

---

## Production recommendation

1. **Do not build the ambient / trade-daily bracket variant.** It fails the
   pass bar under every honest cost model. USDZAR's real spread (~24 pips)
   exceeds the gross per-trade edge of a 50/70/10 bracket; it cannot profit
   from trading daily. USDTRY is the only pair with a plausible positive
   net expectancy, and only in its two liquid sessions and only if its tight
   ~6–12-pip IDEALPRO spread persists (its overnight spread is 130–300 pips).
2. **Keep the current event-scheduled config unchanged** (report 16 scope).
   This report changes no `config/settings.yaml` or `config/events.yaml`.
3. **Run `sample_ib_spreads.py` on the suggested weekday-hourly cron** for a
   few months before *any* ambient work is reconsidered. The single most
   important missing input is a real multi-session IDEALPRO spread
   distribution; Dukascopy cannot supply it and the journal is too small.
4. **Flag for a future report (out of scope here)**: the honest full-spread
   cost turns report 16's *event* numbers negative at real spreads too,
   because reports 04–16 never deducted the spread from realized P&L. The
   live event strategy's true net-of-cost profitability deserves the same
   audit. Report 16's "+10–15 pips/trade" figures are **gross, not net.**

---

## Methodology notes & caveats

1. **Bid-only tick data.** Dukascopy `OFFER_SIDE_BID` returns both bid and
   ask columns, so spreads are true measured bid/ask — not a one-sided
   proxy. Bars used for the P&L sim are bid bars (as in all reports 04–16),
   which is exactly why the [full] one-full-spread deduction is the correct
   cost correction.
2. **Dukascopy is a retail feed.** Its exotic spreads do not represent
   IDEALPRO and are used here only to (a) characterize session/regime
   *structure* and (b) run the spec's literal p75/p95 stress. All economic
   verdicts key off the IDEALPRO-calibrated spread.
3. **IDEALPRO calibration sample is small** (5 USDZAR + 12 USDTRY journal
   fills, all July 2026, plus one live snapshot each). The 23.5 / 12.1 / 5.9
   figures are indicative, not distributions. This is the analysis's biggest
   uncertainty and the reason for the sampler.
4. **[r16] vs [full] cost model** is the crux. [r16] reproduces reports
   04–16 exactly (verified). [full] adds the omitted transaction cost. Both
   are shown; [full] at IDEALPRO is the decision criterion.
5. **Bootstrap**: 10,000 resamples, 95% CI, no Bonferroni (single-combo
   evals, matching prior reports). Path max-drawdown from 2,000 resampled
   equity paths.
6. **Vol proxy** is 5-day realized-vol (close-only), not true ATR — daily
   Dukascopy CSVs lack high/low.
7. **Margin analysis** is from documented margin rates and the configured
   25% cap, not a live whatIf sweep (no orders were placed beyond the single
   read-only spread snapshot).
8. **Foreground, resume-safe downloads**: 184 MB ticks + 32 MB 1-min bars,
   fetched in bounded foreground chunks with per-window/per-day caching.
9. **No config or src changes; no commits/pushes.** Evidence:
   `scripts/data/_cache/ticks/`, `scripts/data/_cache/ambient1m/`,
   `scripts/data/ambient_bracket_results.json`,
   `scripts/data/ib_spread_samples.csv`.

---

## Reviewer addendum (Fable, 2026-07-29)

**Cost model verified.** I re-derived the bracket accounting from
`simulate_bracket()` mechanics: bars are bid, entry triggers on the bid but a
real long fills at the ask (bid+spread) while the exit sells at the bid, so
each round trip is overstated by exactly one full spread. The `+spread/2`
trigger shift nets out because TP/SL are measured from the shifted entry.
Deducting one full spread is correct and does **not** double-count. The report's
central methodological finding — reports 04–16 report **gross** P&L, never
deducting the round-trip spread — is sound.

**Live reality check (trade journal, data/forex_bot.db).** The event straddle
strategy has **filled 0 of 30 orders** (16 cancelled, 12 error — the size/margin
rejections resolved over PRs #75/#76/#80, 2 pending). It has never executed a
single fill, so there is **no live realized P&L** to confirm or refute the
backtested edge. Combined with the gross-not-net finding, the honest status of
the flagship strategy is: **its real-world profitability is unproven, and the
backtest edge that justified it may not survive real IDEALPRO spreads.**

**Secondary: journal/broker desync.** The journal holds 3 carry trades marked
open (USDTRY, AUDJPY, USDZAR; opened Jul 6–13) while IB reconcile reports 0
positions. AUDJPY isn't even in the instrument set. Needs a separate
reconciliation pass — not in scope here.

**Follow-ups filed** (todo.md): (1) event-strategy net-of-cost audit — re-run
reports 04–16 with the one-full-spread deduction at measured IDEALPRO spreads;
this is now higher priority than any new strategy candidate. (2) investigate why
straddle orders never fill. (3) carry journal/broker reconciliation.
