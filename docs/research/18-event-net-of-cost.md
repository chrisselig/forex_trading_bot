# 18 — Event-Strategy Net-of-Cost Audit

**Date**: July 2026
**Status**: DRAFT — pending user review. No config or src changes made.
**Spec**: `docs/research/specs/18-event-net-of-cost-spec.md`
**Builds on**: `docs/research/16-mc-revalidation.md` (corrected-data verdicts),
`docs/research/17-ambient-bracket.md` (reviewer addendum — spot check that
flagged this as the top-priority follow-up)
**Script**: `scripts/mc_net_of_cost.py` (new; reuses
`monte_carlo_dukascopy.simulate_straddle` / `bootstrap_metrics` unmodified)

---

## TL;DR / Production recommendation

**Zero of 18 active production combos clear real spread cost. The event
straddle strategy, as currently configured, is not net-of-cost profitable
on either pair over the full 2020-2026 sample, and both pairs are flat-to-
negative walk-forward out-of-sample (2025-2026).** This confirms and
quantifies report 17's reviewer-addendum spot check — it is not a fluke of
that spot check's narrower event scope.

- **USDZAR: net loser, unambiguously.** Pooled across all 8 configured
  event sources at the base-case real spread (24 pips): net E[P&L] =
  **−7.49 pips/trade, 95% CI [−9.78, −5.12]**, entirely
  below zero, N=1,047. OOS 2025-2026 net **−10.76 [−15.08, −6.12]** — the
  loss gets *worse* out of sample, not better. No single event source's net
  CI clears zero. USDZAR loses an estimated **−1,193 net pips/year**
  (≈ **−$8,900 CAD/year** at current margin-capped sizing) against a gross
  headline of +2,631 pips/year (+$19,630 CAD/year) — the entire gross edge
  reported in 04-16 is smaller than the 24-pip round-trip spread charges.
- **USDTRY: not a loser, but not a winner either — a coin flip.** Pooled net
  E[P&L] = **−1.17 [−2.97, +0.65]**, N=1,495 — a CI that straddles zero by a
  hair, essentially indistinguishable from breakeven. OOS 2025-2026 net
  **−3.77 [−7.93, +0.49]** — still spans zero, point estimate negative. One
  individual combo (USDTRY/CPI) clears the full-sample net CI bar
  (+7.15 [+0.37, +14.61]) but **fails its own walk-forward OOS**
  (−4.61 net) — a param/period-selection artifact, not a repeatable edge.
  No USDTRY combo passes both halves of the bar simultaneously.
- **Pass bar (net 95% CI > 0 at base spread AND net WF OOS > 0): 0 of 18
  combos pass.** See the full table below — every row is FAIL.
- **This is the single most important finding this project has produced
  about the flagship strategy.** Reports 04-16 measured a real, statistically
  robust *gross* volatility-harvesting edge (report 16's own conclusion:
  "ambient volatility harvesting, not a news-reaction edge"). This report
  shows that edge is **smaller than the real IDEALPRO bid/ask spread** on
  USDZAR, and **on the same order of magnitude as the spread — indistinguishable
  from zero — on USDTRY**. Combined with report 17's reviewer addendum
  (0 of 30 real order attempts have ever filled), the honest status of the
  event straddle strategy is: **its net-of-cost live profitability is
  unproven and, on this backtest, probably not there for USDZAR and at best
  a coin flip for USDTRY.**
- **No config or src changes made.** This report answers the audit
  question; the decision on whether to keep trading the strategy, pause it,
  or wait for the live spread sampler (`scripts/sample_ib_spreads.py`, see
  report 17) to build a real multi-session IDEALPRO series is the user's
  call.

---

## Cost model (unchanged from report 17)

`simulate_straddle()` shifts the entry-trigger level by `spread/2` (a real
stop order fills at that shifted level) but then measures TP/SL *from that
entry* — so reports 04-16's realized pip P&L never reflects the spread as a
transaction cost, only as a trigger-selection effect. A real fill pays the
full spread on entry (buys at the ask when the bid-based bar triggered) and
the full spread again is embedded on exit (bid-based bars), i.e. the
backtest's realized P&L overstates the true fill by exactly one full
spread per round trip. This report reports both conventions side by side:

- **gross** = report 04-16's convention (spread shifts the trigger only,
  never deducted) — reproduces every number in report 16 exactly.
