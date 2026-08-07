# Report 22 — Majors-Pair Event-Straddle Feasibility Study

**Date**: 2026-08-06  
**Scope**: EURUSD and USDJPY event-triggered straddles across 9 US economic event types  
**Data**: Dukascopy 1-min bars, 2020–2026, corrected historical CSV  
**Verdict**: EURUSD shows promise on gross P&L but margin erodes at realistic spreads; USDJPY collapses out-of-sample. Neither pair recommended for live deployment without (a) real IDEALPRO spread sampling and (b) explicit user confirmation.

---

## Executive Summary

The forex-bot project has historically focused on exotic pairs (USDZAR, USDTRY, USDJPY/BOJ) where niche-pair spreads and lower absolute notional values enabled real straddle edge. This report investigates whether the major-pair complex (specifically EURUSD and USDJPY on US economic news) offers sufficient edge to justify activation.

**Finding**: On *gross* P&L, both pairs show superficially attractive returns. On *net* P&L (accounting for typical IDEALPRO spreads), both pairs fail to clear profitability thresholds. USDJPY additionally exhibits out-of-sample Sharpe collapse, indicating in-sample overfitting.

---

## Grid Search Results (Corrected Data, 9-Event-Type Sample)

Unlike prior reports (07, 16), this analysis pools across **all 9 event types present in the corrected Dukascopy CSV**:
- US events: NFP, CPI, FOMC, PPI, GDP, PCE, Unemployment Claims, ISM Manufacturing PMI, Retail Sales

