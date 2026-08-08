"""Spec 18 — Event-strategy net-of-cost audit.

Reports 04-16 compute GROSS P&L: simulate_straddle() shifts the entry
trigger by spread/2 but TP/SL are measured from that shifted entry, so
realized P&L never reflects the spread magnitude (verified in report 17's
reviewer addendum). This script adds the honest NET convention — deduct
one full round-trip spread per triggered leg (report 17's `[full]`
convention) — at REAL IDEALPRO event-time spreads (not Dukascopy tick
spreads, which report 17 proved are 3.6-15x too wide for these exotics),
for every ACTIVE PRODUCTION combo in config/settings.yaml + events.yaml.

No parameter search: params are fixed at the configured production values.
This is a cost audit, not an optimization.

Usage:
    python scripts/mc_net_of_cost.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from monte_carlo_dukascopy import (  # noqa: E402
    PIP_SIZES,
    bootstrap_metrics,
    load_dukascopy_data,
    simulate_straddle,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
RESULTS_PATH = DATA_DIR / "net_of_cost_results.json"

IS_YEARS = {2020, 2021, 2022, 2023, 2024}
OOS_YEARS = {2025, 2026}

# ---------------------------------------------------------------------------
# Active production combos (config/settings.yaml straddle_pair_overrides +
# config/events.yaml pairs lists, as of commit 862df53 / PR #80 — report 16
# verdicts applied). event_name matches the Dukascopy CSV event_name column
# exactly (verified against monte_carlo_dukascopy.py's date-builder labels).
# ---------------------------------------------------------------------------
COMBOS: list[tuple[str, str, float, float, float]] = [
    ("USDZAR", "NFP", 50, 70, 10),
    ("USDZAR", "CPI", 50, 70, 10),
    ("USDZAR", "FOMC", 50, 70, 10),
    ("USDZAR", "PPI", 50, 70, 10),
    ("USDZAR", "GDP", 50, 70, 10),
    ("USDZAR", "PCE", 50, 70, 10),
    ("USDZAR", "SARB Rate Decision", 50, 70, 10),
    ("USDZAR", "South Africa CPI", 50, 70, 10),
    ("USDTRY", "NFP", 50, 70, 10),
    ("USDTRY", "CPI", 50, 70, 10),
    ("USDTRY", "FOMC", 50, 70, 10),
    ("USDTRY", "PPI", 50, 70, 10),
    ("USDTRY", "GDP", 50, 70, 10),
    ("USDTRY", "PCE", 50, 70, 10),
    ("USDTRY", "Unemployment Claims", 50, 70, 10),
    ("USDTRY", "ISM Manufacturing PMI", 50, 70, 10),
    ("USDTRY", "Retail Sales", 50, 70, 10),
    ("USDTRY", "TCMB Rate Decision", 35, 70, 10),
]

# Real IDEALPRO spreads (report 17 calibration; trade journal
# data/forex_bot.db orders table, entry_spread_pips on real straddle
# order attempts):
#   USDZAR journal mean 23.5 (n=5), live snapshot 24.9  -> base 24
#   USDTRY journal mean 12.1 (n=12), live snapshot 5.9  -> base 12
SPREAD_POINTS: dict[str, list[tuple[str, float]]] = {
    "USDZAR": [("base", 24.0), ("wide_stress", 40.0)],
    "USDTRY": [("base", 12.0), ("tight_sensitivity", 6.0), ("wide_stress", 30.0)],
}

# Margin-capped position sizing. The spec/task handoff assumed ~2,700
# USDTRY / ~8,000 USDZAR units. The trade journal's actual recent
# margin-cap-scaled order attempts (data/forex_bot.db orders, straddle
# strategy, ERROR status = margin-rejected but sized by the same whatIf
# scaling logic that a filled order would use) are two to three orders
# of magnitude larger. Using the JOURNAL-OBSERVED sizes here — they are
# directly verifiable and reflect the current (post PR #75) MaxOrderSize
# / margin-cap logic; the spec's assumed sizes are flagged as a deviation
# in the report.
POSITION_UNITS = {
    "USDZAR": 861_000.0,   # mean of 2026-07-14/15 journal orders (858k, 864k)
    "USDTRY": 2_481_250.0,  # mean of 2026-07-14..16 journal orders (2453k-2495k)
}
# Spot rates used for quote->CAD conversion (Dukascopy daily closes,
# 2026-07-01 — most recent common date across USDZAR/USDTRY/USDCAD daily
# CSVs). quote_to_cad = USDCAD / pair_mid (src/forex_bot/broker/pricing.py
# get_quote_to_cad_rate, non-USD non-CAD quote branch).
SPOT = {"USDCAD": 1.42186, "USDZAR": 16.41054, "USDTRY": 46.68239}
QUOTE_TO_CAD = {
    "USDZAR": SPOT["USDCAD"] / SPOT["USDZAR"],
    "USDTRY": SPOT["USDCAD"] / SPOT["USDTRY"],
}

# Commission model: IBKR charges 0.20 bps (0.00002) per side on forex with
# $2 minimum per order (verified 2026-08). For straddle position sizes (861k
# USDZAR, 2.48M USDTRY), the $2 minimum does NOT bind; real commission is
# ~$17-50 per entry/exit order. A straddle round trip = entry order + exit
# order = 2 order commissions. Entry commission = units × 0.00002, exit same.
IBKR_COMMISSION_BPS = 0.00002  # 0.20 basis points per side (per order)
IBKR_COMMISSION_MIN = 2.0      # $2 minimum per order (does not bind here)

# Slippage model: no real fill data for straddle strategy (0/30 fills to date).
# Model per-fill sensitivity as 0.5/0.75/1.0 pips per fill (low/base/high).
# Each straddle trade has entry fill + exit fill = 2 fills per round trip.
SLIPPAGE_PER_FILL = {
    "tight_sensitivity": 0.5,   # optimistic
    "base": 0.75,               # realistic
    "wide_stress": 1.0,         # conservative
}


def eval_combo(events: dict, pair: str, event_name: str, dist: float, tp: float,
                sl: float, spread: float, years: set[int] | None) -> dict | None:
    """Run simulate_straddle for all matching event windows at one spread
    value. Returns triggered-trade pnl_pips array (gross) plus n_events
    (distinct event dates seen, triggered or not)."""
    pnls = []
    n_events = 0
    for v in events.values():
        if v["event_name"] != event_name:
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


def calc_commission_pips(pair: str, cad_per_pip: float) -> float:
    """Calculate commission per order (entry or exit) in pips.

    Commission = units × 0.00002 USD per order. Convert to pips using CAD/pip.
    For straddle: entry order + exit order = 2× this commission.
    """
    units = POSITION_UNITS[pair]
    commission_usd_per_order = max(units * IBKR_COMMISSION_BPS, IBKR_COMMISSION_MIN)
    # Convert USD to CAD (assume 1 USD ≈ 1.42 CAD, but CAD/pip is already normalized)
    # cad_per_pip = pip_size * units * quote_to_cad
    # To get pips from CAD: pips = cad_amount / cad_per_pip
    commission_cad = commission_usd_per_order * 1.42186  # rough USD->CAD
    commission_pips = commission_cad / cad_per_pip if cad_per_pip else 0
    return commission_pips


def calc_slippage_pips(slippage_mode: str) -> float:
    """Calculate total slippage in pips for a round-trip trade.

    Each fill has slippage_mode pips slippage. Entry + exit = 2 fills.
    """
    per_fill = SLIPPAGE_PER_FILL.get(slippage_mode, SLIPPAGE_PER_FILL["base"])
    return per_fill * 2  # entry fill + exit fill


def gross_net_metrics(pnl: np.ndarray, spread: float, pair: str = None,
                      cad_per_pip: float = None, slippage_mode: str = "base") -> dict:
    """Compute gross, net (spread only), and net_all_costs metrics.

    gross = original P&L
    net = gross - spread (existing convention from report 18)
    net_all_costs = gross - spread - commission - slippage

    If pair/cad_per_pip provided, include commission; if slippage_mode provided, include slippage.
    """
    gross = bootstrap_metrics(pnl)
    net = bootstrap_metrics(pnl - spread)

    # net_all_costs: deduct spread + commission + slippage
    commission_pips = 0.0
    if pair is not None and cad_per_pip is not None:
        commission_pips = calc_commission_pips(pair, cad_per_pip)
    slippage_pips = calc_slippage_pips(slippage_mode)
    total_cost_pips = spread + commission_pips + slippage_pips
    net_all_costs = bootstrap_metrics(pnl - total_cost_pips) if total_cost_pips > 0 else gross

    return {
        "gross": gross,
        "net": net,
        "net_all_costs": net_all_costs,
        "_cost_breakdown": {
            "spread_pips": spread,
            "commission_pips": commission_pips,
            "slippage_pips": slippage_pips,
            "total_pips": total_cost_pips,
        }
    }


def fmt(m: dict) -> str:
    if m is None or m["n_trades"] == 0:
        return "no trades"
    return (f"E={m['mean_pnl']:+6.2f} CI=[{m['ci_low']:+6.2f},{m['ci_high']:+6.2f}] "
            f"Sh={m['sharpe']:+5.2f} N={m['n_trades']}")


def fmt_all_costs(gm: dict) -> str:
    """Format net_all_costs (spread + commission + slippage) metrics."""
    if gm is None or "net_all_costs" not in gm:
        return "no data"
    m = gm["net_all_costs"]
    if m is None or m["n_trades"] == 0:
        return "no trades"
    cb = gm.get("_cost_breakdown", {})
    return (f"E={m['mean_pnl']:+6.2f} CI=[{m['ci_low']:+6.2f},{m['ci_high']:+6.2f}] "
            f"Sh={m['sharpe']:+5.2f} (cost: {cb.get('total_pips', 0):5.2f}pips)")


def main() -> None:
    cache: dict[str, dict] = {}
    cad_per_pip_cache: dict[str, float] = {}
    for pair in ("USDZAR", "USDTRY"):
        print(f"Loading {pair} Dukascopy data...")
        cache[pair] = load_dukascopy_data(pair)
        # Pre-compute CAD/pip for commission calculations
        units = POSITION_UNITS[pair]
        q2c = QUOTE_TO_CAD[pair]
        pip = PIP_SIZES[pair]
        cad_per_pip_cache[pair] = pip * units * q2c

    all_results: dict[str, dict] = {}
    combo_dates: list[str] = []

    for pair, event_name, dist, tp, sl in COMBOS:
        key = f"{pair}/{event_name}"
        print(f"\n================ {key} @ {dist:.0f}/{tp:.0f}/{sl:.0f} ================")
        events = cache[pair]
        combo_res: dict = {"pair": pair, "event_name": event_name,
                            "dist": dist, "tp": tp, "sl": sl}

        # full-sample event dates (for frequency + span)
        for v in events.values():
            if v["event_name"] == event_name:
                combo_dates.append(v["event_date"])

        spread_pts = SPREAD_POINTS[pair]
        base_label, base_spread = spread_pts[0]
        cad_per_pip = cad_per_pip_cache[pair]
        for label, spread in spread_pts:
            full = eval_combo(events, pair, event_name, dist, tp, sl, spread, None)
            gm = gross_net_metrics(full["pnl"], spread, pair=pair,
                                  cad_per_pip=cad_per_pip,
                                  slippage_mode="base") if full["n_trades"] else None
            combo_res[f"full_{label}"] = {
                "spread": spread, "n_events": full["n_events"],
                "n_trades": full["n_trades"],
                "gross": gm["gross"] if gm else None,
                "net": gm["net"] if gm else None,
                "net_all_costs": gm["net_all_costs"] if gm else None,
            }
            g = gm["gross"] if gm else None
            n = gm["net"] if gm else None
            nac = gm if gm else None
            print(f"  FULL   @spread={spread:5.1f} ({label:18s}) "
                  f"gross {fmt(g)}  |  net {fmt(n)}  |  net+costs {fmt_all_costs(nac)}")

        # walk-forward: fixed configured params, IS 2020-2024 / OOS 2025-2026,
        # base-case spread only (per spec: pass bar is base-case spread)
        is_ = eval_combo(events, pair, event_name, dist, tp, sl, base_spread, IS_YEARS)
        oos = eval_combo(events, pair, event_name, dist, tp, sl, base_spread, OOS_YEARS)
        gm_is = gross_net_metrics(is_["pnl"], base_spread, pair=pair,
                                 cad_per_pip=cad_per_pip,
                                 slippage_mode="base") if is_["n_trades"] else None
        gm_oos = gross_net_metrics(oos["pnl"], base_spread, pair=pair,
                                  cad_per_pip=cad_per_pip,
                                  slippage_mode="base") if oos["n_trades"] else None
        combo_res["wf_is"] = {
            "n_events": is_["n_events"], "n_trades": is_["n_trades"],
            "gross": gm_is["gross"] if gm_is else None,
            "net": gm_is["net"] if gm_is else None,
            "net_all_costs": gm_is["net_all_costs"] if gm_is else None,
        }
        combo_res["wf_oos"] = {
            "n_events": oos["n_events"], "n_trades": oos["n_trades"],
            "gross": gm_oos["gross"] if gm_oos else None,
            "net": gm_oos["net"] if gm_oos else None,
            "net_all_costs": gm_oos["net_all_costs"] if gm_oos else None,
        }
        print(f"  WF IS  2020-2024  gross {fmt(gm_is['gross'] if gm_is else None)}  "
              f"|  net {fmt(gm_is['net'] if gm_is else None)}")
        print(f"  WF OOS 2025-2026  gross {fmt(gm_oos['gross'] if gm_oos else None)}  "
              f"|  net {fmt(gm_oos['net'] if gm_oos else None)}  "
              f"|  net+costs {fmt_all_costs(gm_oos)}")

        net_base = combo_res[f"full_{base_label}"]["net"]
        net_all_costs_base = combo_res[f"full_{base_label}"]["net_all_costs"]
        passes = (net_base is not None and net_base["ci_low"] > 0
                  and gm_oos is not None and gm_oos["net"]["mean_pnl"] > 0)
        passes_all_costs = (net_all_costs_base is not None and net_all_costs_base["ci_low"] > 0
                           and gm_oos is not None and gm_oos["net_all_costs"]["mean_pnl"] > 0)
        combo_res["passes_bar"] = bool(passes)
        combo_res["passes_bar_all_costs"] = bool(passes_all_costs)
        print(f"  PASS BAR (net CI>0 @base spread AND net WF OOS>0): {passes}")
        print(f"  PASS BAR w/ all costs (spread+commission+slippage): {passes_all_costs}")

        all_results[key] = combo_res

    # ---- span for events/year weighting ----
    dates = pd.to_datetime(pd.Series(combo_dates))
    span_years = (dates.max() - dates.min()).days / 365.25
    print(f"\nData span across all combos: {dates.min().date()} .. "
          f"{dates.max().date()} = {span_years:.2f} years")

    # ---- per-pair aggregate: net pips/year (base spread), net CAD/year ----
    pair_agg: dict[str, dict] = {}
    for pair in ("USDZAR", "USDTRY"):
        base_label = SPREAD_POINTS[pair][0][0]
        total_net_pips = 0.0
        total_gross_pips = 0.0
        total_net_all_costs_pips = 0.0
        combo_breakdown = []
        for (p, event_name, dist, tp, sl) in COMBOS:
            if p != pair:
                continue
            key = f"{p}/{event_name}"
            c = all_results[key][f"full_{base_label}"]
            if c["n_trades"] == 0:
                continue
            sum_net = c["net"]["mean_pnl"] * c["n_trades"]
            sum_gross = c["gross"]["mean_pnl"] * c["n_trades"]
            sum_net_all_costs = (c["net_all_costs"]["mean_pnl"] * c["n_trades"]
                                if c["net_all_costs"] else 0.0)
            per_year_net = sum_net / span_years
            per_year_gross = sum_gross / span_years
            per_year_net_all_costs = sum_net_all_costs / span_years
            total_net_pips += per_year_net
            total_gross_pips += per_year_gross
            total_net_all_costs_pips += per_year_net_all_costs
            combo_breakdown.append({
                "event_name": event_name, "n_trades": c["n_trades"],
                "net_pips_per_year": per_year_net,
                "gross_pips_per_year": per_year_gross,
                "net_all_costs_pips_per_year": per_year_net_all_costs,
            })
        units = POSITION_UNITS[pair]
        q2c = QUOTE_TO_CAD[pair]
        pip = PIP_SIZES[pair]
        cad_per_pip = pip * units * q2c
        pair_agg[pair] = {
            "span_years": span_years,
            "base_spread": SPREAD_POINTS[pair][0][1],
            "units": units,
            "quote_to_cad": q2c,
            "cad_per_pip": cad_per_pip,
            "net_pips_per_year": total_net_pips,
            "gross_pips_per_year": total_gross_pips,
            "net_all_costs_pips_per_year": total_net_all_costs_pips,
            "net_cad_per_year": total_net_pips * cad_per_pip,
            "gross_cad_per_year": total_gross_pips * cad_per_pip,
            "net_all_costs_cad_per_year": total_net_all_costs_pips * cad_per_pip,
            "combo_breakdown": combo_breakdown,
        }
        print(f"\n{pair}: net {total_net_pips:+.1f} pips/yr "
              f"(gross {total_gross_pips:+.1f}), "
              f"net w/ all costs {total_net_all_costs_pips:+.1f} pips/yr")
        print(f"  CAD/pip@{units:,.0f} units = {cad_per_pip:.4f}, "
              f"net CAD/yr = {total_net_pips * cad_per_pip:+,.0f} "
              f"(gross {total_gross_pips * cad_per_pip:+,.0f}), "
              f"net+costs = {total_net_all_costs_pips * cad_per_pip:+,.0f}")

    RESULTS_PATH.write_text(json.dumps(
        {"combos": all_results, "pair_agg": pair_agg, "span_years": span_years},
        indent=1, default=str))
    print(f"\nresults saved -> {RESULTS_PATH}")


if __name__ == "__main__":
    main()
