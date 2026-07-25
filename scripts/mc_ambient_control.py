"""Ambient-volatility control experiment for report 16.

Why did the shifted-window backtests (reports 04-12) look plausible when the
windows contained no releases? And is the straddle edge event-specific at all?

Run A (replication): simulate on the OLD shifted CSVs with the stored
event_utc. simulate_straddle anchors on the bar closest to event-30min; the
old windows span [event+4h, event+10h], so the anchor is the first bar of the
window — a straddle placed ~4h after the release, with no release in the
window at all. Reproducing the old report numbers confirms the mechanism.

Run B (independent pseudo-anchor): same old shifted windows, anchored 2.5h
into the window (event+6.5h) — a second arbitrary no-event anchor, but still
on event days.

Run C (corrected event windows): true event anchor on corrected data.

Run D (true non-event days): uniformly sampled weekdays with NO tracked
high-impact release for the pair (not in the pair's event CSV, not in
ff_history.csv), anchored at 14:00 UTC (liquid London/NY overlap) and
03:00 UTC (Asia session). Data downloaded with the FIXED tz-aware fetcher.

All at configured 50/70/10, spread 25 (USDZAR) / 30 (USDTRY).

Usage:
    # Download Run D windows (resume-safe; rerun until "0 remaining"):
    python scripts/mc_ambient_control.py --download --limit 60

    # Run the experiment (A/B/C always; D if ambient CSVs exist):
    python scripts/mc_ambient_control.py
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent))

from monte_carlo_dukascopy import (  # noqa: E402
    DATA_DIR,
    bootstrap_metrics,
    simulate_straddle,
)

US3 = {"NFP", "CPI", "FOMC"}
US6 = {"NFP", "CPI", "FOMC", "PPI", "GDP", "PCE"}

PAIR_SPREADS = {"USDZAR": 25.0, "USDTRY": 30.0}

N_SAMPLE_DAYS = 160
RNG_SEED = 42
ANCHORS_UTC = ["14:00", "03:00"]
FETCH_START_HOUR = 1   # 01:00 UTC — covers 03:00 anchor's -2h
FETCH_END_HOUR = 18    # 18:00 UTC — covers 14:00 anchor's +4h
REQUEST_DELAY_SECS = 0.8

DUKASCOPY_INSTRUMENTS = {
    "USDZAR": "USD/ZAR",
    "USDTRY": "USD/TRY",
}


def ambient_csv_path(pair: str) -> Path:
    return DATA_DIR / "dukascopy" / f"{pair}_ambient_1min.csv"


def load_csv(path: Path) -> dict[str, dict]:
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    groups = {}
    for (event_date, event_name), g in df.groupby(["event_date", "event_name"]):
        bars = g[["open", "high", "low", "close", "volume"]].sort_index()
        groups[f"{event_date}_{event_name}"] = {
            "bars": bars,
            "event_name": event_name,
            "event_date": event_date,
            "event_utc": g["event_utc"].iloc[0],
        }
    return groups


# ---------------------------------------------------------------------------
# Run D: non-event day sampling + download
# ---------------------------------------------------------------------------


def sample_non_event_days(pair: str) -> list[str]:
    """Uniformly sample weekdays 2020-2026 with no tracked release for the pair."""
    event_dates: set[str] = set()

    csv_path = DATA_DIR / "dukascopy" / f"{pair}_1min.csv"
    df = pd.read_csv(csv_path, usecols=["event_date"])
    event_dates |= set(df["event_date"].unique())

    ff = pd.read_csv(DATA_DIR / "ff_history.csv", usecols=["scheduled_utc"])
    event_dates |= set(ff["scheduled_utc"].str[:10].unique())

    candidates = []
    day = datetime(2020, 1, 6)
    end = datetime(2026, 6, 26)
    while day <= end:
        ds = day.strftime("%Y-%m-%d")
        is_holiday_week = (day.month == 12 and day.day >= 24) or (
            day.month == 1 and day.day <= 2
        )
        if day.weekday() < 5 and ds not in event_dates and not is_holiday_week:
            candidates.append(ds)
        day += timedelta(days=1)

    rng = random.Random(RNG_SEED)
    sample = sorted(rng.sample(candidates, min(N_SAMPLE_DAYS, len(candidates))))
    logger.info(
        f"{pair}: {len(candidates)} candidate non-event weekdays, "
        f"sampled {len(sample)}"
    )
    return sample


def download_ambient(pair: str, limit: int | None) -> None:
    """Fetch 01:00-18:00 UTC 1-min bars for sampled non-event days (resume-safe)."""
    import dukascopy_python as dp

    out_path = ambient_csv_path(pair)
    existing: set[str] = set()
    if out_path.exists():
        existing = set(
            pd.read_csv(out_path, usecols=["event_date"])["event_date"].unique()
        )

    days = [d for d in sample_non_event_days(pair) if d not in existing]
    logger.info(f"[{pair}] {len(days)} non-event day(s) remaining to fetch")
    if limit is not None:
        days = days[:limit]

    instrument = DUKASCOPY_INSTRUMENTS[pair]
    frames = []
    failed = 0
    for ds in days:
        day = datetime.fromisoformat(ds)
        # tz-aware UTC — the fix that motivated report 16
        start = day.replace(hour=FETCH_START_HOUR, tzinfo=UTC)
        end = day.replace(hour=FETCH_END_HOUR, tzinfo=UTC)
        try:
            df = dp.fetch(instrument, dp.INTERVAL_MIN_1, dp.OFFER_SIDE_BID, start, end)
        except Exception as exc:  # noqa: BLE001 — analysis script, keep going but LOUD
            logger.error(f"[{pair}] {ds}: fetch failed: {exc}")
            failed += 1
            continue
        if df is None or df.empty:
            logger.warning(f"[{pair}] {ds}: no data returned")
            failed += 1
            continue
        df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        df["event_name"] = "AMBIENT"
        df["event_date"] = ds
        df["event_utc"] = f"{ds}T14:00:00"  # nominal; anchors applied at sim time
        frames.append(df)
        time.sleep(REQUEST_DELAY_SECS)

    if frames:
        new = pd.concat(frames)
        header = not out_path.exists()
        new.to_csv(out_path, mode="a", header=header)
        logger.info(
            f"[{pair}] appended {len(frames)} day(s) ({len(new):,} bars), "
            f"{failed} failed -> {out_path}"
        )
    else:
        logger.info(f"[{pair}] nothing fetched ({failed} failed)")


# ---------------------------------------------------------------------------
# Simulation runs
# ---------------------------------------------------------------------------


def run(groups, pair, wanted, spread, anchor):
    """anchor: 'stored' = stored event_utc; 'mid' = first bar + 150min."""
    pnls = []
    n_events = 0
    for v in groups.values():
        if v["event_name"] not in wanted:
            continue
        bars = v["bars"]
        if len(bars) < 60:
            continue
        n_events += 1
        if anchor == "stored":
            evt = v["event_utc"]
        else:  # mid-window pseudo-anchor
            t0 = bars.index[0]
            if t0.tz is not None:
                t0 = t0.tz_convert("UTC").tz_localize(None)
            evt = (t0 + timedelta(minutes=150)).isoformat()
        trades = simulate_straddle(bars, evt, pair, 50, 70, 10, spread_pips=spread)
        pnls.extend(t.pnl_pips for t in trades if t.triggered)
    m = bootstrap_metrics(np.array(pnls)) if pnls else None
    return n_events, m


def run_ambient(pair: str, spread: float, anchor_hhmm: str):
    """Run D: simulate on non-event days, window [anchor-2h, anchor+4h]."""
    path = ambient_csv_path(pair)
    if not path.exists():
        return 0, None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    idx = df.index
    idx_naive = idx.tz_convert("UTC").tz_localize(None) if idx.tz is not None else idx

    hh, mm = (int(x) for x in anchor_hhmm.split(":"))
    pnls = []
    n_days = 0
    for ds, g in df.groupby("event_date"):
        anchor = datetime.fromisoformat(ds).replace(hour=hh, minute=mm)
        mask = (idx_naive >= anchor - timedelta(hours=2)) & (
            idx_naive <= anchor + timedelta(hours=4)
        )
        window = df.loc[mask & (df["event_date"] == ds).values]
        bars = window[["open", "high", "low", "close", "volume"]].sort_index()
        if len(bars) < 60:
            continue
        n_days += 1
        trades = simulate_straddle(
            bars, anchor.isoformat(), pair, 50, 70, 10, spread_pips=spread
        )
        pnls.extend(t.pnl_pips for t in trades if t.triggered)
    m = bootstrap_metrics(np.array(pnls)) if pnls else None
    return n_days, m


def fmt(m):
    if m is None:
        return "no trades"
    return (
        f"E={m['mean_pnl']:+6.1f} CI=[{m['ci_low']:+6.1f},{m['ci_high']:+6.1f}] "
        f"WR={m['win_rate'] * 100:4.1f}% Sh={m['sharpe']:+5.2f} N={m['n_trades']}"
    )


def main():
    parser = argparse.ArgumentParser(description="Ambient control experiment (report 16)")
    parser.add_argument("--download", action="store_true", help="Fetch Run D windows")
    parser.add_argument("--limit", type=int, default=None, help="Max days per pair per run")
    args = parser.parse_args()

    if args.download:
        for pair in PAIR_SPREADS:
            download_ambient(pair, args.limit)
        return

    for pair, spread in PAIR_SPREADS.items():
        old = load_csv(DATA_DIR / "dukascopy_SHIFTED_BAD" / f"{pair}_1min.csv")
        new = load_csv(DATA_DIR / "dukascopy" / f"{pair}_1min.csv")
        print(f"\n================ {pair} (50/70/10, spread {spread}) ================")
        for scope_name, scope in [("NFP+CPI+FOMC", US3), ("6 US events", US6)]:
            ne, a = run(old, pair, scope, spread, "stored")
            _, b = run(old, pair, scope, spread, "mid")
            _, c = run(new, pair, scope, spread, "stored")
            print(f"\n  scope: {scope_name} ({ne} old windows)")
            print(f"  A old shifted CSV, stored anchor (=window start, event+4h): {fmt(a)}")
            print(f"  B old shifted CSV, anchor event+6.5h (no event in window):  {fmt(b)}")
            print(f"  C corrected CSV, true event anchor:                         {fmt(c)}")
        for hhmm in ANCHORS_UTC:
            nd, d = run_ambient(pair, spread, hhmm)
            print(f"  D non-event days ({nd}), anchor {hhmm} UTC:                   {fmt(d)}")


if __name__ == "__main__":
    main()
