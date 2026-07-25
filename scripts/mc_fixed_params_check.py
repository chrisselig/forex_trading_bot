"""Phase C: evaluate CONFIGURED production params (and old-report optima for
disabled pairs) on the corrected Dukascopy data.

Covers combos that the stock MC scripts do not evaluate at exact configured
params. For each (pair, event set, distance/tp/sl, spread):
  - full-sample bootstrap CI / Sharpe / WR / PF / N
  - fixed-param IS (2020-2024) and OOS (2025-2026) evaluation
"""
from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, "/home/doopdeep/00_data_projects/forex_trading_bot/scripts")

from monte_carlo_dukascopy import (  # noqa: E402
    bootstrap_metrics,
    load_dukascopy_data,
    simulate_straddle,
)

IS_YEARS = {2020, 2021, 2022, 2023, 2024}
OOS_YEARS = {2025, 2026}


def eval_fixed(pair, events, wanted, dist, tp, sl, spread, years=None):
    pnls = []
    for v in events.values():
        if v["event_name"] not in wanted:
            continue
        if years is not None and int(v["event_date"][:4]) not in years:
            continue
        trades = simulate_straddle(
            v["bars"], v["event_utc"], pair, dist, tp, sl, spread_pips=spread
        )
        pnls.extend(t.pnl_pips for t in trades if t.triggered)
    if not pnls:
        return None
    return bootstrap_metrics(np.array(pnls))


COMBOS = [
    # --- ACTIVE production combos at CONFIGURED params ---
    ("USDZAR", {"SARB Rate Decision"}, 50, 70, 10, 25.0, "ACTIVE cfg"),
    ("USDZAR", {"South Africa CPI"}, 50, 70, 10, 25.0, "ACTIVE cfg"),
    ("USDTRY", {"TCMB Rate Decision"}, 20, 60, 10, 30.0, "ACTIVE cfg"),
    ("USDTRY", {"Unemployment Claims"}, 50, 70, 10, 30.0, "ACTIVE cfg"),
    ("USDTRY", {"ISM Manufacturing PMI"}, 50, 70, 10, 30.0, "ACTIVE cfg"),
    ("USDTRY", {"Retail Sales"}, 50, 70, 10, 30.0, "ACTIVE cfg"),
    ("USDJPY", {"BOJ Rate Decision"}, 25, 15, 15, 2.0, "ACTIVE cfg"),
    ("AUDUSD", {"NFP"}, 40, 15, 25, 1.5, "ACTIVE cfg"),
    ("AUDUSD", {"CPI"}, 40, 15, 25, 1.5, "ACTIVE cfg"),
    ("AUDUSD", {"FOMC"}, 40, 15, 25, 1.5, "ACTIVE cfg"),
    ("AUDUSD", {"PPI"}, 40, 15, 25, 1.5, "ACTIVE cfg"),
    ("AUDUSD", {"GDP"}, 40, 15, 25, 1.5, "ACTIVE cfg"),
    ("AUDUSD", {"PCE"}, 40, 15, 25, 1.5, "ACTIVE cfg"),
    ("AUDUSD", {"RBA Rate Decision"}, 40, 70, 30, 1.5, "ACTIVE cfg"),
    ("AUDUSD", {"Australia CPI"}, 40, 70, 30, 1.5, "ACTIVE cfg"),
    ("AUDUSD", {"Australia Employment"}, 40, 70, 30, 1.5, "ACTIVE cfg"),
    # --- DISABLED pairs: old-report optimal params, quick check ---
    ("GBPUSD", {"NFP", "CPI", "FOMC"}, 35, 15, 25, 2.0, "DISABLED r04"),
    ("USDCAD", {"NFP", "CPI", "FOMC"}, 10, 15, 15, 2.5, "DISABLED r04"),
    ("GBPJPY", {"NFP", "CPI", "FOMC"}, 10, 15, 10, 4.0, "DISABLED r04"),
    ("EURUSD", {"NFP", "CPI", "FOMC", "PPI", "GDP", "PCE"}, 10, 20, 10, 1.5,
     "DISABLED r07"),
    ("CADJPY", {"BOC Rate Decision", "Canada CPI", "Canada Employment"},
     45, 20, 15, 3.0, "DISABLED r10"),
    ("CADJPY", {"BOJ Rate Decision", "Japan CPI"}, 50, 50, 10, 3.0,
     "DISABLED r10"),
    ("CADJPY", {"NFP", "CPI", "FOMC", "PPI", "GDP", "PCE"}, 50, 15, 30, 3.0,
     "DISABLED r10"),
    ("EURCAD", {"BOC Rate Decision", "Canada CPI", "Canada Employment"},
     25, 15, 15, 3.0, "DISABLED r10"),
    ("EURCAD", {"NFP", "CPI", "FOMC", "PPI", "GDP", "PCE"}, 10, 15, 20, 3.0,
     "DISABLED r10"),
    ("GBPCAD", {"BOC Rate Decision", "Canada CPI", "Canada Employment"},
     10, 15, 10, 3.5, "DISABLED r10"),
    ("GBPCAD", {"NFP", "CPI", "FOMC", "PPI", "GDP", "PCE"}, 15, 15, 10, 3.5,
     "DISABLED r10"),
]


def fmt(m):
    if m is None:
        return "n/a"
    return (
        f"E={m['mean_pnl']:+6.1f} CI=[{m['ci_low']:+6.1f},{m['ci_high']:+6.1f}] "
        f"WR={m['win_rate'] * 100:4.1f}% Sh={m['sharpe']:+5.2f} N={m['n_trades']}"
    )


def main():
    cache: dict[str, dict] = {}
    print(f"{'pair':7s} {'events':45s} {'params':9s} {'tag':12s}")
    for pair, wanted, d, tp, sl, spread, tag in COMBOS:
        if pair not in cache:
            cache[pair] = load_dukascopy_data(pair)
        events = cache[pair]
        full = eval_fixed(pair, events, wanted, d, tp, sl, spread)
        is_m = eval_fixed(pair, events, wanted, d, tp, sl, spread, IS_YEARS)
        oos = eval_fixed(pair, events, wanted, d, tp, sl, spread, OOS_YEARS)
        name = "/".join(sorted(wanted))[:45]
        print(f"\n{pair:7s} {name:45s} {d}/{tp}/{sl} sp={spread} [{tag}]")
        print(f"  FULL: {fmt(full)}")
        print(f"  IS  : {fmt(is_m)}")
        print(f"  OOS : {fmt(oos)}")


if __name__ == "__main__":
    main()
