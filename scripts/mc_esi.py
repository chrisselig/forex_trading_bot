#!/usr/bin/env python3
"""Monte Carlo + walk-forward validation of a US Economic Surprise Index
(ESI) directional strategy (Spec 19).

Citi-ESI-style construction: standardize each US data release's surprise
(actual vs forecast) against that release type's own historical surprise
dispersion (no look-ahead: prior-only rolling window, same discipline as
report 15 / scripts/mc_surprise.py), then aggregate into a single per-day
USD index via an EWMA decay (half-life grid: 10/20/40 trading days).

Two directional signals are tested weekly on EURUSD/GBPUSD/USDJPY/USDCAD/
AUDUSD, NET of one round-trip major-pair spread per sign-flip turn:
  - LEVEL:    long USD iff ESI(t) > 0
  - MOMENTUM: long USD iff ESI(t) - ESI(t-1 rebalance) > 0

Controls (must beat, or the "edge" is just a USD trend / noise):
  (a) buy-and-hold USD basket (always long USD, same 5 pairs)
  (b) random-sign control: 10,000 simulated sign paths with the SAME
      flip-rate as the real signal, same real weekly price data, same
      cost model -- if ESI does not beat this, it has no surprise content.

Also reports the correlation between ESI weekly returns and a rate-
differential "carry factor" proxy (same methodology as scripts/mc_value.py)
to assess whether ESI would diversify the carry book.

v1 scope: US-ONLY ESI (no foreign-leg surprise data) -- flagged as a
limitation throughout; see docs/research/19-mc-esi.md.

Usage:
  ~/anaconda3/envs/forex-bot/bin/python scripts/mc_esi.py
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from forex_bot.calendar.fred_client import FredClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "scripts" / "data"
DUKASCOPY_DIR = DATA_DIR / "dukascopy"
FF_HISTORY_CSV = DATA_DIR / "ff_history.csv"
RESULTS_JSON = DATA_DIR / "mc_esi_results.json"
FRED_CACHE = DATA_DIR / "_cache" / "mc_esi_fred.json"

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCAD", "AUDUSD"]
PIP_SIZE = {"EURUSD": 0.0001, "GBPUSD": 0.0001, "USDJPY": 0.01, "USDCAD": 0.0001, "AUDUSD": 0.0001}
# +1 = USD is the base currency (long USD => BUY pair); -1 = USD is quote (long USD => SELL pair)
PAIR_FLIP = {"EURUSD": -1, "GBPUSD": -1, "USDJPY": 1, "USDCAD": 1, "AUDUSD": -1}

BASE_SPREAD_PIPS = 1.5
STRESS_SPREAD_PIPS = 3.0

HALF_LIVES = [10, 20, 40]  # trading days
SIGNAL_TYPES = ["LEVEL", "MOMENTUM"]
MOMENTUM_LOOKBACK_WEEKS = 1  # design choice, not swept -- see report caveats

# Exact replication of report 15 / mc_surprise.py z-score construction
MIN_Z_HISTORY = 8
Z_WINDOW = 24
UNEMPLOYMENT_INDICATORS = ["unemployment", "jobless", "claims"]

TRAIN_YEARS = {2020, 2021, 2022, 2023, 2024}
TEST_YEARS = {2025, 2026}

N_BOOTSTRAP = 10_000
PERIODS_PER_YEAR = 52.0

# Carry-factor proxy (same series as scripts/mc_value.py)
RATE_SERIES = {
    "USD": "IR3TIB01USM156N", "EUR": "IR3TIB01EZM156N", "GBP": "IR3TIB01GBM156N",
    "JPY": "IR3TIB01JPM156N", "CAD": "IR3TIB01CAM156N", "AUD": "IR3TIB01AUM156N",
}
DATA_START = pd.Timestamp("2019-06-01")
DATA_END = pd.Timestamp("2026-07-15")


# ---------------------------------------------------------------------------
# Surprise / ESI construction (reuses report-15 parsing + no-look-ahead logic)
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


def usd_direction_sign(diff: float, title: str) -> int:
    """+1 = USD strength, -1 = USD weakness. Exact surprise.py logic."""
    usd_positive = diff > 0
    if any(ind in title.lower() for ind in UNEMPLOYMENT_INDICATORS):
        usd_positive = not usd_positive
    return 1 if usd_positive else -1


def trade_side(usd_dir: int, pair: str) -> str:
    """surprise.py: USD base -> BUY on USD strength; USD quote -> SELL."""
    usd_is_base = pair.upper().startswith("USD")
    if usd_dir > 0:
        return "BUY" if usd_is_base else "SELL"
    return "SELL" if usd_is_base else "BUY"


@dataclass
class Release:
    title: str
    scheduled_utc: pd.Timestamp
    z_usd: float  # standardized surprise, signed in USD-strength terms


def load_us_releases() -> list[Release]:
    """Build per-title, no-look-ahead standardized surprises for every US
    release type present in ff_history.csv (12 titles)."""
    df = pd.read_csv(FF_HISTORY_CSV)
    df["scheduled_utc"] = pd.to_datetime(df["scheduled_utc"])
    titles = sorted(df["title"].unique())
    releases: list[Release] = []
    for title in titles:
        sub = df[df["title"] == title].sort_values("scheduled_utc")
        diffs_history: list[float] = []
        n_z = 0
        for _, r in sub.iterrows():
            a, f = parse_ff_value(r["actual"]), parse_ff_value(r["forecast"])
            if a is None or f is None:
                continue
            diff = a - f
            z = None
            if len(diffs_history) >= MIN_Z_HISTORY:
                window = diffs_history[-Z_WINDOW:]
                sigma = float(np.std(window, ddof=1))
                if sigma > 0:
                    z = diff / sigma
            diffs_history.append(diff)
            if z is None or diff == 0:
                continue
            usd_dir = usd_direction_sign(diff, title)
            z_usd = abs(z) * usd_dir  # signed in USD-strength units
            releases.append(Release(title=title, scheduled_utc=r["scheduled_utc"], z_usd=z_usd))
            n_z += 1
        logger.info(f"{title}: {len(sub)} releases, {n_z} standardized (min {MIN_Z_HISTORY} priors)")
    releases.sort(key=lambda x: x.scheduled_utc)
    logger.info(f"Total standardized US releases feeding ESI: {len(releases)} across {len(titles)} titles")
    return releases


# ---------------------------------------------------------------------------
# Price panel + trading calendar
# ---------------------------------------------------------------------------

def load_daily_close(pair: str) -> pd.Series:
    path = DUKASCOPY_DIR / f"{pair}_daily.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing daily bars for {pair}: {path}")
    df = pd.read_csv(path, parse_dates=["timestamp"])
    s = df.set_index("timestamp")["close"].sort_index()
    s = s[~s.index.duplicated(keep="last")]
    n_days = (s.index.max() - s.index.min()).days
    if n_days < 365 * 3:
        raise RuntimeError(
            f"{pair} daily history too short ({n_days} days) -- fetch more with "
            "download_dukascopy.py (tz-aware fetcher) before running this script."
        )
    return s


def build_trading_calendar(price_panel: pd.DataFrame) -> pd.DatetimeIndex:
    """Weekday (Mon-Fri) trading days present in the union of pairs, i.e.
    excludes the Dukascopy 'Sunday' week-open micro-candle."""
    weekday_mask = price_panel.index.weekday < 5
    return price_panel.index[weekday_mask]


def compute_esi_series(
    releases: list[Release], trading_days: pd.DatetimeIndex, half_life: int
) -> pd.Series:
    """ESI(t) = ESI(t-1)*decay + sum(z_usd of releases mapped to day t).
    decay = 0.5**(1/half_life); half_life in trading days."""
    decay = 0.5 ** (1.0 / half_life)
    # Map each release date to the next available trading day (no look-ahead:
    # a release always maps forward, never backward).
    daily_z = pd.Series(0.0, index=trading_days)
    td_arr = trading_days.values
    for rel in releases:
        pos = int(np.searchsorted(td_arr, np.datetime64(rel.scheduled_utc.normalize()), side="left"))
        if pos >= len(td_arr):
            continue
        daily_z.iloc[pos] += rel.z_usd

    esi = np.empty(len(trading_days))
    acc = 0.0
    z_vals = daily_z.to_numpy()
    for i in range(len(trading_days)):
        acc = acc * decay + z_vals[i]
        esi[i] = acc
    return pd.Series(esi, index=trading_days)


# ---------------------------------------------------------------------------
# Weekly rebalance calendar
# ---------------------------------------------------------------------------

def build_rebalance_days(trading_days: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """One rebalance day per ISO week: the earliest weekday (Mon preferred,
    next available weekday if Monday is a holiday)."""
    iso = trading_days.isocalendar()
    key = iso["year"].astype(str) + "-" + iso["week"].astype(str).str.zfill(2)
    df = pd.DataFrame({"date": trading_days, "key": key.values, "weekday": trading_days.weekday})
    rebal = df.sort_values(["key", "weekday"]).groupby("key", sort=False).first()
    return pd.DatetimeIndex(sorted(rebal["date"]))


# ---------------------------------------------------------------------------
# Signal + net-return construction
# ---------------------------------------------------------------------------

def build_weekly_frame(
    price_panel: pd.DataFrame,
    esi: pd.Series,
    rebalance_days: pd.DatetimeIndex,
) -> pd.DataFrame:
    """One row per rebalance week k (from rebal[k] close to rebal[k+1] close):
    esi value at decision time, per-pair raw (unsigned) price return, and
    per-pair turn cost basis (spread_pct at the entry price)."""
    rows = []
    for k in range(len(rebalance_days) - 1):
        d0, d1 = rebalance_days[k], rebalance_days[k + 1]
        row = {"date": d0, "next_date": d1, "esi": esi.loc[d0]}
        for pair in PAIRS:
            p0, p1 = price_panel.loc[d0, pair], price_panel.loc[d1, pair]
            row[f"{pair}_ret"] = p1 / p0 - 1.0
            row[f"{pair}_spread_pct"] = PIP_SIZE[pair] / p0  # per-pip; scale by pips at use site
        rows.append(row)
    return pd.DataFrame(rows).set_index("date")


def signal_directions(wk: pd.DataFrame, signal_type: str) -> np.ndarray:
    """+1 = long USD, -1 = short USD, per rebalance week."""
    esi = wk["esi"].to_numpy()
    if signal_type == "LEVEL":
        sign = np.sign(esi)
    elif signal_type == "MOMENTUM":
        delta = esi - np.concatenate([np.full(MOMENTUM_LOOKBACK_WEEKS, np.nan), esi[:-MOMENTUM_LOOKBACK_WEEKS]])
        sign = np.sign(delta)
    else:
        raise ValueError(signal_type)
    sign[sign == 0] = 1.0  # negligible in practice; break ties long-USD
    return sign


def net_weekly_returns(
    wk: pd.DataFrame, directions: np.ndarray, spread_pips: float
) -> tuple[pd.Series, int]:
    """Pooled equal-weight net weekly return series + total turn count."""
    n = len(wk)
    valid = ~np.isnan(directions)
    per_pair = np.zeros((n, len(PAIRS)))
    turns = np.zeros(n, dtype=bool)
    prev_dir = None
    for i in range(n):
        if not valid[i]:
            per_pair[i, :] = np.nan
            continue
        d = directions[i]
        turns[i] = prev_dir is None or d != prev_dir
        prev_dir = d
        for j, pair in enumerate(PAIRS):
            pair_dir = PAIR_FLIP[pair] * d
            raw_ret = wk[f"{pair}_ret"].iloc[i]
            cost = wk[f"{pair}_spread_pct"].iloc[i] * spread_pips if turns[i] else 0.0
            per_pair[i, j] = pair_dir * raw_ret - cost
    with warnings.catch_warnings():
        # rows with no signal (MOMENTUM warmup) are all-NaN by design -> dropna() below
        warnings.filterwarnings("ignore", message="Mean of empty slice", category=RuntimeWarning)
        pooled = np.nanmean(per_pair, axis=1)
    pooled_series = pd.Series(pooled, index=wk.index)
    n_turns = int(turns[valid].sum())
    return pooled_series.dropna(), n_turns


def per_pair_net_returns(
    wk: pd.DataFrame, directions: np.ndarray, spread_pips: float
) -> dict[str, pd.Series]:
    out = {}
    n = len(wk)
    valid = ~np.isnan(directions)
    for pair in PAIRS:
        vals = np.full(n, np.nan)
        prev_dir = None
        for i in range(n):
            if not valid[i]:
                continue
            d = directions[i]
            turn = prev_dir is None or d != prev_dir
            prev_dir = d
            pair_dir = PAIR_FLIP[pair] * d
            raw_ret = wk[f"{pair}_ret"].iloc[i]
            cost = wk[f"{pair}_spread_pct"].iloc[i] * spread_pips if turn else 0.0
            vals[i] = pair_dir * raw_ret - cost
        out[pair] = pd.Series(vals, index=wk.index).dropna()
    return out


# ---------------------------------------------------------------------------
# Bootstrap metrics
# ---------------------------------------------------------------------------

def bootstrap_metrics(returns: pd.Series, n_bootstrap: int = N_BOOTSTRAP, seed: int = 42) -> dict:
    arr = returns.to_numpy()
    n = len(arr)
    if n < 5:
        return {"n": n, "ann_return": 0.0, "ci_low": 0.0, "ci_high": 0.0,
                "sharpe": 0.0, "max_dd": 0.0, "win_rate": 0.0}
    equity = np.cumprod(1 + arr)
    point_ann = float(equity[-1] ** (PERIODS_PER_YEAR / n) - 1)
    mean, std = arr.mean(), max(arr.std(ddof=1), 1e-9)
    sharpe = float(np.clip(mean / std * np.sqrt(PERIODS_PER_YEAR), -10, 10))
    running_max = np.maximum.accumulate(equity)
    max_dd = float((equity / running_max - 1).min())

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_bootstrap, n))
    boot = arr[idx]
    boot_equity_end = np.prod(1 + boot, axis=1)
    boot_ann = boot_equity_end ** (PERIODS_PER_YEAR / n) - 1
    ci_low, ci_high = np.percentile(boot_ann, [2.5, 97.5])
    return {
        "n": n, "ann_return": point_ann,
        "ci_low": float(ci_low), "ci_high": float(ci_high),
        "sharpe": sharpe, "max_dd": max_dd,
        "win_rate": float((arr > 0).mean()),
    }


def turns_per_year(n_turns: int, n_weeks: int) -> float:
    if n_weeks == 0:
        return 0.0
    return n_turns / (n_weeks / PERIODS_PER_YEAR)


# ---------------------------------------------------------------------------
# Random-sign control
# ---------------------------------------------------------------------------

def random_sign_control(
    wk: pd.DataFrame, p_flip: float, spread_pips: float, n_iter: int = N_BOOTSTRAP, seed: int = 7
) -> dict:
    """10,000 random-sign paths, same flip rate, same real price data,
    same cost model. Returns distribution of annualized returns."""
    n = len(wk)
    raw = np.column_stack([wk[f"{p}_ret"].to_numpy() for p in PAIRS])          # (n, 5)
    spread_pct = np.column_stack([wk[f"{p}_spread_pct"].to_numpy() for p in PAIRS])  # (n, 5)
    flip_mult = np.array([PAIR_FLIP[p] for p in PAIRS])

    rng = np.random.default_rng(seed)
    chunk = 1000
    ann_returns = np.empty(n_iter)
    filled = 0
    while filled < n_iter:
        b = min(chunk, n_iter - filled)
        signs = np.empty((b, n))
        signs[:, 0] = rng.choice([-1.0, 1.0], size=b)
        flip_draws = rng.random((b, n - 1)) < p_flip
        for t in range(1, n):
            signs[:, t] = np.where(flip_draws[:, t - 1], -signs[:, t - 1], signs[:, t - 1])
        turns = np.empty((b, n), dtype=bool)
        turns[:, 0] = True
        turns[:, 1:] = signs[:, 1:] != signs[:, :-1]

        # per-pair directional return: (iter, week, pair)
        pair_dir = signs[:, :, None] * flip_mult[None, None, :]
        gross = pair_dir * raw[None, :, :]
        cost = turns[:, :, None] * spread_pct[None, :, :] * spread_pips
        pooled = (gross - cost).mean(axis=2)  # (b, n)
        equity_end = np.prod(1 + pooled, axis=1)
        ann_returns[filled:filled + b] = equity_end ** (PERIODS_PER_YEAR / n) - 1
        filled += b

    return {
        "n_iter": n_iter,
        "mean_ann": float(ann_returns.mean()),
        "ci_low": float(np.percentile(ann_returns, 2.5)),
        "ci_high": float(np.percentile(ann_returns, 97.5)),
        "raw": ann_returns,
    }


# ---------------------------------------------------------------------------
# Buy-and-hold USD basket control
# ---------------------------------------------------------------------------

def buy_and_hold_usd(wk: pd.DataFrame, spread_pips: float) -> pd.Series:
    n = len(wk)
    directions = np.ones(n)
    pooled, _ = net_weekly_returns(wk, directions, spread_pips)
    return pooled


# ---------------------------------------------------------------------------
# Carry-factor proxy + correlation
# ---------------------------------------------------------------------------

def load_fred_rate(fred: FredClient, series_id: str) -> pd.Series:
    cache = {}
    if FRED_CACHE.exists():
        cache = json.loads(FRED_CACHE.read_text())
    if series_id in cache:
        s = pd.Series(cache[series_id])
        s.index = pd.to_datetime(s.index)
        return s
    data = fred.get_series(series_id, DATA_START.to_pydatetime(), DATA_END.to_pydatetime())
    if not data:
        raise RuntimeError(f"FRED returned no data for {series_id}")
    s = pd.Series([d["value"] for d in data], index=pd.to_datetime([d["date"] for d in data])).sort_index()
    cache[series_id] = {str(k): v for k, v in s.items()}
    FRED_CACHE.parent.mkdir(parents=True, exist_ok=True)
    FRED_CACHE.write_text(json.dumps(cache, default=str))
    return s


def build_carry_factor(price_panel: pd.DataFrame, rebalance_days: pd.DatetimeIndex) -> pd.Series:
    """Weekly rate-differential carry factor proxy over the same 5 pairs
    (same methodology as scripts/mc_value.py::carry_factor, resampled
    weekly instead of monthly). Long the higher-rate currency, equal
    weight, no cost (proxy only -- used solely for the correlation check)."""
    fred = FredClient()
    rates = {}
    for cur, sid in RATE_SERIES.items():
        s = load_fred_rate(fred, sid)
        rates[cur] = s.resample("ME").last().reindex(
            pd.date_range(DATA_START, DATA_END, freq="D"), method="ffill"
        )
    rate_panel = pd.DataFrame(rates)

    records = []
    for k in range(len(rebalance_days) - 1):
        d0, d1 = rebalance_days[k], rebalance_days[k + 1]
        pnl, npos = 0.0, 0
        for pair in PAIRS:
            base, quote = pair[:3], pair[3:]
            rb = rate_panel[base].asof(d0)
            rq = rate_panel[quote].asof(d0)
            if pd.isna(rb) or pd.isna(rq):
                continue
            direction = 1 if rb > rq else -1
            p0, p1 = price_panel.loc[d0, pair], price_panel.loc[d1, pair]
            spot_ret = p1 / p0 - 1.0
            accrual = (rb - rq) / 100.0 / PERIODS_PER_YEAR
            pnl += direction * (spot_ret + accrual)
            npos += 1
        records.append((d0, pnl / npos if npos else 0.0))
    return pd.Series([r for _, r in records], index=pd.DatetimeIndex([d for d, _ in records]))


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("Loading US releases and building standardized (no-look-ahead) surprises...")
    releases = load_us_releases()

    logger.info("Loading daily price panel for %s..." % PAIRS)
    price_series = {p: load_daily_close(p) for p in PAIRS}
    price_panel = pd.DataFrame(price_series).ffill().dropna()
    trading_days = build_trading_calendar(price_panel)
    rebalance_days = build_rebalance_days(trading_days)
    logger.info(f"Trading days: {len(trading_days)}, rebalance weeks: {len(rebalance_days)}")

    results: dict = {"variants": {}, "controls": {}, "walk_forward": {}, "carry_correlation": {}}

    esi_by_hl = {hl: compute_esi_series(releases, trading_days, hl) for hl in HALF_LIVES}

    weekly_frames = {}
    for hl in HALF_LIVES:
        weekly_frames[hl] = build_weekly_frame(price_panel, esi_by_hl[hl], rebalance_days)

    # Restrict analysis to weeks from 2020-02-01 onward (buffer past first
    # release so ESI is not degenerate zero for the very first weeks).
    BACKTEST_START = pd.Timestamp("2020-02-01")

    all_variant_rows = []
    variant_pooled_returns: dict[tuple[str, int, float], pd.Series] = {}
    for hl in HALF_LIVES:
        wk_full = weekly_frames[hl]
        wk = wk_full[wk_full.index >= BACKTEST_START]
        for sig_type in SIGNAL_TYPES:
            directions = signal_directions(wk, sig_type)
            for spread_pips, spread_label in [(BASE_SPREAD_PIPS, "base"), (STRESS_SPREAD_PIPS, "stress")]:
                pooled, n_turns = net_weekly_returns(wk, directions, spread_pips)
                m = bootstrap_metrics(pooled)
                m.update({
                    "signal": sig_type, "half_life": hl, "spread": spread_label,
                    "spread_pips": spread_pips, "n_turns": n_turns,
                    "turns_per_yr": turns_per_year(n_turns, len(pooled)),
                })
                all_variant_rows.append(m)
                variant_pooled_returns[(sig_type, hl, spread_pips)] = pooled
                logger.info(
                    f"{sig_type} hl={hl} spread={spread_label}: ann={m['ann_return']*100:+.1f}% "
                    f"CI=[{m['ci_low']*100:+.1f},{m['ci_high']*100:+.1f}]% Sharpe={m['sharpe']:.2f} "
                    f"turns/yr={m['turns_per_yr']:.1f}"
                )
    results["variants"] = all_variant_rows

    # Per-pair results at base + stress, for every (signal, half_life)
    per_pair_rows = []
    for hl in HALF_LIVES:
        wk_full = weekly_frames[hl]
        wk = wk_full[wk_full.index >= BACKTEST_START]
        for sig_type in SIGNAL_TYPES:
            directions = signal_directions(wk, sig_type)
            for spread_pips, spread_label in [(BASE_SPREAD_PIPS, "base"), (STRESS_SPREAD_PIPS, "stress")]:
                per_pair = per_pair_net_returns(wk, directions, spread_pips)
                for pair, series in per_pair.items():
                    m = bootstrap_metrics(series)
                    m.update({"signal": sig_type, "half_life": hl, "spread": spread_label, "pair": pair})
                    per_pair_rows.append(m)
    results["per_pair"] = per_pair_rows

    # -------------------------------------------------------------------
    # Walk-forward: select best variant on TRAIN (pooled, base spread,
    # by CI-low), evaluate OOS on TEST.
    # -------------------------------------------------------------------
    train_candidates = []
    for hl in HALF_LIVES:
        wk_full = weekly_frames[hl]
        wk_train = wk_full[(wk_full.index >= BACKTEST_START) & (wk_full.index.year.isin(TRAIN_YEARS))]
        for sig_type in SIGNAL_TYPES:
            directions = signal_directions(wk_train, sig_type)
            pooled, n_turns = net_weekly_returns(wk_train, directions, BASE_SPREAD_PIPS)
            m = bootstrap_metrics(pooled)
            m.update({"signal": sig_type, "half_life": hl})
            train_candidates.append(m)
    best_train = max(train_candidates, key=lambda r: r["ci_low"])
    sel_signal, sel_hl = best_train["signal"], best_train["half_life"]
    logger.info(f"Walk-forward selected variant: {sel_signal} half_life={sel_hl} (train CI-low={best_train['ci_low']*100:+.1f}%)")

    wk_full = weekly_frames[sel_hl]
    wk_test = wk_full[(wk_full.index >= BACKTEST_START) & (wk_full.index.year.isin(TEST_YEARS))]
    directions_test = signal_directions(wk_test, sel_signal)
    pooled_test, n_turns_test = net_weekly_returns(wk_test, directions_test, BASE_SPREAD_PIPS)
    m_test = bootstrap_metrics(pooled_test)
    m_test.update({"signal": sel_signal, "half_life": sel_hl, "n_turns": n_turns_test})

    results["walk_forward"] = {
        "selected_signal": sel_signal, "selected_half_life": sel_hl,
        "train": best_train, "test_oos": m_test,
    }
    logger.info(
        f"WF selected {sel_signal}/hl={sel_hl}: IS ann={best_train['ann_return']*100:+.1f}% "
        f"CI=[{best_train['ci_low']*100:+.1f},{best_train['ci_high']*100:+.1f}]% | "
        f"OOS ann={m_test['ann_return']*100:+.1f}% CI=[{m_test['ci_low']*100:+.1f},{m_test['ci_high']*100:+.1f}]%"
    )

    # -------------------------------------------------------------------
    # Controls, evaluated on the FULL backtest window for the selected
    # (winning-by-training) variant.
    # -------------------------------------------------------------------
    wk_sel_full = weekly_frames[sel_hl]
    wk_sel = wk_sel_full[wk_sel_full.index >= BACKTEST_START]
    directions_sel = signal_directions(wk_sel, sel_signal)
    pooled_sel, n_turns_sel = net_weekly_returns(wk_sel, directions_sel, BASE_SPREAD_PIPS)
    m_sel = bootstrap_metrics(pooled_sel)
    p_flip = n_turns_sel / max(len(pooled_sel) - 1, 1)

    logger.info(f"Running random-sign control ({N_BOOTSTRAP} iterations, p_flip={p_flip:.3f})...")
    control = random_sign_control(wk_sel, p_flip, BASE_SPREAD_PIPS, n_iter=N_BOOTSTRAP)
    pct_rank = float((control["raw"] < m_sel["ann_return"]).mean())

    bh = buy_and_hold_usd(wk_sel, BASE_SPREAD_PIPS)
    m_bh = bootstrap_metrics(bh)

    results["controls"] = {
        "selected_variant": {"signal": sel_signal, "half_life": sel_hl, "metrics": m_sel},
        "buy_and_hold_usd": m_bh,
        "random_sign": {
            "p_flip": p_flip, "mean_ann": control["mean_ann"],
            "ci_low": control["ci_low"], "ci_high": control["ci_high"],
            "esi_percentile_in_random_dist": pct_rank,
            "esi_ci_low_beats_random_ci_high": bool(m_sel["ci_low"] > control["ci_high"]),
        },
    }
    logger.info(
        f"Selected variant ann={m_sel['ann_return']*100:+.1f}% CI=[{m_sel['ci_low']*100:+.1f},{m_sel['ci_high']*100:+.1f}]% | "
        f"Buy&hold USD ann={m_bh['ann_return']*100:+.1f}% CI=[{m_bh['ci_low']*100:+.1f},{m_bh['ci_high']*100:+.1f}]% | "
        f"Random-sign mean={control['mean_ann']*100:+.1f}% CI=[{control['ci_low']*100:+.1f},{control['ci_high']*100:+.1f}]% "
        f"(ESI at percentile {pct_rank*100:.1f} of random dist)"
    )

    # -------------------------------------------------------------------
    # Carry correlation
    # -------------------------------------------------------------------
    logger.info("Building carry-factor proxy (FRED short rates) and correlating...")
    carry = build_carry_factor(price_panel, rebalance_days)
    aligned = pd.concat([pooled_sel.rename("esi"), carry.rename("carry")], axis=1, sort=True).dropna()
    corr = float(aligned["esi"].corr(aligned["carry"])) if len(aligned) > 2 else float("nan")
    results["carry_correlation"] = {"corr": corr, "n_weeks": len(aligned)}
    logger.info(f"ESI vs carry-factor correlation: {corr:+.3f} (n={len(aligned)} weeks)")

    RESULTS_JSON.write_text(json.dumps(results, indent=2, default=str))
    logger.info(f"Results written -> {RESULTS_JSON}")


if __name__ == "__main__":
    main()