- **net** = gross minus one full round-trip spread per triggered leg (the
  standard conservative convention for bid-based backtest data; verified
  independently in report 17's reviewer addendum, "does not double-count").

## Spread values

**Real IDEALPRO event-time spreads**, not Dukascopy tick spreads — report
17 proved Dukascopy's exotic-pair tick feed marks spreads 3.6-15x wider than
IDEALPRO (a retail-feed artifact, not the venue the bot trades on).

| Pair | Base case | Sensitivity | Wide-stress | Source |
|------|-----------|-------------|-------------|--------|
| USDZAR | **24.0** | — | 40.0 | Trade journal `entry_spread_pips` mean 23.5 (n=5) + live IDEALPRO snapshot 24.9 |
| USDTRY | **12.0** | 6.0 | 30.0 | Trade journal `entry_spread_pips` mean 12.1 (n=12); live snapshot 5.9 |

**Caveat with teeth (carried forward from report 17)**: this is a **thin
sample** — 5 USDZAR and 12 USDTRY journal fills, all from a single month
(July 2026), plus one live snapshot each. It is the best data available (the
only trustworthy IDEALPRO-venue source), but it is not a distribution across
sessions, volatility regimes, or years. Treat the base-case numbers as
indicative, not precise — which is exactly why the spread-sensitivity
columns below matter.

---

## Per-combo results — gross vs net, at base-case spread

`Verdict` = PASS only if net 95% CI > 0 at base spread **and** net WF OOS
(2025-2026, configured params, not re-optimized) > 0. IS = walk-forward
train period (2020-2024) evaluated at the same fixed configured params, for
context only (not used to select params — none of the params here were
tuned in this report; they are the production values).

### USDZAR (base spread 24 pips)

| Event | N | Gross E / CI | Net E / CI | Net Sharpe | Net WF OOS | Verdict |
|-------|---|--------------|------------|------------|------------|---------|
| NFP | 154 | +9.74 [+4.55,+14.94] | **−14.26 [−19.45,−9.06]** | −5.20 | −8.86 | FAIL |
| CPI | 143 | +16.29 [+10.14,+22.45] | **−7.71 [−13.86,−1.55]** | −2.48 | −14.61 | FAIL |
| FOMC | 99 | +23.13 [+15.86,+31.21] | −0.87 [−8.14,+7.21] | −0.25 | −8.40 | FAIL |
| PPI | 145 | +16.48 [+10.41,+22.55] | **−7.52 [−13.59,−1.45]** | −2.43 | −17.03 | FAIL |
| GDP | 142 | +17.04 [+10.85,+23.24] | **−6.96 [−13.15,−0.76]** | −2.21 | −10.00 | FAIL |
| PCE | 140 | +14.00 [+8.29,+20.29] | **−10.00 [−15.71,−3.71]** | −3.27 | −4.67 | FAIL |
| SARB | 78 | +22.82 [+14.62,+32.05] | −1.18 [−9.38,+8.05] | −0.28 | −12.95 | FAIL |
| SA CPI | 146 | +17.95 [+11.92,+23.97] | **−6.05 [−12.08,−0.03]** | −1.93 | −9.56 | FAIL |
| **POOLED (all 8)** | **1047** | **+16.51 [+14.22,+18.88]** | **−7.49 [−9.78,−5.12]** | **−6.44** | **−10.76** | **FAIL** |

Every single USDZAR event source fails net-of-cost. Five of eight have a
net CI entirely below zero (statistically significant loss, not just
"unproven"). The pooled OOS figure (−10.76) is worse than the pooled
full-sample figure (−7.49) — no sign this improves with more recent data.

### USDTRY (base spread 12 pips; TCMB at 35/70/10, all others 50/70/10)

| Event | N | Gross E / CI | Net E / CI | Net Sharpe | Net WF OOS | Verdict |
|-------|---|--------------|------------|------------|------------|---------|
| NFP | 127 | +14.57 [+8.27,+20.87] | +2.57 [−3.73,+8.87] | +0.75 | +2.35 | FAIL (CI spans 0) |
| CPI | 118 | +19.15 [+12.37,+26.61] | **+7.15 [+0.37,+14.61]** | +2.01 | −4.61 | FAIL (OOS negative) |
| FOMC | 96 | +15.24 [+7.26,+24.05] | +3.24 [−4.74,+12.05] | +0.68 | +12.55 | FAIL (CI spans 0) |
| PPI | 109 | +11.79 [+5.41,+18.65] | −0.21 [−6.59,+6.65] | −0.10 | −8.60 | FAIL |
| GDP | 110 | +9.64 [+3.09,+16.18] | −2.36 [−8.91,+4.18] | −0.79 | −2.00 | FAIL |
| PCE | 115 | +6.00 [+0.43,+12.26] | −6.00 [−11.57,+0.26] | −2.11 | −0.95 | FAIL |
| Unemployment Claims | 482 | +8.00 [+5.10,+11.06] | **−4.00 [−6.90,−0.94]** | −2.66 | −5.81 | FAIL |
| ISM Manufacturing PMI | 111 | +7.37 [+1.53,+13.86] | −4.63 [−10.47,+1.86] | −1.56 | −18.80 | FAIL |
| Retail Sales | 105 | +13.14 [+6.31,+20.12] | +1.14 [−5.69,+8.12] | +0.28 | −1.19 | FAIL (CI spans 0) |
| TCMB (35/70/10) | 122 | +12.50 [+6.15,+18.85] | +0.50 [−5.85,+6.85] | +0.11 | −3.18 | FAIL (CI spans 0) |
| **POOLED (all 10)** | **1495** | **+10.83 [+9.03,+12.65]** | **−1.17 [−2.97,+0.65]** | **−1.30** | **−3.77** | **FAIL** |

Unemployment Claims — the highest-N, statistically strongest gross combo in
report 16 (Sharpe 6.11, N=482, weekly cadence) — is the one USDTRY combo
whose net CI is *significantly* below zero, not just unproven. Its high
trade frequency means it dominates the pair-level pooled loss. CPI is the
only combo to individually clear the full-sample net CI bar, but that result
does not survive walk-forward — it is the train-period-favorable half of the
sample, not a repeatable edge.

---

## Spread sensitivity

| Pair | Spread | Pooled net E[P&L]/trade | Interpretation |
|------|--------|--------------------------|-----------------|
| USDZAR | 24 (base) | −7.49 | fails |
| USDZAR | 40 (wide stress) | more negative at every combo (e.g. NFP −26.47, CPI −23.15) | fails harder |
| USDTRY | 6 (tight sensitivity) | net turns *positive* on most combos (e.g. NFP +11.09, CPI +15.19, UC +2.31) | **the entire USDTRY verdict hinges on which of the two live-snapshot spread readings (5.9 vs 12.1) is representative** |
| USDTRY | 12 (base) | −1.17 pooled, coin flip | marginal |
| USDTRY | 30 (wide stress) | deeply negative on every combo (e.g. NFP −17.66, CPI −13.10, UC −20.15) | fails hard |

USDZAR has no spread regime tested here where it passes — even the
optimistic reading (its own base case, 24 pips) already fails. **USDTRY is
spread-knife-edge**: report 17's two independent IDEALPRO readings for
USDTRY were 12.1 (trade-journal mean, n=12) and 5.9 (single live snapshot).
At 6 pips the strategy looks like a real, if modest, edge on most event
types; at 12 pips it is a wash; at 30 pips (still inside the configured
`max_spread_overrides.USDTRY: 80.0` gate, i.e. a spread the bot would
still accept a trade at) it is a clear loser. **The single most
consequential unknown in this whole audit is which USDTRY spread the bot
actually pays in a representative session** — the sample is far too thin
(n=12 fills, one month) to know.

---

## Per-pair net expectancy (pips/year, CAD/year)

Weighted by each event type's actual triggered-trade frequency in the
2020-01-02 to 2026-07-29 sample (6.57 years), at base-case spread. CAD/year
uses `quote_to_cad = USDCAD / pair_mid` (`src/forex_bot/broker/pricing.py`
`get_quote_to_cad_rate`, the exact conversion the risk manager already uses)
with spot rates from the most recent common Dukascopy daily close
(2026-07-01: USDCAD 1.42186, USDZAR 16.41054, USDTRY 46.68239).

| Pair | Gross pips/yr | Net pips/yr | Units (see caveat) | CAD/pip | Gross CAD/yr | **Net CAD/yr** |
|------|---------------|-------------|---------------------|---------|--------------|----------------|
| USDZAR | +2,631 | **−1,193** | 861,000 | 7.46 | +$19,630 | **−$8,899** |
| USDTRY | +2,463 | **−267** | 2,481,250 | 7.56 | +$18,618 | **−$2,016** |

Per-event breakdown (net pips/year) is in `scripts/data/net_of_cost_results.json`
(`pair_agg.<PAIR>.combo_breakdown`). Highlights: USDZAR's least-bad sources
are FOMC (−13/yr) and SARB (−14/yr) — both low-frequency (8/yr FOMC, ~6/yr
SARB) — while its highest-frequency sources (NFP, CPI monthly) are its
biggest net losers (−334/yr, −168/yr) because trade count amplifies a
negative per-trade expectancy. USDTRY's only net-positive sources are CPI
(+128/yr), NFP (+50/yr), FOMC (+47/yr), Retail Sales (+18/yr) and TCMB
(+9/yr); its biggest single net drag is Unemployment Claims at −293/yr
(weekly cadence turns a small per-trade edge into the largest aggregate
loss on the pair) — an argument for *removing* UC specifically even if
USDTRY overall were kept.

### Position-sizing deviation from the task's assumed figures

The task handoff assumed **~2,700 USDTRY / ~8,000 USDZAR units** for the
margin-capped CAD/year conversion. The trade journal's actual recent
straddle order attempts (`data/forex_bot.db` orders table, 2026-07-14
through 2026-07-16, `strategy='straddle'`) show quantities of
**858,000-864,000 USDZAR units** and **2,453,000-2,495,000 USDTRY units** —
two to three orders of magnitude larger. These orders never filled (report
17's reviewer addendum: 0/30 fills; the ones queried here are the
`ERROR`-status, margin-rejected attempts), but they were sized by the same
whatIf-checked, margin-cap-scaled logic (`RiskManager` + `max_margin_pct_
per_trade: 25.0`) that a filled order would use — so they are the best
available evidence of "current margin-capped sizing," and this report uses
their mean (861,000 / 2,481,250) instead of the task's assumed figures. This
is flagged as an explicit **deviation** below; if the ~2,700/~8,000 figures
come from a different, more current source the user has and this report
doesn't, the net CAD/year figures should be rescaled linearly (CAD/year
scales linearly with units — e.g. at 8,000 USDZAR units net CAD/year would
be ≈ −$8,899 × 8,000/861,000 ≈ **−$83/year**, immaterial either way; at
2,700 USDTRY units net CAD/year ≈ −$2,016 × 2,700/2,481,250 ≈ **−$2/year**,
immaterial). At either sizing assumption the *sign* of the verdict is
unchanged — this is a magnitude question, not a pass/fail one.

