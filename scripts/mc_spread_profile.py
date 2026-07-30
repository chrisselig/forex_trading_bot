"""Phase A (spec 17) — measured spread profile from Dukascopy tick data.

Report 16's Run D showed the 50/70/10 bracket earns ambient-volatility
P&L indistinguishable from event windows, but every number rested on a
FLAT spread assumption (USDZAR 25 / USDTRY 30 pips). This script measures
REAL bid/ask tick spreads from Dukascopy and calibrates them against the
live trade journal (data/forex_bot.db, orders.entry_spread_pips).

Sampling design (per spec):
  - ~200 days/pair, 2020-2026, weekdays, holiday weeks excluded.
  - Base sample = the 160 non-event days already downloaded for report 16's
    Run D (scripts/data/dukascopy/{PAIR}_ambient_1min.csv), extended with
    ~40 more days drawn from the same non-event candidate pool (new seed,
    no overlap) to reach ~200.
  - Per sampled day: four 30-min tick probe windows, anchored at
    03:00 / 09:00 / 14:00 / 20:00 UTC (Asia / early London / London-NY
    overlap / NY-only).
  - dukascopy_python.fetch() is called with tz-AWARE UTC datetimes only
    (see download_dukascopy.py's fixed fetcher / report 16). Naive
    datetimes are silently interpreted in system-local time — do not
    reintroduce that bug here.

Tick fetch (INTERVAL_TICK) returns both bidPrice and askPrice in a single
call (verified empirically) — no separate bid/ask fetches needed.

Usage:
    # Download tick windows (resume-safe; rerun until "0 remaining"):
    python scripts/mc_spread_profile.py --download --limit 60

    # Compute spread profile + calibration once download is complete:
    python scripts/mc_spread_profile.py --analyze
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "scripts" / "data"
DUKA_DIR = DATA_DIR / "dukascopy"
TICK_CACHE_DIR = DATA_DIR / "_cache" / "ticks"
DB_PATH = PROJECT_ROOT / "data" / "forex_bot.db"

PAIRS = ["USDZAR", "USDTRY"]
PIP_SIZES = {"USDZAR": 0.0001, "USDTRY": 0.0001}
DUKASCOPY_INSTRUMENTS = {"USDZAR": "USD/ZAR", "USDTRY": "USD/TRY"}

# Report 16 flat-spread assumption (the thing this analysis is testing)
REPORT16_ASSUMED_SPREAD = {"USDZAR": 25.0, "USDTRY": 30.0}

ANCHORS_UTC = ["03:00", "09:00", "14:00", "20:00"]
PROBE_WINDOW_MIN = 30

TARGET_DAYS = 200
EXTEND_SEED = 43
REQUEST_DELAY_SECS = 0.3

# TRY regime shift: Turkish presidential/parliamentary elections May 14 +
# runoff May 28, 2023, followed by the CBRT policy pivot (rate hikes
# resumed June 2023). Flag pre/post split at 2023-06-01.
TRY_REGIME_SPLIT = "2023-06-01"


# ---------------------------------------------------------------------------
# Day sampling — base (Run D 160) + extension to ~200
# ---------------------------------------------------------------------------


def _non_event_candidates(pair: str) -> list[str]:
    event_dates: set[str] = set()
    csv_path = DUKA_DIR / f"{pair}_1min.csv"
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
    return candidates


def sample_days_extended(pair: str, target_n: int = TARGET_DAYS) -> list[str]:
    """Base = Run D's 160 non-event days (already downloaded for report 16).
    Extended with new non-overlapping days from the same candidate pool to
    reach ~target_n, using a distinct RNG seed so the extension is
    reproducible and does not disturb the original Run D sample.
    """
    ambient_path = DUKA_DIR / f"{pair}_ambient_1min.csv"
    base: set[str] = set()
    if ambient_path.exists():
        base = set(
            pd.read_csv(ambient_path, usecols=["event_date"])["event_date"].unique()
        )

    candidates = _non_event_candidates(pair)
    remaining = [d for d in candidates if d not in base]
    n_extra = max(0, target_n - len(base))
    rng = random.Random(EXTEND_SEED)
    extra = rng.sample(remaining, min(n_extra, len(remaining)))

    full = sorted(base | set(extra))
    logger.info(
        f"{pair}: base={len(base)} Run-D days, +{len(extra)} extension days "
        f"-> {len(full)} total (target {target_n}, pool={len(candidates)})"
    )
    return full


# ---------------------------------------------------------------------------
# Tick download
# ---------------------------------------------------------------------------


def tick_path(pair: str, day: str, anchor: str) -> Path:
    hh = anchor.replace(":", "")
    return TICK_CACHE_DIR / pair / f"{day}_{hh}.csv"


def download_ticks(pair: str, limit: int | None) -> None:
    """Fetch 30-min tick probe windows at each anchor, for sampled days.

    Resume-safe: any (day, anchor) file already on disk is skipped.
    `limit` bounds the number of NEW (day, anchor) fetches this run, for
    foreground chunking.
    """
    import dukascopy_python as dp

    days = sample_days_extended(pair)
    out_dir = TICK_CACHE_DIR / pair
    out_dir.mkdir(parents=True, exist_ok=True)

    todo = []
    for day in days:
        for anchor in ANCHORS_UTC:
            if not tick_path(pair, day, anchor).exists():
                todo.append((day, anchor))

    logger.info(f"[{pair}] {len(todo)} (day, anchor) window(s) remaining to fetch")
    if limit is not None:
        todo = todo[:limit]

    instrument = DUKASCOPY_INSTRUMENTS[pair]
    total_bytes = 0
    fetched = 0
    failed = 0
    for i, (day, anchor) in enumerate(todo, 1):
        hh, mm = (int(x) for x in anchor.split(":"))
        start = datetime.fromisoformat(day).replace(hour=hh, minute=mm, tzinfo=UTC)
        end = start + timedelta(minutes=PROBE_WINDOW_MIN)
        try:
            df = dp.fetch(instrument, dp.INTERVAL_TICK, dp.OFFER_SIDE_BID, start, end)
        except Exception as exc:  # noqa: BLE001 — analysis script, LOUD, keep going
            logger.error(f"[{pair}] {day} {anchor}: fetch failed: {exc}")
            failed += 1
            continue
        if df is None or df.empty:
            # Write a header-only marker so genuinely-empty windows (e.g.
            # TRY overnight illiquidity) are not refetched forever.
            logger.warning(f"[{pair}] {day} {anchor}: no ticks returned (marker written)")
            tick_path(pair, day, anchor).write_text(
                "timestamp,bidPrice,askPrice,bidVolume,askVolume\n"
            )
            failed += 1
            continue
        path = tick_path(pair, day, anchor)
        df.to_csv(path)
        total_bytes += path.stat().st_size
        fetched += 1
        if i % 25 == 0:
            logger.info(f"[{pair}] {i}/{len(todo)} fetched this run")
        time.sleep(REQUEST_DELAY_SECS)

    logger.info(
        f"[{pair}] run done: {fetched} fetched, {failed} failed, "
        f"{total_bytes / 1e6:.2f} MB written this run"
    )


# ---------------------------------------------------------------------------
# Spread profile
# ---------------------------------------------------------------------------


def load_all_ticks(pair: str) -> pd.DataFrame:
    out_dir = TICK_CACHE_DIR / pair
    frames = []
    for path in sorted(out_dir.glob("*.csv")):
        day_anchor = path.stem  # YYYY-MM-DD_HHMM
        day, hhmm = day_anchor.rsplit("_", 1)
        anchor = f"{hhmm[:2]}:{hhmm[2:]}"
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty:
            continue
        df["day"] = day
        df["anchor"] = anchor
        df["year"] = int(day[:4])
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    all_df = pd.concat(frames, ignore_index=False)
    pip = PIP_SIZES[pair]
    all_df["spread_pips"] = (all_df["askPrice"] - all_df["bidPrice"]) / pip
    return all_df


def spread_profile_table(pair: str) -> pd.DataFrame:
    df = load_all_ticks(pair)
    if df.empty:
        return pd.DataFrame()
    rows = []
    for (anchor, year), g in df.groupby(["anchor", "year"]):
        rows.append({
            "pair": pair,
            "anchor": anchor,
            "year": year,
            "n_ticks": len(g),
            "n_days": g["day"].nunique(),
            "median": g["spread_pips"].median(),
            "p75": g["spread_pips"].quantile(0.75),
            "p95": g["spread_pips"].quantile(0.95),
        })
    out = pd.DataFrame(rows).sort_values(["anchor", "year"])
    return out


def overall_profile_table(pair: str) -> pd.DataFrame:
    df = load_all_ticks(pair)
    if df.empty:
        return pd.DataFrame()
    rows = []
    for anchor, g in df.groupby("anchor"):
        rows.append({
            "pair": pair,
            "anchor": anchor,
            "n_ticks": len(g),
            "n_days": g["day"].nunique(),
            "median": g["spread_pips"].median(),
            "p75": g["spread_pips"].quantile(0.75),
            "p95": g["spread_pips"].quantile(0.95),
        })
    return pd.DataFrame(rows).sort_values("anchor")


def regime_flag(pair: str) -> dict | None:
    if pair != "USDTRY":
        return None
    df = load_all_ticks(pair)
    if df.empty:
        return None
    pre = df[df["day"] < TRY_REGIME_SPLIT]["spread_pips"]
    post = df[df["day"] >= TRY_REGIME_SPLIT]["spread_pips"]
    if len(pre) < 20 or len(post) < 20:
        return None
    return {
        "split": TRY_REGIME_SPLIT,
        "pre_median": pre.median(), "pre_p75": pre.quantile(0.75), "pre_n": len(pre),
        "post_median": post.median(), "post_p75": post.quantile(0.75), "post_n": len(post),
    }


# ---------------------------------------------------------------------------
# Calibration vs trade journal + report 16 assumptions
# ---------------------------------------------------------------------------


def journal_spreads() -> pd.DataFrame:
    con = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT instrument, created_at, entry_spread_pips FROM orders "
        "WHERE entry_spread_pips IS NOT NULL AND instrument IN ('USDZAR','USDTRY') "
        "ORDER BY created_at",
        con,
    )
    con.close()
    df["created_at"] = pd.to_datetime(df["created_at"])
    df["hour_utc"] = df["created_at"].dt.hour
    return df


def calibration_report() -> pd.DataFrame:
    jdf = journal_spreads()
    rows = []
    for pair in PAIRS:
        sub = jdf[jdf["instrument"] == pair]
        overall = overall_profile_table(pair)
        duka_p75_all = overall["p75"].mean() if not overall.empty else float("nan")
        duka_median_all = overall["median"].mean() if not overall.empty else float("nan")
        rows.append({
            "pair": pair,
            "journal_n": len(sub),
            "journal_mean": sub["entry_spread_pips"].mean() if len(sub) else float("nan"),
            "journal_median": sub["entry_spread_pips"].median() if len(sub) else float("nan"),
            "journal_min": sub["entry_spread_pips"].min() if len(sub) else float("nan"),
            "journal_max": sub["entry_spread_pips"].max() if len(sub) else float("nan"),
            "journal_date_range": (
                f"{sub['created_at'].min()} .. {sub['created_at'].max()}" if len(sub) else "n/a"
            ),
            "dukascopy_median_avg_anchor": duka_median_all,
            "dukascopy_p75_avg_anchor": duka_p75_all,
            "report16_assumed": REPORT16_ASSUMED_SPREAD[pair],
        })
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description="Phase A — measured spread profile")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--analyze", action="store_true")
    args = parser.parse_args()

    if args.download:
        for pair in PAIRS:
            download_ticks(pair, args.limit)
        return

    if args.analyze:
        pd.set_option("display.width", 160)
        pd.set_option("display.max_rows", 200)
        for pair in PAIRS:
            print(f"\n================ {pair}: spread profile by anchor x year ================")
            print(spread_profile_table(pair).to_string(index=False))
            print(f"\n---- {pair}: overall by anchor ----")
            print(overall_profile_table(pair).to_string(index=False))
            rf = regime_flag(pair)
            if rf:
                print(f"\n---- {pair}: regime flag (split {rf['split']}) ----")
                print(
                    f"  pre : median={rf['pre_median']:.1f} p75={rf['pre_p75']:.1f} n={rf['pre_n']}"
                )
                print(
                    f"  post: median={rf['post_median']:.1f} p75={rf['post_p75']:.1f} n={rf['post_n']}"
                )
        print("\n================ Calibration vs journal + report 16 ================")
        print(calibration_report().to_string(index=False))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
