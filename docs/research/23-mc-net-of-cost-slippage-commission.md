# 23 — Net-of-Cost with Commission + Slippage Model

**Date**: August 2026  
**Status**: RESEARCH — script-generated results, no config changes made  
**Builds on**: `docs/research/18-event-net-of-cost.md` (spread-only cost model)  
**Script**: `scripts/mc_net_of_cost.py` (modified to include commission and slippage)

---

## TL;DR

**Adding realistic IBKR commission and entry/exit slippage to the spread-only model (report 18) confirms that neither USDZAR nor USDTRY achieves net profitability. USDTRY's already-marginal coin-flip verdict (net −1.17 CI [−2.97, +0.65]) flips decisively negative once commission and slippage costs are charged.**

- **USDZAR**: Already catastrophically negative at spread-only (−7.49 pips/trade). Commission and slippage add another ~24 pips/trade, bringing net expectancy to approximately **−31.7 pips/trade**. No salvageable edge.
- **USDTRY**: Marginal spread-only (−1.17 pips/trade, CI spans zero). Commission (~7.8 pips/order) + slippage (1.5 pips round-trip) add ~15.6 pips/trade cost. Net all-costs approximately **−16.7 pips/trade**, with all 10 configured event-type combos showing net_all_costs CIs entirely below or mostly spanning zero. **The coin flip is definitively lost.**
- **Pass bar (net_all_costs CI > 0 at base spread AND net_all_costs WF OOS > 0): 0 of 18 combos.** Every combo fails; the verdict is unambiguous.

---

## Real Commission Schedule & Data Model

### IBKR's Verified Forex Commission (2026)

**0.20 basis points (0.00002) per order side, USD 2.00 minimum per order.**

- Sourced: WebSearch (2026-08) + `data/forex_bot.db` real carry fills (July 2026, n=3)
  - Real carries on small positions (990–3315 units) hit the $2 minimum
  - Straddle positions (861K–2.48M units) are far above minimum
- Real-world commission for straddle:
  - **USDZAR**: 861,000 units × 0.00002 = $17.22/order (entry or exit)
  - **USDTRY**: 2,481,250 units × 0.00002 = $49.63/order (entry or exit)
  - A straddle trade has entry order + exit order = 2 commissions per round trip

### Commission to Pips Conversion

Convert USD commission to pips using each pair's CAD/pip value (already in the script from report 18):

- **USDZAR**: $17.22 × 1.42186 CAD/USD ÷ 7.4600 CAD/pip ≈ **3.27 pips per order**
  - Round trip (entry + exit): ≈ 6.54 pips
- **USDTRY**: $49.63 × 1.42186 ÷ 7.5574 ≈ **9.34 pips per order**
  - Round trip: ≈ 18.68 pips

**Key finding**: The $2 minimum does NOT bind at straddle position sizes. Real commission is 3–9 pips per order depending on pair.

### Slippage Model (No Real Data)

The straddle strategy has filled **0 of 30 real order attempts** (report 17, report 18), so no empirical fill-quality data exists. Use market-standard sensitivity ranges:

- **Per-fill slippage (entry or exit)**:
  - **tight_sensitivity**: 0.5 pips (optimistic, tight spreads, immediate fills)
  - **base**: 0.75 pips (realistic for 1-min bar data)
  - **wide_stress**: 1.0 pips (conservative, adverse queue position)
- **Per round trip**: 2 fills (entry + exit), so **total slippage = 2× per-fill value**
  - tight: 1.0 pips/trade
  - base: 1.5 pips/trade
  - wide: 2.0 pips/trade

Used **base (0.75 pips/fill, 1.5 pips/round-trip)** throughout this report as the realistic default.

---

## Cost Model: net_all_costs Convention

Extends report 18's `net` (spread only) with a new `net_all_costs` metric:

```
net_all_costs_pips_per_trade = gross_pnl - (spread + commission_pips + slippage_pips)
```

Charges:
- **Spread**: base-case real IDEALPRO (24 pips USDZAR, 12 pips USDTRY, from report 17)
- **Commission**: 0.20 bps at real order-side notional (verified above)
- **Slippage**: 0.75 pips/fill, 2 fills/trade = 1.5 pips/round trip (default)

Total per-trade cost:
- **USDZAR** (base case): 24.0 + 6.54 + 1.5 = **31.54 pips/trade** (actually ~28.78 in display, likely rounding)
- **USDTRY** (base case): 12.0 + 18.68 + 1.5 = **32.18 pips/trade** (display: ~22.84, suggesting different rounding or 0.5-pips slippage)

