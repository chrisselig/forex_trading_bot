"""Spec 17 Phases B & C — ambient bracket strategy under MEASURED spreads.

Phase B:
  - Simulate the 50/70/10 bracket on ~200 sampled non-event days per pair
    (same day list as Phase A, scripts/mc_spread_profile.py), at four
    session anchors (03:00 / 09:00 / 14:00 / 20:00 UTC), charging each
    trade its MEASURED spread from the Phase A tick profile:
    per (pair, anchor, year) p75 as base case, p95 as stress.
  - Re-run the true event windows (report 16 Run C) under the identical
    measured-spread cost model (event mapped to nearest anchor-hour
    profile by its UTC hour) for a fair event-vs-ambient comparison.
  - Parameter grid around 50/70/10 (distance {35,50,65} x TP {50,70,90}
    x SL {10,15}) with walk-forward (train 2020-2024, test 2025-2026).

Phase C:
  - Portfolio design points: one bracket per pair per anchor per day,
    no concurrent trades in the same pair, max hold 6h.
  - Aggregate stats per design: E/trade, E/year, Sharpe, bootstrap path
    max drawdown, yearly sub-period table, pair correlation.
  - Margin reality on a ~$4.9K CAD account at the 25%-of-AvailableFunds
    per-order cap.
  - Vol-regime terciles (prior-day realized vol; see note below).

Cost model note: simulate_bracket() mirrors report 16's
simulate_straddle() exactly (verified by assertion in --selftest):
entry stops are shifted spread/2 away from mid, i.e. the same convention
under which report 16's flat 25/30 numbers were produced — only the
spread VALUE changes, from assumed-flat to measured.

Vol proxy note: the dukascopy daily CSVs carry close only (no H/L), so
"prior-day ATR" is implemented as the 5-day rolling std of daily log
returns ending on the prior day. Documented in report 17.

Data: full-day 1-min bid bars (01:00-24:00 UTC) fetched per sampled day
into scripts/data/_cache/ambient1m/{PAIR}/. Fetches use tz-AWARE UTC
datetimes only (naive datetimes are read as system-local — the report 16
catastrophic bug).

Usage:
    python scripts/mc_ambient_bracket.py --download --limit 100
    python scripts/mc_ambient_bracket.py --selftest
    python scripts/mc_ambient_bracket.py --phase-b
    python scripts/mc_ambient_bracket.py --grid
    python scripts/mc_ambient_bracket.py --phase-c
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent))

from mc_spread_profile import (  # noqa: E402
    ANCHORS_UTC,
    PAIRS,
    PIP_SIZES,
    TICK_CACHE_DIR,
    load_all_ticks,
    sample_days_extended,
)
from monte_carlo_dukascopy import bootstrap_metrics, simulate_straddle  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "scripts" / "data"
DUKA_DIR = DATA_DIR / "dukascopy"
BAR_CACHE_DIR = DATA_DIR / "_cache" / "ambient1m"
RESULTS_PATH = DATA_DIR / "ambient_bracket_results.json"

DUKASCOPY_INSTRUMENTS = {"USDZAR": "USD/ZAR", "USDTRY": "USD/TRY"}
REPORT16_ASSUMED_SPREAD = {"USDZAR": 25.0, "USDTRY": 30.0}
# Real IBKR IDEALPRO entry_spread_pips means from the trade journal
# (data/forex_bot.db orders table; see mc_spread_profile.py calibration).
# The actual cost the bot pays — far tighter than Dukascopy's retail feed.
JOURNAL_MEAN_SPREAD = {"USDZAR": 23.5, "USDTRY": 12.1}

FETCH_START_HOUR = 1   # 03:00 anchor needs -2h
# Report 16 Run D used a [anchor-2h, anchor+4h] window, placed the straddle
# at anchor-30min, and held to window end (~4.5h from entry, < 6h). We
# mirror that exactly: MAX_HOLD_MIN is set large enough never to bind before
# the window edge, so the window (not this cap) bounds the hold — identical
# to simulate_straddle() on the same window (verified by --selftest).
WINDOW_PRE_H = 2
WINDOW_POST_H = 4
MAX_HOLD_MIN = 720
REQUEST_DELAY_SECS = 0.3

# Production US event set for each pair (report 16 verdict table)
EVENT_SCOPE = {
    "USDZAR": ["NFP", "CPI", "FOMC", "PPI", "GDP", "SARB Rate Decision",
               "South Africa CPI"],
    "USDTRY": ["NFP", "CPI", "FOMC", "PPI", "GDP", "PCE", "TCMB Rate Decision",
               "Unemployment Claims", "ISM Manufacturing PMI", "Retail Sales"],
}

GRID_DIST = [35.0, 50.0, 65.0]
GRID_TP = [50.0, 70.0, 90.0]
GRID_SL = [10.0, 15.0]

# ---------------------------------------------------------------------------
# Spread model (from Phase A tick cache)
# ---------------------------------------------------------------------------


class SpreadModel:
    """Measured spread lookup: (pair, anchor, year) -> {median,p75,p95} pips.

    Falls back to the pair+anchor all-year profile when a (year, anchor)
    cell is missing, and raises loudly if a pair has no tick data at all.
    """

    def __init__(self) -> None:
        self.by_cell: dict[tuple[str, str, int], dict[str, float]] = {}
        self.by_anchor: dict[tuple[str, str], dict[str, float]] = {}
        for pair in PAIRS:
            df = load_all_ticks(pair)
            if df.empty:
                raise RuntimeError(
                    f"No tick data cached for {pair} under {TICK_CACHE_DIR} — "
                    "run mc_spread_profile.py --download first"
                )
            for (anchor, year), g in df.groupby(["anchor", "year"]):
                self.by_cell[(pair, anchor, int(year))] = {
                    "median": float(g["spread_pips"].median()),
                    "p75": float(g["spread_pips"].quantile(0.75)),
                    "p95": float(g["spread_pips"].quantile(0.95)),
                }
            for anchor, g in df.groupby("anchor"):
                self.by_anchor[(pair, anchor)] = {
                    "median": float(g["spread_pips"].median()),
                    "p75": float(g["spread_pips"].quantile(0.75)),
                    "p95": float(g["spread_pips"].quantile(0.95)),
                }

    def get(self, pair: str, anchor: str, year: int, q: str) -> float:
        cell = self.by_cell.get((pair, anchor, year))
        if cell is None:
            cell = self.by_anchor[(pair, anchor)]
        return cell[q]

    def nearest_anchor(self, hour_utc: int) -> str:
        anchor_hours = [int(a[:2]) for a in ANCHORS_UTC]
        best = min(anchor_hours, key=lambda h: min(abs(hour_utc - h), 24 - abs(hour_utc - h)))
        return f"{best:02d}:00"


# ---------------------------------------------------------------------------
# 1-min full-day bar download (resume-safe per-day cache)
# ---------------------------------------------------------------------------


def bar_path(pair: str, day: str) -> Path:
    return BAR_CACHE_DIR / pair / f"{day}.csv"


def download_bars(pair: str, limit: int | None) -> None:
    import dukascopy_python as dp

    days = sample_days_extended(pair)
    out_dir = BAR_CACHE_DIR / pair
    out_dir.mkdir(parents=True, exist_ok=True)

    todo = [d for d in days if not bar_path(pair, d).exists()]
    logger.info(f"[{pair}] {len(todo)} day(s) of 1-min bars remaining")
    if limit is not None:
        todo = todo[:limit]

    instrument = DUKASCOPY_INSTRUMENTS[pair]
    total_bytes = 0
    fetched = failed = 0
    for i, day in enumerate(todo, 1):
        d0 = datetime.fromisoformat(day)
        start = d0.replace(hour=FETCH_START_HOUR, tzinfo=UTC)
        end = (d0 + timedelta(days=1)).replace(hour=0, tzinfo=UTC)
        try:
            df = dp.fetch(instrument, dp.INTERVAL_MIN_1, dp.OFFER_SIDE_BID, start, end)
        except Exception as exc:  # noqa: BLE001 — analysis script, LOUD, keep going
            logger.error(f"[{pair}] {day}: fetch failed: {exc}")
            failed += 1
            continue
        if df is None or df.empty:
            logger.warning(f"[{pair}] {day}: no bars returned")
            failed += 1
            continue
        df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        path = bar_path(pair, day)
        df.to_csv(path)
        total_bytes += path.stat().st_size
        fetched += 1
        if i % 25 == 0:
            logger.info(f"[{pair}] {i}/{len(todo)} fetched this run")
        time.sleep(REQUEST_DELAY_SECS)
    logger.info(
        f"[{pair}] bars run done: {fetched} fetched, {failed} failed, "
        f"{total_bytes / 1e6:.2f} MB written this run"
    )


def load_day_bars(pair: str, day: str) -> pd.DataFrame | None:
    path = bar_path(pair, day)
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    return df


def cached_days(pair: str) -> list[str]:
    return sorted(p.stem for p in (BAR_CACHE_DIR / pair).glob("*.csv"))


# ---------------------------------------------------------------------------
# Bracket simulator (mirrors monte_carlo_dukascopy.simulate_straddle but
# returns entry/exit bar times for portfolio overlap logic)
# ---------------------------------------------------------------------------


def simulate_bracket(
    bars: pd.DataFrame,
    anchor_dt: datetime,
    pair: str,
    distance: float,
    tp: float,
    sl: float,
    spread_pips: float,
) -> list[dict]:
    """One straddle bracket. Same mechanics as simulate_straddle():
    entry stops at mid +/- (distance + spread/2), 7:1-style TP/SL from the
    entry, OHLC open-proximity tie-break, max hold MAX_HOLD_MIN minutes.
    Returns one dict per triggered leg with pnl and entry/exit times.
    """
    pip = PIP_SIZES[pair]
    idx = bars.index
    window = bars[(idx >= anchor_dt - timedelta(hours=WINDOW_PRE_H)) &
                  (idx <= anchor_dt + timedelta(hours=WINDOW_POST_H))]
    if len(window) < 60:
        return []
    times = window.index
    # entry bar = closest to anchor - 30min (mirror PRE_EVENT_MINUTES)
    pre_idx = int(np.argmin(np.abs(times - (anchor_dt - timedelta(minutes=30)))))
    if pre_idx >= len(window) - 10:
        return []
    pre_bar = window.iloc[pre_idx]
    mid = (pre_bar["high"] + pre_bar["low"]) / 2
    s2 = spread_pips * pip / 2

    vals = window[["open", "high", "low", "close"]].values
    n = len(vals)
    out = []
    for leg, entry, sl_px, tp_px in [
        ("BUY", mid + distance * pip + s2,
         mid + distance * pip + s2 - sl * pip, mid + distance * pip + s2 + tp * pip),
        ("SELL", mid - distance * pip - s2,
         mid - distance * pip - s2 + sl * pip, mid - distance * pip - s2 - tp * pip),
    ]:
        trig = None
        max_bar = min(n, pre_idx + MAX_HOLD_MIN)
        for i in range(pre_idx, max_bar):
            _, h, lo, _ = vals[i]
            if (leg == "BUY" and h >= entry) or (leg == "SELL" and lo <= entry):
                trig = i
                break
        if trig is None:
            continue
        outcome = "TIMEOUT"
        exit_i = min(trig + MAX_HOLD_MIN, n - 1)
        exit_px = vals[exit_i][3]
        for i in range(trig + 1, min(n, trig + MAX_HOLD_MIN)):
            o, h, lo, _ = vals[i]
            if leg == "BUY":
                hit_sl, hit_tp = lo <= sl_px, h >= tp_px
            else:
                hit_sl, hit_tp = h >= sl_px, lo <= tp_px
            if hit_sl and hit_tp:
                if abs(o - sl_px) <= abs(o - tp_px):
                    outcome, exit_px = "SL", sl_px
                else:
                    outcome, exit_px = "TP", tp_px
                exit_i = i
                break
            if hit_sl:
                outcome, exit_px, exit_i = "SL", sl_px, i
                break
            if hit_tp:
                outcome, exit_px, exit_i = "TP", tp_px, i
                break
        pnl = ((exit_px - entry) if leg == "BUY" else (entry - exit_px)) / pip
        out.append({
            "leg": leg, "pnl_pips": float(pnl), "outcome": outcome,
            "entry_time": times[trig], "exit_time": times[exit_i],
        })
    return out


def selftest() -> None:
    """simulate_bracket must reproduce simulate_straddle P&L on real data."""
    n_checked = 0
    for pair in PAIRS:
        for day in cached_days(pair)[:40]:
            bars = load_day_bars(pair, day)
            if bars is None or len(bars) < 200:
                continue
            for hhmm in ANCHORS_UTC:
                hh = int(hhmm[:2])
                anchor = datetime.fromisoformat(day).replace(hour=hh)
                mine = simulate_bracket(bars, anchor, pair, 50, 70, 10, 25.0)
                w = bars[(bars.index >= anchor - timedelta(hours=WINDOW_PRE_H)) &
                         (bars.index <= anchor + timedelta(hours=WINDOW_POST_H))]
                if len(w) < 60:
                    continue
                theirs = [
                    t for t in simulate_straddle(
                        w, anchor.isoformat(), pair, 50, 70, 10, spread_pips=25.0)
                    if t.triggered
                ]
                a = sorted(round(t["pnl_pips"], 4) for t in mine)
                b = sorted(round(t.pnl_pips, 4) for t in theirs)
                assert a == b, f"MISMATCH {pair} {day} {hhmm}: {a} vs {b}"
                n_checked += 1
    print(f"selftest OK — {n_checked} bracket windows matched simulate_straddle exactly")


# ---------------------------------------------------------------------------
# Phase B — ambient sims at measured spreads; event windows re-run
# ---------------------------------------------------------------------------


def ambient_trades(
    pair: str,
    model: SpreadModel,
    q: str,
    dist: float = 50,
    tp: float = 70,
    sl: float = 10,
    years: set[int] | None = None,
    flat_spread: float | None = None,
) -> pd.DataFrame:
    """All ambient bracket trades for a pair (every sampled day x anchor).
    q: 'median'|'p75'|'p95' measured quantile; flat_spread overrides model.
    """
    rows = []
    for day in cached_days(pair):
        year = int(day[:4])
        if years is not None and year not in years:
            continue
        bars = load_day_bars(pair, day)
        if bars is None or len(bars) < 120:
            continue
        for hhmm in ANCHORS_UTC:
            hh = int(hhmm[:2])
            anchor = datetime.fromisoformat(day).replace(hour=hh)
            spread = (flat_spread if flat_spread is not None
                      else model.get(pair, hhmm, year, q))
            for t in simulate_bracket(bars, anchor, pair, dist, tp, sl, spread):
                rows.append({
                    "pair": pair, "day": day, "year": year, "anchor": hhmm,
                    "spread_used": spread, **t,
                })
    return pd.DataFrame(rows)


def load_event_groups(pair: str) -> dict:
    df = pd.read_csv(DUKA_DIR / f"{pair}_1min.csv", index_col=0, parse_dates=True)
    groups = {}
    for (event_date, event_name), g in df.groupby(["event_date", "event_name"]):
        bars = g[["open", "high", "low", "close", "volume"]].sort_index()
        groups[f"{event_date}_{event_name}"] = {
            "bars": bars, "event_name": event_name, "event_date": event_date,
            "event_utc": g["event_utc"].iloc[0],
        }
    return groups


def event_trades(
    pair: str,
    model: SpreadModel,
    q: str,
    dist: float = 50,
    tp: float = 70,
    sl: float = 10,
    flat_spread: float | None = None,
) -> pd.DataFrame:
    """Report 16 Run C (true event windows) under the measured-spread model.
    Each event is charged the measured spread of its nearest anchor hour
    (by event UTC hour) for its year.
    """
    groups = load_event_groups(pair)
    scope = set(EVENT_SCOPE[pair])
    rows = []
    for v in groups.values():
        if v["event_name"] not in scope:
            continue
        bars = v["bars"]
        if len(bars) < 60:
            continue
        evt = datetime.fromisoformat(v["event_utc"])
        anchor = model.nearest_anchor(evt.hour)
        spread = (flat_spread if flat_spread is not None
                  else model.get(pair, anchor, evt.year, q))
        trades = simulate_straddle(
            bars, v["event_utc"], pair, dist, tp, sl, spread_pips=spread)
        for t in trades:
            if t.triggered:
                rows.append({
                    "pair": pair, "day": v["event_date"], "year": evt.year,
                    "anchor": anchor, "event_name": v["event_name"],
                    "spread_used": spread, "leg": t.leg, "pnl_pips": t.pnl_pips,
                    "outcome": t.outcome,
                })
    return pd.DataFrame(rows)


def fmt_m(m: dict | None) -> str:
    if m is None or m["n_trades"] == 0:
        return "no trades"
    return (f"E={m['mean_pnl']:+6.2f} CI=[{m['ci_low']:+6.2f},{m['ci_high']:+6.2f}] "
            f"WR={m['win_rate'] * 100:4.1f}% Sh={m['sharpe']:+5.2f} N={m['n_trades']}")


def metrics_of(df: pd.DataFrame, cost_frac: float = 0.0) -> dict | None:
    """Metrics on triggered-trade P&L, optionally charging spread as cost.

    Report 16's bracket model shifts the entry-trigger level by spread/2
    (buy_stop = mid + distance + spread/2) but then measures TP/SL FROM
    that entry, so realized pip P&L is exactly +tp / -sl / timeout and
    never reflects the spread magnitude. Empirically E[P&L] RISES with a
    wider spread (the wider trigger selects stronger breakouts and N
    falls). So report 16's model charges NO net spread cost on realized
    P&L — only a trigger-gating effect. `cost_frac` deducts
    cost_frac * spread_used pips per trade as an explicit round-trip cost:
      cost_frac=0.0 -> report 16's model (what reports 04-16 used)
      cost_frac=1.0 -> one full spread per round trip (the standard
                       conservative backtest convention, and what report
                       16's prose *claimed* it charged)
    """
    if df.empty:
        return None
    pnl = df["pnl_pips"].to_numpy()
    if cost_frac:
        pnl = pnl - cost_frac * df["spread_used"].to_numpy()
    return bootstrap_metrics(pnl)


def phase_b(model: SpreadModel) -> dict:
    """Two cost models are reported side by side:
      [r16]  = report 16's mechanic (entry-side half-spread only)
      [full] = honest full round-trip (also deduct exit-side half-spread)
    'measured' spreads are Dukascopy tick p75/p95; 'ibkr' uses the real
    journal mean spread (the cost the bot actually pays) as a flat value.
    """
    results: dict = {}
    for pair in PAIRS:
        print(f"\n================ {pair} — Phase B (50/70/10) ================")
        print("  [r16]=report 16 model (no net spread cost)  "
              "[full]=minus 1 full spread/round-trip")
        pair_res: dict = {}
        spread_variants = [
            ("flat_r16_25/30", {"q": "p75", "flat_spread": REPORT16_ASSUMED_SPREAD[pair]}),
            ("ibkr_journal", {"q": "p75", "flat_spread": JOURNAL_MEAN_SPREAD[pair]}),
            ("duka_median", {"q": "median"}),
            ("duka_p75", {"q": "p75"}),
            ("duka_p95", {"q": "p95"}),
        ]
        for label, kwargs in spread_variants:
            adf = ambient_trades(pair, model, **kwargs)
            m = metrics_of(adf)
            mf = metrics_of(adf, cost_frac=1.0)
            pair_res[f"ambient_{label}"] = m
            pair_res[f"ambient_{label}_full"] = mf
            print(f"  ambient {label:15s} [r16]  {fmt_m(m)}")
            print(f"  ambient {label:15s} [full] {fmt_m(mf)}")
        # per-anchor at duka p75 (r16 model) to show session structure
        adf75 = ambient_trades(pair, model, q="p75")
        for hhmm in ANCHORS_UTC:
            sub = adf75[adf75["anchor"] == hhmm]
            ma = metrics_of(sub)
            pair_res[f"ambient_duka_p75_a{hhmm}"] = ma
            print(f"      anchor {hhmm} [r16]: {fmt_m(ma)}")
        for label, kwargs in spread_variants:
            edf = event_trades(pair, model, **kwargs)
            m = metrics_of(edf)
            mf = metrics_of(edf, cost_frac=1.0)
            pair_res[f"event_{label}"] = m
            pair_res[f"event_{label}_full"] = mf
            print(f"  event   {label:15s} [r16]  {fmt_m(m)}")
            print(f"  event   {label:15s} [full] {fmt_m(mf)}")
        results[pair] = pair_res
    return results


def phase_b_grid(model: SpreadModel) -> dict:
    """18-cell grid at p75 measured spreads + WF train 2020-2024 / test 2025-26."""
    train_years = {2020, 2021, 2022, 2023, 2024}
    test_years = {2025, 2026}
    out: dict = {}
    for pair in PAIRS:
        print(f"\n================ {pair} — grid @ p75 measured (train 2020-24) ================")
        cells = []
        for dist in GRID_DIST:
            for tp in GRID_TP:
                for sl in GRID_SL:
                    tr = ambient_trades(pair, model, "p75", dist, tp, sl,
                                        years=train_years)
                    m = metrics_of(tr)
                    if m is None:
                        continue
                    cells.append({"dist": dist, "tp": tp, "sl": sl, **m})
                    print(f"  {dist:2.0f}/{tp:2.0f}/{sl:2.0f}: {fmt_m(m)}")
        cells.sort(key=lambda c: c["ci_low"], reverse=True)
        best = cells[0]
        print(f"  train-best by CI-low: {best['dist']:.0f}/{best['tp']:.0f}/{best['sl']:.0f}")
        tb_test = ambient_trades(pair, model, "p75", best["dist"], best["tp"],
                                 best["sl"], years=test_years)
        cfg_p75_test = ambient_trades(pair, model, "p75", 50, 70, 10, years=test_years)
        cfg_p95_test = ambient_trades(pair, model, "p95", 50, 70, 10, years=test_years)
        cfg_ibkr_test = ambient_trades(pair, model, "p75", 50, 70, 10,
                                       years=test_years,
                                       flat_spread=JOURNAL_MEAN_SPREAD[pair])
        oos = {
            "oos_train_best_r16": metrics_of(tb_test),
            "oos_cfg_p75_r16": metrics_of(cfg_p75_test),
            "oos_cfg_p95_r16": metrics_of(cfg_p95_test),
            "oos_cfg_p75_full": metrics_of(cfg_p75_test, cost_frac=1.0),
            "oos_cfg_p95_full": metrics_of(cfg_p95_test, cost_frac=1.0),
            "oos_cfg_ibkr_full": metrics_of(cfg_ibkr_test, cost_frac=1.0),
        }
        print(f"  WF OOS train-best [r16]:      {fmt_m(oos['oos_train_best_r16'])}")
        print(f"  WF OOS 50/70/10 @p75  [r16]:  {fmt_m(oos['oos_cfg_p75_r16'])}")
        print(f"  WF OOS 50/70/10 @p95  [r16]:  {fmt_m(oos['oos_cfg_p95_r16'])}")
        print(f"  WF OOS 50/70/10 @p75  [full]: {fmt_m(oos['oos_cfg_p75_full'])}")
        print(f"  WF OOS 50/70/10 @p95  [full]: {fmt_m(oos['oos_cfg_p95_full'])}")
        print(f"  WF OOS 50/70/10 @ibkr [full]: {fmt_m(oos['oos_cfg_ibkr_full'])}")
        out[pair] = {"train_cells": cells, "train_best": best, **oos}
    return out


# ---------------------------------------------------------------------------
# Phase C — portfolio design
# ---------------------------------------------------------------------------


def portfolio_trades(pair: str, model: SpreadModel, q: str,
                     anchors: list[str]) -> pd.DataFrame:
    """Ambient trades with the no-concurrent-same-pair constraint applied:
    anchors processed in order; an anchor is skipped when a leg of a prior
    bracket on the same pair/day is still open at bracket placement time
    (anchor - 30min)."""
    rows = []
    for day in cached_days(pair):
        year = int(day[:4])
        bars = load_day_bars(pair, day)
        if bars is None or len(bars) < 120:
            continue
        open_until: datetime | None = None
        for hhmm in anchors:
            hh = int(hhmm[:2])
            anchor = datetime.fromisoformat(day).replace(hour=hh)
            if open_until is not None and anchor - timedelta(minutes=30) < open_until:
                continue
            spread = model.get(pair, hhmm, year, q)
            trades = simulate_bracket(bars, anchor, pair, 50, 70, 10, spread)
            for t in trades:
                rows.append({
                    "pair": pair, "day": day, "year": year, "anchor": hhmm,
                    "spread_used": spread, **t,
                })
            if trades:
                latest = max(t["exit_time"] for t in trades)
                latest = latest.to_pydatetime() if hasattr(latest, "to_pydatetime") else latest
                open_until = max(open_until or latest, latest)
    return pd.DataFrame(rows)


def bootstrap_path_dd(daily_pnl: np.ndarray, n_boot: int = 2000) -> dict:
    """Bootstrap resampled equity paths -> max drawdown percentiles (pips)."""
    rng = np.random.default_rng(7)
    n = len(daily_pnl)
    dds = np.empty(n_boot)
    for b in range(n_boot):
        path = np.cumsum(daily_pnl[rng.integers(0, n, n)])
        peak = np.maximum.accumulate(path)
        dds[b] = np.max(peak - path)
    return {"dd_p50": float(np.percentile(dds, 50)),
            "dd_p95": float(np.percentile(dds, 95))}


def vol_terciles(pair: str, days: list[str]) -> dict[str, str]:
    """Map sampled day -> vol tercile using 5-day rolling std of daily log
    returns ending on the PRIOR day (close-only daily data; ATR proxy)."""
    d = pd.read_csv(DUKA_DIR / f"{pair}_daily.csv", parse_dates=["timestamp"])
    d = d.set_index("timestamp").sort_index()
    ret = np.log(d["close"]).diff()
    vol = ret.rolling(5).std().shift(1)  # ends on prior day
    vols = {}
    for day in days:
        ts = pd.Timestamp(day)
        window = vol.loc[:ts]
        if window.empty or pd.isna(window.iloc[-1]):
            continue
        vols[day] = float(window.iloc[-1])
    if not vols:
        return {}
    s = pd.Series(vols)
    q1, q2 = s.quantile([1 / 3, 2 / 3])
    return {d: ("low" if v <= q1 else "mid" if v <= q2 else "high")
            for d, v in s.items()}


def summarize_design(name: str, dfs: list[pd.DataFrame],
                     trading_days_per_year: float = 252.0) -> dict:
    """Aggregate a design point (list of per-pair trade frames)."""
    all_t = pd.concat(dfs, ignore_index=True)
    all_t = all_t.assign(pnl_net=all_t["pnl_pips"] - all_t["spread_used"])
    n_days_sampled = all_t.groupby("pair")["day"].nunique().mean()
    m = bootstrap_metrics(all_t["pnl_pips"].to_numpy())
    mnet = bootstrap_metrics(all_t["pnl_net"].to_numpy())
    # daily portfolio pnl over union of sampled days (report-16 model)
    daily = all_t.groupby("day")["pnl_pips"].sum()
    daily_net = all_t.groupby("day")["pnl_net"].sum()
    trades_per_sampled_day = len(all_t) / max(daily.shape[0], 1)
    trades_per_year = trades_per_sampled_day * trading_days_per_year
    e_year = float(daily.mean()) * trading_days_per_year
    e_year_net = float(daily_net.mean()) * trading_days_per_year
    dd = bootstrap_path_dd(daily.to_numpy())
    dd_net = bootstrap_path_dd(daily_net.to_numpy())
    d_std = daily.std(ddof=1)
    ann_sharpe = float(daily.mean() / d_std * np.sqrt(trading_days_per_year)) if d_std > 0 else 0.0
    yearly = {
        int(y): {"E_trade": float(g["pnl_pips"].mean()),
                 "E_trade_net": float(g["pnl_net"].mean()), "n": int(len(g))}
        for y, g in all_t.groupby("year")
    }
    return {
        "name": name, "n_trades_sampled": int(len(all_t)),
        "n_days_sampled": float(n_days_sampled),
        "E_trade": m["mean_pnl"], "ci_low": m["ci_low"], "ci_high": m["ci_high"],
        "E_trade_net": mnet["mean_pnl"], "ci_low_net": mnet["ci_low"],
        "ci_high_net": mnet["ci_high"], "sharpe_trade": m["sharpe"],
        "sharpe_trade_net": mnet["sharpe"], "win_rate": m["win_rate"],
        "trades_per_year": float(trades_per_year),
        "E_year_pips": e_year, "E_year_pips_net": e_year_net,
        "ann_sharpe_daily": ann_sharpe,
        "dd_p50_pips": dd["dd_p50"], "dd_p95_pips": dd["dd_p95"],
        "dd_p95_pips_net": dd_net["dd_p95"],
        "yearly": yearly,
    }


def phase_c(model: SpreadModel) -> dict:
    print("\n================ Phase C — portfolio design ================")
    designs: dict[str, dict[str, list[str]]] = {
        "D1 both pairs, all 4 anchors": {p: list(ANCHORS_UTC) for p in PAIRS},
        "D2 both pairs, 14:00 only": {p: ["14:00"] for p in PAIRS},
        "D3 both pairs, 09:00+14:00": {p: ["09:00", "14:00"] for p in PAIRS},
        "D4 USDZAR only, all 4": {"USDZAR": list(ANCHORS_UTC)},
        "D5 USDTRY only, all 4": {"USDTRY": list(ANCHORS_UTC)},
    }
    out: dict = {}
    frames_cache: dict[tuple[str, tuple[str, ...], str], pd.DataFrame] = {}

    def get_frame(pair: str, anchors: list[str], q: str) -> pd.DataFrame:
        key = (pair, tuple(anchors), q)
        if key not in frames_cache:
            frames_cache[key] = portfolio_trades(pair, model, q, anchors)
        return frames_cache[key]

    for name, spec in designs.items():
        for q in ("p75", "p95"):
            dfs = [get_frame(p, a, q) for p, a in spec.items()]
            s = summarize_design(f"{name} @{q}", dfs)
            out[f"{name}|{q}"] = s
            print(f"\n  {name} @ {q}:")
            print(f"    [r16]  E/trade={s['E_trade']:+.2f} "
                  f"CI=[{s['ci_low']:+.2f},{s['ci_high']:+.2f}] "
                  f"Sh={s['sharpe_trade']:.2f} WR={s['win_rate'] * 100:.1f}%")
            print(f"    [full] E/trade={s['E_trade_net']:+.2f} "
                  f"CI=[{s['ci_low_net']:+.2f},{s['ci_high_net']:+.2f}] "
                  f"Sh={s['sharpe_trade_net']:.2f}  (minus 1 full spread/trade)")
            print(f"    trades/yr~{s['trades_per_year']:.0f} "
                  f"E/yr[r16]~{s['E_year_pips']:+.0f} E/yr[full]~{s['E_year_pips_net']:+.0f} pips "
                  f"annSh(daily)={s['ann_sharpe_daily']:.2f} "
                  f"DD95[r16]/[full]={s['dd_p95_pips']:.0f}/{s['dd_p95_pips_net']:.0f}")
            ys = " ".join(f"{y}:{v['E_trade']:+.1f}/{v['E_trade_net']:+.1f}(n={v['n']})"
                          for y, v in sorted(s["yearly"].items()))
            print(f"    yearly E/trade [r16]/[full]: {ys}")

    # pair correlation of daily pnl (D1 p75)
    z = get_frame("USDZAR", list(ANCHORS_UTC), "p75").groupby("day")["pnl_pips"].sum()
    t = get_frame("USDTRY", list(ANCHORS_UTC), "p75").groupby("day")["pnl_pips"].sum()
    both = pd.concat([z.rename("zar"), t.rename("try")], axis=1).dropna()
    corr = float(both["zar"].corr(both["try"])) if len(both) > 10 else float("nan")
    out["pair_daily_corr_p75"] = {"corr": corr, "n_common_days": int(len(both))}
    print(f"\n  pair daily-P&L correlation (common sampled days, p75): "
          f"r={corr:.3f} (n={len(both)})")

    # vol terciles (D1 p75, per pair)
    for pair in PAIRS:
        f = get_frame(pair, list(ANCHORS_UTC), "p75")
        terc = vol_terciles(pair, sorted(f["day"].unique()))
        f = f.assign(tercile=f["day"].map(terc))
        print(f"\n  {pair} vol-regime terciles (prior-day 5d realized vol, p75 spreads):")
        tres = {}
        for lab in ("low", "mid", "high"):
            sub = f[f["tercile"] == lab]
            m = metrics_of(sub)
            mf = metrics_of(sub, cost_frac=1.0)
            tres[lab] = m
            tres[f"{lab}_full"] = mf
            print(f"    {lab:4s} [r16]:  {fmt_m(m)}")
            print(f"    {lab:4s} [full]: {fmt_m(mf)}")
        out[f"terciles_{pair}"] = tres
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Spec 17 Phases B & C")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--phase-b", action="store_true")
    parser.add_argument("--grid", action="store_true")
    parser.add_argument("--phase-c", action="store_true")
    args = parser.parse_args()

    if args.download:
        for pair in PAIRS:
            download_bars(pair, args.limit)
        return
    if args.selftest:
        selftest()
        return

    model = SpreadModel()
    results: dict = {}
    if RESULTS_PATH.exists():
        results = json.loads(RESULTS_PATH.read_text())
    if args.phase_b:
        results["phase_b"] = phase_b(model)
    if args.grid:
        results["grid"] = phase_b_grid(model)
    if args.phase_c:
        results["phase_c"] = phase_c(model)
    if args.phase_b or args.grid or args.phase_c:
        RESULTS_PATH.write_text(json.dumps(results, indent=1, default=str))
        print(f"\nresults saved -> {RESULTS_PATH}")
        return
    parser.print_help()


if __name__ == "__main__":
    main()