---

## Which combos clear the pass bar

**None. 0 of 18.** No USDZAR combo and no USDTRY combo simultaneously
clears (a) net 95% CI > 0 at base-case spread and (b) net walk-forward OOS
(2025-2026, configured params) > 0.

Nearest misses (informative, not passing):
- USDTRY/CPI: passes (a) but fails (b) — net WF OOS −4.61.
- USDTRY/FOMC, USDTRY/Retail Sales, USDTRY/TCMB, USDTRY/NFP: net CI spans
  zero at base spread (fail (a)); OOS point estimates mixed (FOMC +12.55
  is the single most positive OOS reading in the whole table, but its
  full-sample CI [−4.74,+12.05] spans zero — N=96 is too small to trust a
  positive OOS point estimate on its own).
- USDZAR/FOMC and USDZAR/SARB: net CI spans zero at base spread (closest
  USDZAR combos to passing (a)), but both have negative OOS.

---

## Production recommendation

This is a **cost audit only** — no `config/settings.yaml` or
`config/events.yaml` changes are made here, per the Analysis-Driven
Configuration rule and this spec's explicit instruction. The decision is
the user's. What the data supports:

1. **The event straddle strategy, net of real IDEALPRO spread cost, does
   not clear its own pass bar on any configured combo.** Reports 04-16's
   "PASS" verdicts were all computed gross; every one of them reverses or
   goes to a coin-flip once the round-trip spread is charged.