This 7× larger sample (vs. report 07's 3-event NFP/CPI/FOMC-only baseline) changes the picture materially.

### EURUSD Grid Optimum: 10/70/10

| Metric               | Gross   | Net (1.5 pip spread) |
|----------------------|---------|---------------------|
| E[P&L]               | +2.60   | +1.10               |
| 95% CI               | [+1.41, +3.85] | [-0.09, +2.35]  |
| Sharpe ratio         | 4.17    | 1.74                |
| N trades (full 2020–2026) | 1,372   | 1,372               |
| Walk-forward IS (2020–2024) | +2.54 (Sh 3.55) | +1.04 (Sh 1.44) |
| Walk-forward OOS (2025–2026) | +2.79 (Sh 2.19) | +1.29 (Sh 0.98) |

**Critical observation**: Net CI spans zero at base spread (1.5 pips). The gross-to-net transition erases ~58% of the edge. Walk-forward OOS holds positive but with vastly reduced Sharpe (2.19 → 0.98), indicating the sample-driven gross numbers may not be robust.

### USDJPY Grid Optimum: 15/70/10

| Metric               | Gross   | Net (2.0 pip spread) |
|----------------------|---------|---------------------|
| E[P&L]               | +3.21   | +1.21               |
| 95% CI               | [+1.86, +4.61] | [-0.14, +2.61]  |
| Sharpe ratio         | 4.56    | 1.70                |
| N trades (full 2020–2026) | 1,326   | 1,326               |
| Walk-forward IS (2020–2024) | +3.99 (Sh 4.73) | +1.99 (Sh 2.33) |
| Walk-forward OOS (2025–2026) | **+0.94 (Sh 0.71)** | **-1.06 (Sh -0.89)** |

**Critical failure**: USDJPY's out-of-sample walk-forward nets to **negative P&L** (−1.06 pips mean), with Sharpe collapsing from +4.73 (IS) to +0.71 (OOS gross) to **−0.89 (OOS net)**. This is the classic overfitting signature: training-set parameters that do not transfer. Identical pattern observed in report 21 on AUDJPY/USDMXN carry-threshold analysis.

### Why This Differs From Report 07

Report 07 (using 3 event types, ~185 trades per pair) concluded: "EURUSD CI spans zero, do not enable."  
This report (using 9 event types, ~1,400 trades per pair) shows: "EURUSD CI is marginally positive on gross, but collapses at base spread."

The 7× sample enlargement did not yield robust edge; it reveals the fragility of small-sample estimates. The gross Sharpe (4.17) and the OOS Sharpe collapse (2.19) together suggest the initial finding was noise.

---

## Spread Sensitivity Sweep

Unlike report 18 (USDZAR/USDTRY), the bot has **zero live/journal fills** for EURUSD or USDJPY straddles. There is no "base case" to calibrate spreads from trade-journal reality. Instead, the sweep uses published-literature-typical IDEALPRO major-pair event-time spreads as anchors.

### EURUSD: Full-Sample Net P&L at Three Spread Levels

- **Tight (0.5 pips)**: E=+1.86, CI=[+0.67, +3.08], Sharpe 3.02 → **passes** CI > 0
- **Base (1.5 pips)**: E=+1.10, CI=[−0.09, +2.35], Sharpe 1.74 → **marginal fail** CI barely spans zero
- **Stress (4.0 pips)**: E=−1.30, CI=[−2.53, −0.03], Sharpe −2.09 → **hard fail** decisively negative

At a 4.0-pip stress spread (plausible during volatile event windows), EURUSD turns decisively unprofitable.

### USDJPY: Full-Sample Net P&L at Three Spread Levels

- **Tight (0.5 pips)**: E=+2.44, CI=[+1.12, +3.82], Sharpe 3.52 → **passes** CI > 0
- **Base (2.0 pips)**: E=+1.21, CI=[−0.14, +2.61], Sharpe 1.70 → **marginal fail** CI barely spans zero
- **Stress (4.0 pips)**: E=−0.69, CI=[−2.09, +0.73], Sharpe −0.99 → **hard fail** CI spans zero negatively

Same fragility as EURUSD: tight spreads required for profitability, both OOS net negative.

---

## Decision Matrix

| Criterion | EURUSD | USDJPY |
|-----------|--------|--------|
| **Gross P&L (full sample)** | +2.60, CI >0 | +3.21, CI >0 |
| **Net P&L @ base spread** | +1.10, CI spans zero | +1.21, CI spans zero |
| **Walk-forward OOS net** | +1.29 (Sh 0.98) | **−1.06 (Sh −0.89)** |
| **Spread calibration** | None (no live fills) | None (no live fills) |
| **Sample size (full)** | 1,372 trades | 1,326 trades |
| **Recommendation** | **No** — needs spread study | **No** — fails OOS |

---

## Verdict and Next Steps

### Why Not Enable?

1. **EURUSD**: Gross edge (4.17 Sharpe) evaporates under realistic spreads. Net CI at base spread spans zero. Walk-forward OOS Sharpe (0.98) is consistent with noise rather than signal. No live-journal or IDEALPRO spread calibration exists; all cost assumptions are literature-anchored guesses.

2. **USDJPY**: Full-sample gross looks equally strong (4.56 Sharpe), but walk-forward OOS is decisively negative (−0.89 Sharpe net). Classic overfitting: in-sample parameters do not transfer to held-out data. This is the pattern that stopped AUDJPY/USDMXN in report 21 and should stop USDJPY here.

### Prerequisites for Future Reconsideration

If the user later decides to explore majors-pair straddles, **both of the following must be satisfied**:

1. **Real IDEALPRO spread sampling** (modeled after report 17's USDZAR/USDTRY calibration): Place live or paper straddle orders on EURUSD/USDJPY at several event times and measure actual bid–ask spreads and fill spreads observed. Use the result to anchor cost assumptions instead of literature values.

2. **Explicit user confirmation** per CLAUDE.md's Analysis-Driven Configuration rule: The analysis above recommends *not enabling* these pairs. If the user chooses to override this verdict, they must confirm in writing that they are doing so knowingly, with acceptance of the risk that out-of-sample performance may not match in-sample backtests.

---

## Appendix: Script Outputs

All results computed via `scripts/mc_majors_net_of_cost.py`, extending `scripts/mc_net_of_cost.py` (report 18's methodology).

**Grid-search run**: `scripts/monte_carlo_dukascopy.py --pairs EURUSD USDJPY`  
**Results JSON**: `scripts/data/majors_net_of_cost_results.json`  
**Data source**: Dukascopy 1-min bars, 2020–2026, corrected historical CSV  
**Event set**: All 9 event types in the CSV (not filtered by event_name)  
**Walk-forward**: IS 2020–2024, OOS 2025–2026

---

## See Also

- Report 04–16: Original 6-year MC analysis (USDZAR, USDTRY, and carry strategies)
- Report 18: Net-of-cost methodology and USDZAR/USDTRY validation
- Report 21: Carry-threshold analysis and OOS overfitting patterns