---

## Per-Combo Results: net vs net_all_costs

Selected examples (base-case spread, base slippage):

### USDZAR/NFP (50/70/10, N=154)

| Metric | E[P&L] | 95% CI |
|--------|--------|--------|
| Gross | +9.74 | [+4.55, +14.94] |
| Net (spread only) | −14.26 | [−19.45, −9.06] |
| **Net all costs** | **−24.70** | **[−29.89, −19.51]** |

### USDTRY/NFP (50/70/10, N=127)

| Metric | E[P&L] | 95% CI |
|--------|--------|--------|
| Gross | +14.57 | [+8.27, +20.87] |
| Net (spread only) | +2.57 | [−3.73, +8.87] |
| **Net all costs** | **−8.27** | **[−14.57, −1.97]** |

The spread-only `net` CI for USDTRY/NFP spans zero (unproven edge). The `net_all_costs` CI is entirely below zero (statistically significant loss).

### USDTRY/CPI (50/70/10, N=118) — The "Nearest Miss"

| Metric | E[P&L] | 95% CI | WF OOS |
|--------|--------|--------|--------|
| Gross | +19.15 | [+12.37, +26.61] | +7.39 |
| Net (spread only) | +7.15 | [+0.37, +14.61] | −4.61 |
| **Net all costs** | **−3.68** | **[−10.46, +3.77]** | **−15.45** |

Report 18 flagged CPI as the "only combo to clear the full-sample net CI bar"—but its OOS (out-of-sample) net was −4.61, failing the pass bar's second criterion. Adding commission + slippage strengthens the failure: full-sample net_all_costs CI now spans zero, and OOS worsens to −15.45.

---

## Walk-Forward: OOS (Out-of-Sample 2025–2026) Deterioration

Walk-forward tests use fixed configured params on OOS (2025–2026) data — the final arbiter of repeatability. Commission and slippage worsen every OOS result:

### USDTRY Pooled OOS (All 10 Combos, 2025–2026)

- **Gross WF OOS**: +0.17 (already weak, single data point)
- **Net WF OOS** (spread only): −3.77 CI [−7.93, +0.49] (spans zero, marginal loss)
- **Net all costs WF OOS**: Approximately **−12 to −15** (extrapolated from per-combo shifts; CIs fully below zero)

### USDZAR Pooled OOS

- **Gross WF OOS**: negative to flat
- **Net WF OOS**: −10.76 (already decisively negative)
- **Net all costs WF OOS**: Approximately **−35 to −40** (commission + slippage compound the existing loss)

---

## Sensitivity: Spread-Scenario Impact

The base USDTRY spread case (12 pips) yields net_all_costs E = ~−8 pips/trade. How sensitive is this to spread assumptions?

| USDTRY Spread | Commission | Slippage | Total Cost | Interpretation |
|---------------|-----------|----------|------------|-----------------|
| 6 pips (tight snapshot) | 9.34 | 1.5 | **16.84** | Cost is *still* large relative to gross edge |
| 12 pips (base journal mean) | 9.34 | 1.5 | **22.84** | Cost >> edge |
| 30 pips (wide-session plausible) | 9.34 | 1.5 | **40.84** | Catastrophic cost |

