"""Report 22 — Majors (EURUSD/USDJPY) event-straddle net-of-cost check.

Extends report 18's net-of-cost methodology (`mc_net_of_cost.py`) to the two
candidate major-pair combos identified by `scripts/monte_carlo_dukascopy.py
--pairs EURUSD USDJPY` (report 22's fresh corrected-data grid search):

- EURUSD's own full-sample grid optimum (all event types present in the
  corrected Dukascopy CSV — NFP/CPI/FOMC/PPI/GDP/PCE/Unemployment Claims/
  ISM Manufacturing PMI/Retail Sales)
- EURUSD at report 16's quick-check params (10/20/10, the report-07
  shifted-data optimum) for direct comparison to report 16's corrected-data
  quick-check numbers (+2.3 [+1.2,+3.4] full-sample, +2.6 [+0.3,+5.1] OOS)
- USDJPY's own full-sample grid optimum (never tested on US events before
  this report; only USDJPY/BOJ — a domestic event — was tested in reports
  06/16)

Unlike report 18 (USDZAR/USDTRY), there is NO trade-journal or live-snapshot
IDEALPRO spread sample for EURUSD or USDJPY straddles — the bot has never
traded either pair. There is nothing to calibrate a "base case" spread from.
This script therefore reports a spread SENSITIVITY SWEEP across published-
literature-typical IDEALPRO major-pair spreads instead of a single base
case, and treats all of it as a bigger, not smaller, source of uncertainty
than report 18's already-flagged thin exotic-pair spread sample.

Cost convention (identical to report 18 / mc_net_of_cost.py, unmodified):
net_pnl_pips = gross_pnl_pips - spread_pips (one full round-trip spread
deducted per triggered leg).

Usage:
    python scripts/mc_majors_net_of_cost.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from monte_carlo_dukascopy import (  # noqa: E402
    bootstrap_metrics,
    load_dukascopy_data,
    simulate_straddle,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
RESULTS_PATH = DATA_DIR / "majors_net_of_cost_results.json"

IS_YEARS = {2020, 2021, 2022, 2023, 2024}
OOS_YEARS = {2025, 2026}

# Grid-search results from scripts/monte_carlo_dukascopy.py --pairs EURUSD USDJPY (report 22).
GRID_DIST_EURUSD = 10.0
GRID_TP_EURUSD = 70.0
GRID_SL_EURUSD = 10.0
GRID_DIST_USDJPY = 15.0
GRID_TP_USDJPY = 70.0
GRID_SL_USDJPY = 10.0

# Filled in from the grid-search run (scripts/monte_carlo_dukascopy.py
# --pairs EURUSD USDJPY, report 22). Both entries mean "evaluate this
# pair pooled across ALL event types present in the Dukascopy CSV" (None
# for event_name = no filter), matching that grid search's own pooling
# convention (it does not filter by event_name either).
CANDIDATES: list[tuple[str, str, float, float, float]] = [
    ("EURUSD", "grid_optimum", GRID_DIST_EURUSD, GRID_TP_EURUSD, GRID_SL_EURUSD),
    ("EURUSD", "report16_quickcheck", 10.0, 20.0, 10.0),
    ("USDJPY", "grid_optimum", GRID_DIST_USDJPY, GRID_TP_USDJPY, GRID_SL_USDJPY),
]

# Spread sensitivity sweep — NOT calibrated from any live/journal IDEALPRO
# sample (none exists for these pairs). Tight/base/wide anchored to
# published typical EURUSD/USDJPY retail-ECN event-time spreads; treat as
# indicative only. EVENT_SPREAD_PIPS in monte_carlo_dukascopy.py already
# uses 1.5 (EURUSD) / 2.0 (USDJPY) as the *trigger-shift* estimate (report
# 04-16 convention); this sweep additionally tests tighter and wider values
# as the *deducted cost*.
SPREAD_POINTS: dict[str, list[tuple[str, float]]] = {
    "EURUSD": [("tight", 0.5), ("base", 1.5), ("wide_stress", 4.0)],
    "USDJPY": [("tight", 0.5), ("base", 2.0), ("wide_stress", 4.0)],
}


def eval_combo(events: dict, pair: str, event_name: str | None, dist: float,
                tp: float, sl: float, spread: float,
                years: set[int] | None) -> dict:
    """Run simulate_straddle for all matching event windows at one spread
    value. event_name=None pools across every event type in the CSV."""
    pnls = []
    n_events = 0
    for v in events.values():
        if event_name is not None and v["event_name"] != event_name:
            continue
        if years is not None and int(v["event_date"][:4]) not in years:
            continue
        n_events += 1
        trades = simulate_straddle(
            bars=v["bars"], event_utc_str=v["event_utc"], pair=pair,
            distance_pips=dist, tp_pips=tp, sl_pips=sl, spread_pips=spread,
        )
        for t in trades:
            if t.triggered:
                pnls.append(t.pnl_pips)
    if not pnls:
        return {"n_events": n_events, "n_trades": 0, "pnl": np.array([])}
    return {"n_events": n_events, "n_trades": len(pnls), "pnl": np.array(pnls)}


def gross_net_metrics(pnl: np.ndarray, spread: float) -> dict:
    gross = bootstrap_metrics(pnl)
    net = bootstrap_metrics(pnl - spread)
    return {"gross": gross, "net": net}


def fmt(m: dict | None) -> str:
    if m is None or m["n_trades"] == 0:
        return "no trades"
    return (f"E={m['mean_pnl']:+6.2f} CI=[{m['ci_low']:+6.2f},{m['ci_high']:+6.2f}] "
            f"Sh={m['sharpe']:+5.2f} N={m['n_trades']}")


def main() -> None:
    cache: dict[str, dict] = {}
    for pair in ("EURUSD", "USDJPY"):
        print(f"Loading {pair} Dukascopy data...")
        cache[pair] = load_dukascopy_data(pair)

    all_results: dict[str, dict] = {}

    for pair, label, dist, tp, sl in CANDIDATES:
        key = f"{pair}/{label}"
        print(f"\n================ {key} @ {dist:.0f}/{tp:.0f}/{sl:.0f} ================")
        events = cache[pair]
        combo_res: dict = {"pair": pair, "label": label,
                            "dist": dist, "tp": tp, "sl": sl}

        spread_pts = SPREAD_POINTS[pair]
        base_label, base_spread = spread_pts[1]  # "base" is index 1
        for spread_label, spread in spread_pts:
            full = eval_combo(events, pair, None, dist, tp, sl, spread, None)
            gm = gross_net_metrics(full["pnl"], spread) if full["n_trades"] else None
            combo_res[f"full_{spread_label}"] = {
                "spread": spread, "n_events": full["n_events"],
                "n_trades": full["n_trades"],
                "gross": gm["gross"] if gm else None,
                "net": gm["net"] if gm else None,
            }
            g = gm["gross"] if gm else None
            n = gm["net"] if gm else None
            print(f"  FULL   @spread={spread:5.2f} ({spread_label:11s}) "
                  f"gross {fmt(g)}  |  net {fmt(n)}")

        # walk-forward: fixed params, IS 2020-2024 / OOS 2025-2026, base spread
        is_ = eval_combo(events, pair, None, dist, tp, sl, base_spread, IS_YEARS)
        oos = eval_combo(events, pair, None, dist, tp, sl, base_spread, OOS_YEARS)
        gm_is = gross_net_metrics(is_["pnl"], base_spread) if is_["n_trades"] else None
        gm_oos = gross_net_metrics(oos["pnl"], base_spread) if oos["n_trades"] else None
        combo_res["wf_is"] = {
            "n_events": is_["n_events"], "n_trades": is_["n_trades"],
            "gross": gm_is["gross"] if gm_is else None,
            "net": gm_is["net"] if gm_is else None,
        }
        combo_res["wf_oos"] = {
            "n_events": oos["n_events"], "n_trades": oos["n_trades"],
            "gross": gm_oos["gross"] if gm_oos else None,
            "net": gm_oos["net"] if gm_oos else None,
        }
        print(f"  WF IS  2020-2024  gross {fmt(gm_is['gross'] if gm_is else None)}  "
              f"|  net {fmt(gm_is['net'] if gm_is else None)}")
        print(f"  WF OOS 2025-2026  gross {fmt(gm_oos['gross'] if gm_oos else None)}  "
              f"|  net {fmt(gm_oos['net'] if gm_oos else None)}")

        net_base = combo_res["full_base"]["net"]
        passes = (net_base is not None and net_base["ci_low"] > 0
                  and gm_oos is not None and gm_oos["net"]["mean_pnl"] > 0)
        combo_res["passes_bar"] = bool(passes)
        print(f"  PASS BAR (net CI>0 @base spread AND net WF OOS>0): {passes}")

        all_results[key] = combo_res

    RESULTS_PATH.write_text(json.dumps(all_results, indent=1, default=str))
    print(f"\nresults saved -> {RESULTS_PATH}")


if __name__ == "__main__":
    main()