2. **USDZAR is the clearer case: net loser across the board**, full-sample
   and OOS, at both the base spread and (much more so) the wide-stress
   spread. There is no spread regime tested in this report at which USDZAR
   passes. If a decision has to be made now, USDZAR is the stronger
   candidate for pausing.
3. **USDTRY is genuinely ambiguous, and the ambiguity is a data problem,
   not (necessarily) an economics problem.** At its live-snapshot low
   reading (6 pips) it looks like a real edge on most event sources; at its
   journal-mean reading (12 pips) it's a wash; at a plausible wide-session
   spread (30 pips, still inside the configured spread gate) it's a clear
   loser. The single highest-value next step is **not** more backtesting —
   it's running `scripts/sample_ib_spreads.py`'s suggested weekday-hourly
   cron (documented in report 17, never installed) to build a real
   IDEALPRO USDTRY spread distribution across sessions before trusting
   either 6 or 12 as "the" spread.
4. **Unemployment Claims is USDTRY's single largest net-of-cost drag**
   (−293 pips/yr of the pair's −267 pips/yr total net loss) despite being
   report 16's statistically strongest gross combo — its weekly cadence
   means a small per-trade negative expectancy compounds fastest. If any
   partial action is taken short of pausing the whole pair, removing UC
   specifically is the best-supported single change.
5. **Consistent with report 17's reviewer addendum**: the event strategy
   has filled 0 of 30 real order attempts to date. There is no live
   realized P&L, gross or net, to confirm or contradict this backtest.
   Combined with this report's findings, **the honest status of the
   flagship strategy is: unproven live, and — on the best available
   cost-adjusted backtest — probably a net loser on USDZAR and no better
   than breakeven on USDTRY.**

**The event edge does not clearly survive real spreads.** That is the
plain answer this audit was commissioned to produce.

---

## Methodology notes & caveats

1. **No parameter search.** Every combo in this report uses the exact
   configured production distance/TP/SL from `config/settings.yaml` /
   `config/events.yaml` as of commit `862df53` (report 16's applied
   verdicts, PR #80). This is a cost audit, not an optimization — the spec
   explicitly asked for "no parameter torture."
2. **Data**: corrected (tz-fixed) Dukascopy 1-min windows from report 16's
   re-download (`scripts/data/dukascopy/{PAIR}_1min.csv`), loaded via
   `monte_carlo_dukascopy.load_dukascopy_data()` (the `(event_date,
   event_name)` grouping fix from report 16 — no date-collision bug).
   2020-01-02 to 2026-07-29, 6.57 years.
3. **Cost convention**: one full round-trip spread deducted per triggered
   leg (`gross_pnl_pips - spread_pips`), exactly report 17's `[full]`
   convention, independently re-derived and verified against report 17's
   own IDEALPRO spot-check numbers (USDZAR pooled 7-event net ≈ report 17's
   −6.7 [−9.2,−4.3] on a slightly different 7-vs-8-event scope and 23.5 vs
   24 pip spread; USDTRY pooled 10-event N=1,495 vs report 17's N=1,488 on
   an equivalent scope — both reproduce closely, confirming this script did
   not introduce a new cost-model bug).
4. **Bootstrap**: 10,000 resamples, 95% CI, no Bonferroni correction
   (matches every prior report's per-combo methodology; this report
   evaluates 18 fixed combos, it does not search a grid, so the
   no-correction convention is consistent with reports 04-16).
5. **Walk-forward**: train 2020-2024, test 2025-2026, configured
   (non-re-optimized) params evaluated on each split — the "Cfg-params OOS"
   methodology from report 16, not a train-optimal walk-forward (there is
   nothing to train here; params are fixed by config).
6. **IDEALPRO spread sample is thin** (n=5 USDZAR / n=12 USDTRY journal
   fills, one month, July 2026, plus one live snapshot each) — flagged
   repeatedly above. This is the single biggest source of uncertainty in
   this report, more consequential than any bootstrap CI shown. The
   spread-sensitivity section exists specifically because of this.
7. **Position sizing** for the CAD/year conversion uses journal-observed
   margin-cap-scaled quantities (861,000 USDZAR / 2,481,250 USDTRY units),
   not the task handoff's assumed ~8,000/~2,700 — see "Position-sizing
   deviation" above. The CAD/year figures scale linearly with whatever
   sizing assumption is correct; the pass/fail verdict does not depend on
   sizing at all (it's a pips-based bar).
8. **No config or src changes; no commits/pushes.** New file:
   `scripts/mc_net_of_cost.py` (ruff-clean). Evidence:
   `scripts/data/net_of_cost_results.json`.
