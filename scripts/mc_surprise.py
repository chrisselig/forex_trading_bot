#!/usr/bin/env python3
"""
MC Validation of Post-News Surprise Strategy (Spec 15, Phase 2b)
================================================================

Backtests the production ``SurpriseStrategy`` (src/forex_bot/strategy/
surprise.py): after a data release, trade in the direction of the surprise
(market entry, TP/SL bracket), only when |surprise| exceeds a threshold.

Two surprise definitions are tested:

1. **Primary** -- an exact replication of ``EconomicEvent.surprise_pct``
   (src/forex_bot/models/events.py): percentage deviation of actual from
   forecast, with the K/M/B/% suffix parsing chain, and the production
   unemployment-indicator sign inversion from surprise.py.
2. **Z-score** -- standardized surprise: (actual - forecast) in native
   units divided by the expanding standard deviation of that difference
   over all PRIOR releases of the same event type (min 8 priors; no
   look-ahead). Thresholds in sigma units.

Grid (per spec):
  entry delay N in {1, 2, 5} minutes after release
  threshold in {0, 5, 10, 20, 50} %% (primary) / {0.5, 1.0, 1.5} sigma (z)
  TP in {15, 25, 40, 70} pips x SL in {10, 15, 25} pips
  time-stop in {30, 60} minutes (exit at bar close)
  Intra-bar TP-vs-SL ambiguity: pessimistic, SL first.
  Costs: per-pair event-time spread (same model as prior MC reports),
  swept at 1.0x-4.0x multipliers.

Monte Carlo: bootstrap event P&L 10,000x -> E[P&L] pips, 95%% CI, Sharpe.
Walk-forward: train 2020-2024 (select best params by pessimistic CI-low),
test 2025-2026 out-of-sample.

Bar data
--------
The existing scripts/data/dukascopy/*_1min.csv files CANNOT be used: their
download requested naive-UTC windows that dukascopy_python interpreted as
LOCAL (America/Edmonton) time, so every stored window actually covers
[release+4h .. release+8.5h] (verified against a fresh tz-aware fetch:
the 2023-02-03 NFP burst at 13:30 UTC is absent from the stored window
18:30-22:00 UTC). This script therefore fetches its own 1-min windows
[release-10min, release+130min] with explicitly tz-aware UTC datetimes,
cached per event under scripts/data/_cache/mc_surprise_bars/.

Usage:
  ~/anaconda3/envs/forex-bot/bin/python scripts/mc_surprise.py --fetch-bars
  ~/anaconda3/envs/forex-bot/bin/python scripts/mc_surprise.py --run
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

UTC = timezone.utc

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "scripts" / "data"
FF_HISTORY_CSV = DATA_DIR / "ff_history.csv"
BARS_CACHE = DATA_DIR / "_cache" / "mc_surprise_bars"
BARS_CACHE.mkdir(parents=True, exist_ok=True)
RESULTS_JSON = DATA_DIR / "mc_surprise_results.json"

PIP_SIZES = {"USDZAR": 0.0001, "USDTRY": 0.0001, "AUDUSD": 0.0001}

# Same per-pair event-time spread model as monte_carlo_dukascopy.py
EVENT_SPREAD_PIPS = {"USDZAR": 25.0, "USDTRY": 30.0, "AUDUSD": 2.0}

DUKASCOPY_INSTRUMENTS = {"USDZAR": "USD/ZAR", "USDTRY": "USD/TRY", "AUDUSD": "AUD/USD"}

# Event types -> FF titles in ff_history.csv + applicable pairs (config/events.yaml)
EVENT_GROUPS: dict[str, dict] = {
    "NFP": {"titles": ["Non-Farm Employment Change"], "pairs": ["USDZAR", "USDTRY", "AUDUSD"]},
    "CPI": {"titles": ["CPI m/m"], "pairs": ["USDZAR", "USDTRY", "AUDUSD"]},
    "FOMC": {"titles": ["Federal Funds Rate"], "pairs": ["USDZAR", "USDTRY", "AUDUSD"]},
    "PPI": {"titles": ["PPI m/m"], "pairs": ["USDZAR", "USDTRY", "AUDUSD"]},
    "GDP": {"titles": ["Advance GDP q/q", "Prelim GDP q/q", "Final GDP q/q"], "pairs": ["USDZAR", "USDTRY", "AUDUSD"]},
    "PCE": {"titles": ["Core PCE Price Index m/m"], "pairs": ["USDTRY", "AUDUSD"]},
    "Claims": {"titles": ["Unemployment Claims"], "pairs": ["USDTRY"]},
    "ISM": {"titles": ["ISM Manufacturing PMI"], "pairs": ["USDTRY"]},
    "Retail": {"titles": ["Retail Sales m/m"], "pairs": ["USDTRY"]},
}

# Grid (per spec)
ENTRY_DELAYS = [1, 2, 5]              # minutes after release
THRESHOLDS_PRIMARY = [0.0, 5.0, 10.0, 20.0, 50.0]   # |surprise_pct| >=
THRESHOLDS_ZSCORE = [0.5, 1.0, 1.5]                  # |z| >=
TP_GRID = [15.0, 25.0, 40.0, 70.0]
SL_GRID = [10.0, 15.0, 25.0]
TIME_STOPS = [30, 60]                 # minutes after entry
SPREAD_MULTIPLIERS = [1.0, 1.5, 2.0, 3.0, 4.0]

N_BOOTSTRAP = 10_000
CONFIDENCE_LEVEL = 0.95
MIN_Z_HISTORY = 8
Z_WINDOW = 24  # trailing releases used for the z-score sigma

TRAIN_YEARS = {2020, 2021, 2022, 2023, 2024}
TEST_YEARS = {2025, 2026}

# Bar fetch window around release
PRE_MINUTES = 10
POST_MINUTES = 130


# ---------------------------------------------------------------------------
# Surprise computation -- exact replication of production logic
# ---------------------------------------------------------------------------

def parse_ff_value(raw: str | None) -> float | None:
    """Parse a raw FF value string exactly like EconomicEvent.surprise_pct."""
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return float(s.replace("%", "").replace("K", "e3").replace("M", "e6").replace("B", "e9"))
    except ValueError:
        return None


def surprise_pct(actual: str | None, forecast: str | None) -> float | None:
    """EXACT replication of EconomicEvent.surprise_pct (models/events.py)."""
    if actual is None or (isinstance(actual, float) and np.isnan(actual)) or str(actual).strip() == "":
        return None
    if forecast is None or (isinstance(forecast, float) and np.isnan(forecast)) or not str(forecast).strip():
        return None
    try:
        actual_val = float(str(actual).replace("%", "").replace("K", "e3").replace("M", "e6").replace("B", "e9"))
        forecast_val = float(str(forecast).replace("%", "").replace("K", "e3").replace("M", "e6").replace("B", "e9"))
        if forecast_val == 0:
            return None
        return ((actual_val - forecast_val) / abs(forecast_val)) * 100
    except (ValueError, ZeroDivisionError):
        return None


UNEMPLOYMENT_INDICATORS = ["unemployment", "jobless", "claims"]  # surprise.py verbatim


def usd_direction(surprise: float, title: str) -> int:
    """+1 = USD strength, -1 = USD weakness. Exact surprise.py logic."""
    usd_positive = surprise > 0
    if any(ind in title.lower() for ind in UNEMPLOYMENT_INDICATORS):
        usd_positive = not usd_positive
    return 1 if usd_positive else -1


def trade_side(usd_dir: int, pair: str) -> str:
    """surprise.py: USD base -> BUY on USD strength; USD quote -> SELL."""
    usd_is_base = pair.upper().startswith("USD")
    if usd_dir > 0:
        return "BUY" if usd_is_base else "SELL"
    return "SELL" if usd_is_base else "BUY"


# ---------------------------------------------------------------------------
# Event loading
# ---------------------------------------------------------------------------

@dataclass
class SurpriseEvent:
    event_type: str
    title: str
    scheduled_utc: datetime          # naive UTC
    surprise_primary: float | None   # surprise_pct replication
    diff_native: float | None        # actual - forecast, native units
    zscore: float | None             # standardized diff (expanding, prior-only)


def load_events() -> dict[str, list[SurpriseEvent]]:
    df = pd.read_csv(FF_HISTORY_CSV)
    df["scheduled_utc"] = pd.to_datetime(df["scheduled_utc"])
    out: dict[str, list[SurpriseEvent]] = {}
    for etype, meta in EVENT_GROUPS.items():
        sub = df[df["title"].isin(meta["titles"])].sort_values("scheduled_utc")
        events: list[SurpriseEvent] = []
        diffs_history: list[float] = []
        for _, r in sub.iterrows():
            sp = surprise_pct(r["actual"], r["forecast"])
            a, f = parse_ff_value(r["actual"]), parse_ff_value(r["forecast"])
            diff = (a - f) if (a is not None and f is not None) else None
            z = None
            if diff is not None and len(diffs_history) >= MIN_Z_HISTORY:
                # Trailing sigma: rolling window of the last Z_WINDOW prior
                # releases (not expanding -- an expanding window lets the
                # COVID-2020 outliers poison sigma forever: NFP diffs of
                # +/-10,000K make every later |z| < 0.3 and the variant
                # never trades again).
                window = diffs_history[-Z_WINDOW:]
                sigma = float(np.std(window, ddof=1))
                if sigma > 0:
                    z = diff / sigma
            if diff is not None:
                diffs_history.append(diff)
            events.append(
                SurpriseEvent(
                    event_type=etype,
                    title=str(r["title"]),
                    scheduled_utc=r["scheduled_utc"].to_pydatetime(),
                    surprise_primary=sp,
                    diff_native=diff,
                    zscore=z,
                )
            )
        out[etype] = events
        n_sp = sum(1 for e in events if e.surprise_primary is not None)
        n_z = sum(1 for e in events if e.zscore is not None)
        logger.info(f"{etype}: {len(events)} events, {n_sp} with primary surprise, {n_z} with z-score")
    return out


# ---------------------------------------------------------------------------
# Bar data (correct tz-aware fetch, cached per event)
# ---------------------------------------------------------------------------

def bars_cache_path(pair: str, dt: datetime) -> Path:
    return BARS_CACHE / pair / f"{dt.strftime('%Y%m%d_%H%M')}.csv"


def fetch_bars(pair: str, dt: datetime) -> pd.DataFrame | None:
    """Fetch (or load cached) 1-min bars [dt-10min, dt+130min], true UTC."""
    path = bars_cache_path(pair, dt)
    if path.exists():
        if path.stat().st_size < 10:  # cached "no data" marker
            return None
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df if not df.empty else None

    import dukascopy_python as dp  # lazy import: only needed for fetch phase

    path.parent.mkdir(parents=True, exist_ok=True)
    start = dt.replace(tzinfo=UTC) - timedelta(minutes=PRE_MINUTES)
    end = dt.replace(tzinfo=UTC) + timedelta(minutes=POST_MINUTES)
    try:
        df = dp.fetch(DUKASCOPY_INSTRUMENTS[pair], dp.INTERVAL_MIN_1, dp.OFFER_SIDE_BID, start, end)
    except Exception as exc:  # noqa: BLE001 - third-party lib raises bare Exceptions
        logger.warning(f"Dukascopy fetch failed {pair} {dt}: {exc}")
        return None
    if df is None or df.empty:
        path.write_text("")  # negative-cache
        logger.warning(f"No bars for {pair} {dt}")
        return None
    df = df[["open", "high", "low", "close", "volume"]]
    df.to_csv(path)
    return df


def fetch_all_bars(events_by_type: dict[str, list[SurpriseEvent]], workers: int = 6) -> None:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    tasks: list[tuple[str, datetime]] = []
    seen = set()
    for etype, events in events_by_type.items():
        for pair in EVENT_GROUPS[etype]["pairs"]:
            for e in events:
                if e.surprise_primary is None and e.zscore is None:
                    continue
                key = (pair, e.scheduled_utc)
                if key not in seen:
                    seen.add(key)
                    tasks.append(key)
    todo = [t for t in tasks if not bars_cache_path(*t).exists()]
    logger.info(f"Bar windows: {len(tasks)} total, {len(todo)} to fetch ({workers} workers)")
    n_err = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_bars, pair, dt): (pair, dt) for pair, dt in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001 - report loudly, keep going
                n_err += 1
                logger.error(f"Fetch task failed {futures[fut]}: {exc!r}")
                if n_err > 50:
                    raise RuntimeError(f"{n_err} fetch failures -- aborting loudly") from exc
            if i % 50 == 0:
                logger.info(f"  fetched {i}/{len(todo)}")
    remaining = [t for t in tasks if not bars_cache_path(*t).exists()]
    logger.info(f"Fetch phase complete: {len(remaining)} still missing, {n_err} errors")


# ---------------------------------------------------------------------------
# Trade simulation (directional, pessimistic SL-first)
# ---------------------------------------------------------------------------

def simulate_trade(
    bars: pd.DataFrame,
    event_dt: datetime,
    side: str,
    entry_delay_min: int,
    tp_pips: float,
    sl_pips: float,
    time_stop_min: int,
    spread_pips: float,
    pip: float,
) -> float | None:
    """Simulate one directional trade. Returns P&L in pips, or None if no
    usable entry bar exists (event excluded, not fabricated)."""
    idx = bars.index
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    times = idx.to_numpy()

    entry_target = np.datetime64(event_dt + timedelta(minutes=entry_delay_min))
    # first bar at/after the entry time, tolerance +3 min
    pos = int(np.searchsorted(times, entry_target, side="left"))
    if pos >= len(times):
        return None
    if (times[pos] - entry_target) > np.timedelta64(3, "m"):
        return None

    ohlc = bars[["open", "high", "low", "close"]].to_numpy()
    entry_price = float(ohlc[pos][0])  # open of entry bar (bid data)

    tp_d, sl_d = tp_pips * pip, sl_pips * pip
    if side == "BUY":
        tp_level, sl_level = entry_price + tp_d, entry_price - sl_d
    else:
        tp_level, sl_level = entry_price - tp_d, entry_price + sl_d

    cutoff = np.datetime64(event_dt + timedelta(minutes=entry_delay_min + time_stop_min))
    exit_price = None
    for i in range(pos, len(ohlc)):
        if times[i] > cutoff:
            break
        _, h, lo, c = ohlc[i]
        if side == "BUY":
            hit_sl, hit_tp = lo <= sl_level, h >= tp_level
        else:
            hit_sl, hit_tp = h >= sl_level, lo <= tp_level
        if hit_sl:            # pessimistic: SL first on ambiguity (spec)
            exit_price = sl_level
            break
        if hit_tp:
            exit_price = tp_level
            break
        exit_price = float(c)  # provisional time-stop exit at bar close

    if exit_price is None:
        return None

    pnl = (exit_price - entry_price) if side == "BUY" else (entry_price - exit_price)
    return pnl / pip - spread_pips  # full spread charged per round trip


# ---------------------------------------------------------------------------
# Bootstrap (same shape as monte_carlo_dukascopy.bootstrap_metrics)
# ---------------------------------------------------------------------------

def bootstrap_metrics(pnl_array: np.ndarray, n_comparisons: int = 1) -> dict:
    n = len(pnl_array)
    if n < 3:
        return {"mean_pnl": float(np.mean(pnl_array)) if n else 0.0,
                "ci_low": 0.0, "ci_high": 0.0, "sharpe": 0.0,
                "win_rate": 0.0, "n_trades": n}
    rng = np.random.default_rng(42)
    boot_idx = rng.integers(0, n, size=(N_BOOTSTRAP, n))
    boot = pnl_array[boot_idx]
    means = boot.mean(axis=1)
    stds = np.maximum(boot.std(axis=1, ddof=1), 1.0)
    sharpes = np.clip(means / stds * np.sqrt(n), -10, 10)
    alpha = (1 - CONFIDENCE_LEVEL) / 2
    alpha_b = alpha / n_comparisons if n_comparisons > 1 else alpha
    return {
        "mean_pnl": float(pnl_array.mean()),
        "ci_low": float(np.percentile(means, alpha * 100)),
        "ci_high": float(np.percentile(means, (1 - alpha) * 100)),
        "ci_low_bonf": float(np.percentile(means, alpha_b * 100)),
        "ci_high_bonf": float(np.percentile(means, (1 - alpha_b) * 100)),
        "sharpe": float(np.mean(sharpes)),
        "win_rate": float((pnl_array > 0).mean()),
        "n_trades": n,
    }


# ---------------------------------------------------------------------------
# Grid search
# ---------------------------------------------------------------------------

def eligible_events(
    events: list[SurpriseEvent], definition: str, threshold: float
) -> list[tuple[SurpriseEvent, float]]:
    """Events passing the threshold; returns (event, signed surprise measure)."""
    out = []
    for e in events:
        val = e.surprise_primary if definition == "primary" else e.zscore
        if val is None or abs(val) < threshold:
            continue
        # direction sign source: primary uses surprise_pct sign; z uses diff sign
        sign_src = e.surprise_primary if definition == "primary" else e.diff_native
        if sign_src is None or sign_src == 0:
            continue
        out.append((e, float(sign_src)))
    return out


def run_grid(
    events: list[SurpriseEvent],
    pair: str,
    definition: str,
    year_filter: set[int] | None = None,
    spread_mult: float = 1.0,
    n_comparisons: int = 1,
) -> list[dict]:
    pip = PIP_SIZES[pair]
    spread = EVENT_SPREAD_PIPS[pair] * spread_mult
    thresholds = THRESHOLDS_PRIMARY if definition == "primary" else THRESHOLDS_ZSCORE
    if year_filter:
        events = [e for e in events if e.scheduled_utc.year in year_filter]

    # preload bars once per event
    bar_map: dict[datetime, pd.DataFrame | None] = {}
    for e in events:
        bar_map[e.scheduled_utc] = fetch_bars(pair, e.scheduled_utc)

    results = []
    for thr in thresholds:
        elig = eligible_events(events, definition, thr)
        for delay in ENTRY_DELAYS:
            for ts in TIME_STOPS:
                for tp in TP_GRID:
                    for sl in SL_GRID:
                        pnls = []
                        excluded = 0
                        for e, sign_src in elig:
                            bars = bar_map[e.scheduled_utc]
                            if bars is None:
                                excluded += 1
                                continue
                            side = trade_side(usd_direction(sign_src, e.title), pair)
                            pnl = simulate_trade(bars, e.scheduled_utc, side, delay, tp, sl, ts, spread, pip)
                            if pnl is None:
                                excluded += 1
                                continue
                            pnls.append(pnl)
                        if len(pnls) < 5:
                            continue
                        m = bootstrap_metrics(np.array(pnls), n_comparisons)
                        m.update({"threshold": thr, "delay": delay, "time_stop": ts,
                                  "tp": tp, "sl": sl, "excluded": excluded,
                                  "definition": definition, "pair": pair,
                                  "spread_mult": spread_mult})
                        results.append(m)
    return results


def best_by_ci_low(results: list[dict]) -> dict | None:
    return max(results, key=lambda r: r["ci_low"], default=None)


def rerun_params(
    events: list[SurpriseEvent], pair: str, definition: str, params: dict,
    year_filter: set[int] | None = None, spread_mult: float = 1.0,
) -> dict | None:
    """Evaluate one fixed parameter set (used for walk-forward OOS and spread sweep)."""
    pip = PIP_SIZES[pair]
    spread = EVENT_SPREAD_PIPS[pair] * spread_mult
    if year_filter:
        events = [e for e in events if e.scheduled_utc.year in year_filter]
    elig = eligible_events(events, definition, params["threshold"])
    pnls = []
    excluded = 0
    for e, sign_src in elig:
        bars = fetch_bars(pair, e.scheduled_utc)
        if bars is None:
            excluded += 1
            continue
        side = trade_side(usd_direction(sign_src, e.title), pair)
        pnl = simulate_trade(bars, e.scheduled_utc, side, params["delay"],
                             params["tp"], params["sl"], params["time_stop"], spread, pip)
        if pnl is None:
            excluded += 1
            continue
        pnls.append(pnl)
    if not pnls:
        return None
    m = bootstrap_metrics(np.array(pnls))
    m["excluded"] = excluded
    return m


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyze(events_by_type: dict[str, list[SurpriseEvent]]) -> dict:
    # Resume-safe: previously computed (event_type, pair, definition) cells
    # are loaded from RESULTS_JSON and skipped.
    out: dict = {}
    if RESULTS_JSON.exists():
        out = json.loads(RESULTS_JSON.read_text())
    for etype, meta in EVENT_GROUPS.items():
        events = events_by_type[etype]
        out.setdefault(etype, {})
        for pair in meta["pairs"]:
            out[etype].setdefault(pair, {})
            for definition in ("primary", "zscore"):
                if definition in out[etype][pair]:
                    continue
                t0 = time.time()
                full = run_grid(events, pair, definition, n_comparisons=len(meta["pairs"]))
                best = best_by_ci_low(full)
                entry: dict = {"n_grid": len(full)}
                if best is None:
                    entry["verdict"] = "NO_DATA"
                    out[etype][pair][definition] = entry
                    RESULTS_JSON.write_text(json.dumps(out, indent=2, default=str))
                    continue
                entry["best_full"] = best

                # Overfitting smell: how many grid cells are profitable at all?
                n_pos = sum(1 for r in full if r["mean_pnl"] > 0)
                entry["pct_grid_positive"] = round(100 * n_pos / len(full), 1)

                # Walk-forward
                train = run_grid(events, pair, definition, year_filter=TRAIN_YEARS)
                best_train = best_by_ci_low(train)
                if best_train is not None:
                    oos = rerun_params(events, pair, definition, best_train,
                                       year_filter=TEST_YEARS)
                    entry["wf_train"] = {k: best_train[k] for k in
                                         ("threshold", "delay", "time_stop", "tp", "sl",
                                          "mean_pnl", "ci_low", "ci_high", "sharpe", "n_trades")}
                    entry["wf_oos"] = oos

                # Spread sensitivity at best full-sample params
                sweep = {}
                for m in SPREAD_MULTIPLIERS:
                    r = rerun_params(events, pair, definition, best, spread_mult=m)
                    sweep[str(m)] = None if r is None else {
                        "mean_pnl": r["mean_pnl"], "ci_low": r["ci_low"],
                        "ci_high": r["ci_high"], "n_trades": r["n_trades"]}
                entry["spread_sweep"] = sweep

                # Pass criteria
                ci_ok = best["ci_low"] > 0
                oos_ok = bool(entry.get("wf_oos")) and entry["wf_oos"]["mean_pnl"] > 0
                s2 = sweep.get("2.0")
                spread_ok = bool(s2) and s2["mean_pnl"] > 0
                entry["pass"] = bool(ci_ok and oos_ok and spread_ok)
                entry["pass_detail"] = {"ci_low>0": ci_ok, "wf_oos>0": oos_ok,
                                        "survives_2x_spread": spread_ok}
                out[etype][pair][definition] = entry
                RESULTS_JSON.write_text(json.dumps(out, indent=2, default=str))
                logger.info(
                    f"{etype}/{pair}/{definition}: best E[P&L]={best['mean_pnl']:+.1f} "
                    f"CI=[{best['ci_low']:+.1f},{best['ci_high']:+.1f}] "
                    f"pass={entry['pass']} ({time.time()-t0:.0f}s)"
                )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch-bars", action="store_true", help="Download bar windows only")
    ap.add_argument("--run", action="store_true", help="Run the full analysis")
    ap.add_argument("--workers", type=int, default=6, help="Parallel fetch workers")
    args = ap.parse_args()

    events_by_type = load_events()

    if args.fetch_bars:
        fetch_all_bars(events_by_type, workers=args.workers)
    if args.run:
        results = analyze(events_by_type)
        RESULTS_JSON.write_text(json.dumps(results, indent=2, default=str))
        logger.info(f"Results written -> {RESULTS_JSON}")


if __name__ == "__main__":
    main()