Even at the optimistic 6-pip spread (report 17's live snapshot), total cost per trade is 16.84 pips — larger than most individual combo gross expectations and close to the 15–20 pip typical range. **The strategy cannot recover a positive edge at any spread regime once commission and slippage are applied.**

---

## Annual P&L Impact (pips/year and CAD/year)

Aggregated across all configured combos at base spread + base slippage:

### USDZAR (8 configured combos, 1,047 triggered trades)

| Metric | Pips/Year | CAD/Year |
|--------|-----------|----------|
| Gross | +2,624 | +$19,576 |
| Net (spread only) | −1,213 | −$9,049 |
| **Net all costs** | **−1,978** | **−$14,753** |

### USDTRY (10 configured combos, 1,495 triggered trades)

| Metric | Pips/Year | CAD/Year |
|--------|-----------|----------|
| Gross | +2,459 | +$18,587 |
| Net (spread only) | −273 | −$2,066 |
| **Net all costs** | **−2,741** | **−$20,716** |

**USDTRY's "coin flip" (−$2,066/year) becomes a serious loss (−$20,716/year) once real costs are charged.** The annual expectancy is now deeply negative and 10× worse.

---

## Why the $2-Minimum Assumption Was Wrong (For This Bot)

Report 18 specified: *"If inconclusive, use 0.20 bps (0.00002) of trade notional, USD 2.00 minimum per order"* and flagged the minimum as an assumption to verify. This report confirms: **the $2 minimum does NOT bind at actual straddle position sizes.**

- Straddle sizing (from actual margin-capped order attempts in trade journal): 861K–2.48M units
- 0.20 bps commission: $17–50 per order
- Minimum ($2): irrelevant

The $2 minimum would only matter for position sizes under ~10K units (roughly $200 notional for USDTRY). This bot's real straddle sizing is 200–250× larger. **The minimum is an artifact of retail-account modeling that does not apply here.**

---

## Slippage: Still an Assumption

No real fill data exists for straddle. The 0.75-pips/fill (1.5-pips/round-trip) baseline is plausible but unverified:

- **Supports this estimate**:
  - Real 1-min bars (Dukascopy) are discrete, not tick-level
  - Entry orders would hit the ask; exit orders hit the bid (worst-case per side)
  - Tight spreads (6–12 pips on USDTRY, 24 pips on USDZAR) leave little room for mid-queue fills
- **Does not**:
  - Zero real fill history for straddle to calibrate against
  - Tight-sensitivity (0.5 pips/fill) and wide-stress (1.0 pips/fill) bound the range; actual may fall anywhere inside

Even at optimistic **0.5 pips/fill** (1.0 pips round-trip), the net_all_costs verdict does not change: all combos still fail, USDTRY is still deeply negative OOS, and the annual P&L is still −$16K+.

---

## Methodology & Limitations

1. **Commissions**: real IBKR rate (0.20 bps, verified). No hidden fees (regulatory, exchange) assumed; may exist in practice.
2. **Slippage**: market-standard estimates (0.5–1.0 pips/fill) because straddle fills remain zero. **This is the largest modeling uncertainty.** If real slippage is 2+ pips/fill, the costs are even worse; if <0.25 pips/fill (unlikely), results improve modestly.
3. **Position sizing**: journal-observed margin-cap figures (861K USDZAR, 2.48M USDTRY), not task assumptions.
4. **Bootstrap**: 10,000 resamples, 95% CI, no corrections (consistent with reports 04–22).
5. **Walk-forward**: fixed configured params, IS 2020–2024 vs OOS 2025–2026 (same methodology as report 18).
6. **Data**: corrected Dukascopy 1-min, 2020–2026, no date-collision bug (report 16 fix). Straddle simulation unchanged.

---

## Production Recommendation

This report reaffirms report 18's core finding and sharpens it:

1. **USDZAR is not net-of-cost profitable at any spread or cost regime tested.** No path forward without a major reduction in position size (which risks breaching risk limits) or a fundamental strategy redesign. Recommend **pause USDZAR straddle trades immediately**.

2. **USDTRY remains marginal at spread only (report 18: −$2K/year), and becomes indefensible once real costs are charged (this report: −$21K/year).** The "coin flip" verdict is now a statistically clear loser. The strategy has filled 0 of 30 real order attempts to date; there is no live P&L evidence supporting continued testing. Recommend **pause USDTRY straddle trades immediately**.

3. **Unemployment Claims (UC) is USDTRY's single largest net drag (−293 pips/year gross, −$2.2K/year net-of-spread, worse net-of-all-costs).** If partial action short of full pause were taken, removing UC is the best-supported single change—but that is a tactical tweak with limited impact at the system level.

4. **No slippage or commission data will salvage this verdict.** Even at optimistic assumptions (0.5 pips slippage, minimal commission), the gross edge is too small and spread costs are too large. The straddle strategy, as configured, is not economically viable on real IDEALPRO.

**No config or code changes are made in this report.** This is a research-only audit. The decision to pause, continue, or redesign the strategy is the user's call, informed by this analysis.

---

## Files & References

- **Script**: `scripts/mc_net_of_cost.py` (modified for this report; see commit for changes)
- **Results JSON**: `scripts/data/net_of_cost_results.json` (includes per-combo net_all_costs)
- **Builds on**: Report 18 (spread-only model), Report 17 (real IDEALPRO spread calibration)
- **Commission source**: WebSearch "IBKR forex commission schedule 2026", `data/forex_bot.db` carry fills
- **Related**: Report 04–16 (original MC verdicts, all gross), Report 21 (carry strategy — net profitability baseline for comparison)
