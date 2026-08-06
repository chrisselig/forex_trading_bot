"""Monte Carlo + walk-forward validation for the carry strategy's entry gate.

The carry strategy (src/forex_bot/strategy/carry.py) has never been backtested
end-to-end — `min_differential_pct: 2.0` was a launch-time default (PR #44,
"starts disabled, enable after paper-trade validation") and was never revisited
with data, unlike the straddle strategy's MC-validated parameters. This script
closes that gap:

  1. Sweeps the differential threshold per pair (0.5% .. 4.0%) and walk-forward
     validates it (optimize on 2020-2024, test on 2025-2026 OOS) the same way
     mc_momentum.py / mc_value.py do for their strategies.
  2. Reports whether the CURRENT config value (2.0%) is actually near-optimal,
     or just a round number that happens to work / doesn't.
  3. Reports weekly-return correlation across the current 5-pair carry basket,
     to check the "these aren't 5 independent bets, 3 of them are short USD"
     diversification concern directly (USDZAR/USDTRY/USDMXN all fund off USD;
     AUDJPY/NZDJPY both fund off JPY).
  4. Screens GBPJPY as a candidate 6th pair (flagged in a live-rate check on
     2026-08-05 as the one non-exotic pair currently clearing the differential
     threshold — see docs/research/todo.md "Strategy Research Candidates").

Method:
  - Daily interest-rate differential from FRED (OECD IRSTCI01* / IR3TIB01NZM156N
    policy-rate series, same series CarryManager uses live), lagged 60 days to
    avoid look-ahead bias (OECD monthly data publishes ~1-2 months after the
    observation month; CarryManager's own age_days>120 warning threshold is the
    same ballpark).
  - Weekly rebalance (Monday, matching carry.rebalance_day_of_week=mon): open/
    hold/close a position by comparing |differential| to the threshold.
  - Daily stop-loss check (matching carry.stop_loss_pct=5.0) marked-to-market
    from entry price — closes the position intraweek if breached.
  - Swap accrual modeled as |differential| / 365 per day held (an approximation
    of the roll/swap point — see Caveats).
  - Round-trip cost charged on every open/close (bps of notional, same table as
    mc_momentum.py).

Usage:
    python scripts/mc_carry_threshold.py [--refresh-data]
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import dukascopy_python as dp
import numpy as np
import pandas as pd

from dotenv import load_dotenv

load_dotenv()

COST_BPS = {"USDZAR": 15.0, "USDTRY": 35.0, "USDMXN": 12.0, "AUDJPY": 4.0, "NZDJPY": 5.0, "GBPJPY": 4.0}

# Current live basket (config/settings.yaml carry.instruments) + one candidate.
CURRENT_PAIRS = ["USDZAR", "USDTRY", "USDMXN", "AUDJPY", "NZDJPY"]
CANDIDATE_PAIRS = ["GBPJPY"]
PAIRS = CURRENT_PAIRS + CANDIDATE_PAIRS

FRED_RATE_SERIES = {
    "USD": "IRSTCI01USM156N", "ZAR": "IRSTCI01ZAM156N", "AUD": "IRSTCI01AUM156N",
    "JPY": "IRSTCI01JPM156N", "MXN": "IRSTCI01MXM156N", "TRY": "IRSTCI01TRM156N",
    "NZD": "IR3TIB01NZM156N", "GBP": "IRSTCI01GBM156N",
}

WEEKS_PER_YEAR = 52
STOP_LOSS_PCT = 5.0  # matches carry.stop_loss_pct
RATE_LAG_DAYS = 60  # OECD monthly publication lag, avoids look-ahead
THRESHOLD_GRID = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
CURRENT_THRESHOLD = 2.0

DATA_DIR = Path(__file__).parent / "data" / "dukascopy"
DATA_START = pd.Timestamp("2019-06-01")
DATA_END = pd.Timestamp("2026-08-01")
TRAIN_END = pd.Timestamp("2025-01-01")


def _instrument(pair: str) -> str:
    return f"{pair[:3]}/{pair[3:]}"


def load_daily_close(pair: str, refresh: bool = False) -> pd.Series | None:
    cache = DATA_DIR / f"{pair}_daily.csv"
    if cache.exists() and not refresh:
        s = pd.read_csv(cache, index_col=0, parse_dates=True)["close"]
        s.index = pd.to_datetime(s.index, utc=True).tz_localize(None)
        return s
    print(f"  fetching daily {pair} ...")
    try:
        df = dp.fetch(
            _instrument(pair), dp.INTERVAL_DAY_1, dp.OFFER_SIDE_BID,
            DATA_START.to_pydatetime(), DATA_END.to_pydatetime(),
        )
    except Exception as e:  # noqa: BLE001 — data source can fail per-pair
        print(f"    !! {pair} fetch failed: {e}")
        return None
    if df is None or len(df) == 0:
        return None
    s = df["close"].copy()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    s.name = "close"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    s.to_csv(cache)
    return s


def load_fred_rate_daily(ccy: str) -> pd.Series:
    """Daily-forward-filled policy rate for `ccy`, shifted RATE_LAG_DAYS to
    simulate real-world publication lag (no look-ahead)."""
    from forex_bot.calendar.fred_client import FredClient

    fred = FredClient()
    obs = fred.get_series(FRED_RATE_SERIES[ccy], start_date=datetime(2019, 1, 1), end_date=datetime(2026, 8, 5))
    idx = pd.DatetimeIndex([o["date"] for o in obs]) + pd.Timedelta(days=RATE_LAG_DAYS)
    s = pd.Series([o["value"] for o in obs], index=idx, name=ccy).sort_index()
    daily = s.reindex(pd.date_range(idx.min(), DATA_END, freq="D")).ffill()
    return daily


def build_differential(pair: str, rates: dict[str, pd.Series]) -> pd.Series:
    base, quote = pair[:3], pair[3:]
    diff = (rates[quote] - rates[base]).dropna()
    diff.name = pair
    return diff


def backtest_pair(prices: pd.Series, diff: pd.Series, threshold: float, cost_bps: float) -> pd.Series:
    """Day-by-day carry simulation. Returns a daily return series (position
    P&L + swap accrual, net of turnover cost, in fraction-of-notional terms)."""
    idx = prices.index.intersection(diff.index)
    prices = prices.reindex(idx).ffill()
    diff = diff.reindex(idx).ffill()
    if len(idx) < 260:
        return pd.Series(dtype=float)

    cost = cost_bps / 10_000
    pos_sign = 0
    entry_price = None
    snapshot_diff = 0.0
    daily_returns = []
    dates = []

    for i in range(1, len(idx)):
        date = idx[i]
        price_today, price_yest = prices.iloc[i], prices.iloc[i - 1]
        ret = 0.0

        if date.weekday() == 0:  # Monday rebalance
            d = diff.iloc[i]
            if d >= threshold:
                target = -1
            elif d <= -threshold:
                target = 1
            else:
                target = 0
            if target != pos_sign:
                if pos_sign != 0:
                    ret -= cost
                if target != 0:
                    ret -= cost
                    entry_price = price_today
                    snapshot_diff = abs(d)
                pos_sign = target

        if pos_sign != 0 and entry_price is not None and price_yest > 0:
            price_ret = pos_sign * (price_today / price_yest - 1)
            swap = snapshot_diff / 100 / 365
            ret += price_ret + swap

            unrealized = pos_sign * (price_today / entry_price - 1)
            if unrealized <= -STOP_LOSS_PCT / 100:
                ret -= cost
                pos_sign = 0
                entry_price = None

        daily_returns.append(ret)
        dates.append(date)

    daily = pd.Series(daily_returns, index=pd.DatetimeIndex(dates))
    weekly = daily.resample("W-MON", label="left", closed="left").apply(lambda x: (1 + x).prod() - 1)
    return weekly


def metrics(weekly: pd.Series) -> dict:
    if len(weekly) == 0:
        return {"n": 0, "sharpe": 0.0, "ann_return": 0.0, "total_return": 0.0, "win_rate": 0.0, "max_dd": 0.0}
    mean, std = weekly.mean(), weekly.std(ddof=1)
    sharpe = (mean / std * np.sqrt(WEEKS_PER_YEAR)) if std > 0 else 0.0
    ann_return = (1 + mean) ** WEEKS_PER_YEAR - 1
    equity = (1 + weekly).cumprod()
    max_dd = (equity / equity.cummax() - 1).min()
    return {"n": len(weekly), "sharpe": sharpe, "ann_return": ann_return,
             "total_return": equity.iloc[-1] - 1, "win_rate": (weekly > 0).mean(), "max_dd": max_dd}


def monte_carlo(weekly: pd.Series, runs: int = 10_000, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    arr = weekly.to_numpy()
    n = len(arr)
    if n == 0:
        return {"median_total": 0.0, "p5_total": 0.0, "p95_total": 0.0, "p_negative": 1.0}
    totals = np.empty(runs)
    for k in range(runs):
        totals[k] = np.prod(1 + arr[rng.integers(0, n, n)]) - 1
    return {"median_total": float(np.median(totals)), "p5_total": float(np.percentile(totals, 5)),
             "p95_total": float(np.percentile(totals, 95)), "p_negative": float((totals < 0).mean())}


def optimize_is(prices: pd.Series, diff: pd.Series, cost_bps: float) -> tuple[float, list]:
    results = []
    for th in THRESHOLD_GRID:
        w = backtest_pair(prices, diff, th, cost_bps)
        m = metrics(w[w.index < TRAIN_END])
        results.append((th, m["sharpe"], m["ann_return"], m["n"]))
    results.sort(key=lambda r: r[1], reverse=True)
    return results[0][0], results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-data", action="store_true")
    args = ap.parse_args()

    print("Loading FRED policy rates...")
    currencies = {c for p in PAIRS for c in (p[:3], p[3:])}
    rates = {ccy: load_fred_rate_daily(ccy) for ccy in currencies}

    print("Loading Dukascopy daily prices...")
    prices = {p: load_daily_close(p, refresh=args.refresh_data) for p in PAIRS}
    prices = {p: s for p, s in prices.items() if s is not None}

    diffs = {p: build_differential(p, rates) for p in PAIRS if p in prices}

    pair_rows = []
    weekly_by_pair = {}
    for pair in PAIRS:
        if pair not in prices:
            print(f"  !! {pair}: no price data, skipped")
            continue
        best_th, ranking = optimize_is(prices[pair], diffs[pair], COST_BPS[pair])
        w_best = backtest_pair(prices[pair], diffs[pair], best_th, COST_BPS[pair])
        w_current = backtest_pair(prices[pair], diffs[pair], CURRENT_THRESHOLD, COST_BPS[pair])

        m_is_best = metrics(w_best[w_best.index < TRAIN_END])
        m_oos_best = metrics(w_best[w_best.index >= TRAIN_END])
        m_oos_current = metrics(w_current[w_current.index >= TRAIN_END])
        mc_best = monte_carlo(w_best[w_best.index >= TRAIN_END])

        weekly_by_pair[pair] = w_current[w_current.index >= TRAIN_END]

        pair_rows.append({
            "pair": pair, "best_th": best_th, "is_sharpe": m_is_best["sharpe"],
            "oos_sharpe_best": m_oos_best["sharpe"], "oos_ann_best": m_oos_best["ann_return"],
            "oos_sharpe_2pct": m_oos_current["sharpe"], "oos_ann_2pct": m_oos_current["ann_return"],
            "mc_p5": mc_best["p5_total"], "mc_pneg": mc_best["p_negative"],
            "n_oos": m_oos_best["n"], "ranking": ranking, "candidate": pair in CANDIDATE_PAIRS,
        })

        print(f"\n{pair} (cost={COST_BPS[pair]}bps):")
        print(f"  IS-optimal threshold: {best_th}%  (IS Sharpe {m_is_best['sharpe']:.2f})")
        print(f"  OOS @ IS-optimal:  Sharpe={m_oos_best['sharpe']:+.2f}  ann={m_oos_best['ann_return']*100:+.1f}%  "
              f"MC5th={mc_best['p5_total']*100:+.1f}%  P(neg)={mc_best['p_negative']*100:.0f}%")
        print(f"  OOS @ current 2.0%: Sharpe={m_oos_current['sharpe']:+.2f}  ann={m_oos_current['ann_return']*100:+.1f}%")

    # Correlation of the CURRENT basket's weekly carry returns (position-direction-
    # adjusted P&L, at the live 2.0% threshold) — answers the diversification question.
    corr_pairs = [p for p in CURRENT_PAIRS if p in weekly_by_pair]
    corr_df = pd.DataFrame({p: weekly_by_pair[p] for p in corr_pairs}).dropna(how="all")
    corr = corr_df.corr()

    print("\n=== Weekly return correlation, current basket (OOS 2025-2026, @2.0% threshold) ===")
    print(corr.round(2))

    _write_report(pair_rows, corr, corr_pairs)


def _verdict(row: dict) -> str:
    if row["oos_sharpe_best"] > 0.3 and row["mc_p5"] > -0.10:
        return "PASS"
    if row["oos_ann_best"] > 0:
        return "BORDERLINE"
    return "FAIL"


def _write_report(pair_rows: list[dict], corr: pd.DataFrame, corr_pairs: list[str]) -> None:
    report = Path(__file__).parent.parent / "docs" / "research" / "21-mc-carry-threshold.md"

    pair_table = "\n".join(
        f"| {r['pair']}{' *(candidate)*' if r['candidate'] else ''} | {r['best_th']}% | {r['is_sharpe']:.2f} | "
        f"{r['oos_sharpe_best']:+.2f} | {r['oos_ann_best']*100:+.1f}% | {r['oos_sharpe_2pct']:+.2f} | "
        f"{r['oos_ann_2pct']*100:+.1f}% | {r['mc_p5']*100:+.1f}% | {r['mc_pneg']*100:.0f}% | **{_verdict(r)}** |"
        for r in pair_rows
    )

    # High-level correlation summary: max off-diagonal |corr| within the USD-quoted
    # sub-group and the JPY-funded sub-group, plus cross-group.
    usd_group = [p for p in ["USDZAR", "USDTRY", "USDMXN"] if p in corr.columns]
    jpy_group = [p for p in ["AUDJPY", "NZDJPY"] if p in corr.columns]

    def _avg_offdiag(cols: list[str]) -> float | None:
        if len(cols) < 2:
            return None
        sub = corr.loc[cols, cols].to_numpy()
        n = len(cols)
        mask = ~np.eye(n, dtype=bool)
        return float(sub[mask].mean())

    usd_avg = _avg_offdiag(usd_group)
    jpy_avg = _avg_offdiag(jpy_group)

    corr_table = "| |" + "|".join(corr.columns) + "|\n"
    corr_table += "|---" * (len(corr.columns) + 1) + "|\n"
    for row in corr.index:
        corr_table += f"| **{row}** |" + "|".join(f"{corr.loc[row, c]:+.2f}" for c in corr.columns) + "|\n"

    threshold_grid_str = ", ".join(f"{t}%" for t in THRESHOLD_GRID)
    best_current_diff = [r for r in pair_rows if not r["candidate"] and abs(r["best_th"] - CURRENT_THRESHOLD) > 0.01]

    report.write_text(f"""# Monte Carlo — Carry Strategy Differential Threshold

**Analysis date:** 2026-08-05
**Strategy:** `src/forex_bot/strategy/carry.py` — `min_differential_pct` entry gate
**Data:** Dukascopy daily close (price) + FRED OECD policy-rate series (differential,
lagged {RATE_LAG_DAYS}d to avoid look-ahead)
**Walk-forward:** train < 2025-01, test >= 2025-01 (out-of-sample)
**Threshold grid:** {threshold_grid_str}

## Why this exists

`min_differential_pct: 2.0` has never been backtested. It was set as a launch
default when the carry strategy was first built and never revisited with data —
unlike the straddle strategy, whose every parameter traces back to an MC/walk-
forward report in this directory. This closes that gap and, along the way,
answers two live questions: whether USDMXN should be pushed into the basket
despite sitting below 2.0% today, and whether the current 5-pair basket is
actually diversified.

## Per-pair: is 2.0% actually the right threshold?

| Pair | IS-optimal threshold | IS Sharpe | OOS Sharpe @optimal | OOS ann. @optimal | OOS Sharpe @2.0% | OOS ann. @2.0% | MC 5th %ile | P(losing OOS) | Verdict |
|------|----------------------|-----------|----------------------|--------------------|--------------------|-----------------|-------------|----------------|---------|
{pair_table}

{"**2.0% is not universally optimal** — " + ", ".join(f"{r['pair']} prefers {r['best_th']}%" for r in best_current_diff) + "." if best_current_diff else "**2.0% lands close to the in-sample optimum for every pair tested** — the round-number default holds up better than expected."}

## Diversification: is the current basket actually 5 independent bets?

Weekly OOS (2025-2026) return correlation across the live basket, each pair run
at its own carry direction (so this is the correlation of realized carry P&L,
not raw FX returns):

{corr_table}

{f"- **USD-quoted group** (USDZAR/USDTRY/USDMXN) average pairwise correlation: **{usd_avg:+.2f}**" if usd_avg is not None else ""}
{f"- **JPY-funded group** (AUDJPY/NZDJPY) average pairwise correlation: **{jpy_avg:+.2f}**" if jpy_avg is not None else ""}

The concern raised — that USDZAR/USDTRY/USDMXN sharing USD as the funding leg
isn't real diversification — {"is confirmed by the data: correlation between the USD-quoted legs is meaningfully positive, meaning a broad USD move (e.g. a risk-off dollar rally) hits all three simultaneously rather than being independent." if (usd_avg or 0) > 0.3 else "is only partially confirmed here: the measured correlation is lower than the shared-funding-currency intuition suggests, likely because each EM currency's idiosyncratic risk (SARB/BOM/Banxico policy surprises, local political risk) dominates the shared-USD component at weekly granularity." if usd_avg is not None else "could not be fully evaluated — see per-pair verdicts above."}

## USDMXN specifically

{[r for r in pair_rows if r['pair']=='USDMXN'][0]['pair'] if any(r['pair']=='USDMXN' for r in pair_rows) else 'USDMXN'} is currently **not open** live — its FRED differential sits at ~1.56% as of the
last live pull (2026-08-05), below the 2.0% gate. The walk-forward numbers above
are the answer to "should it be pushed in anyway": see its row in the table —
judge by OOS Sharpe/annualized return at the IS-optimal threshold, not by
whether today's snapshot happens to clear 2.0%.

## Candidate: GBPJPY

Flagged separately (`docs/research/todo.md`, live differential ~2.89% as of
2026-08-05) as the one non-exotic pair currently clearing the gate. See its row
above for walk-forward verdict before adding it to `carry.instruments` — per
CLAUDE.md's Analysis-Driven Configuration rule, it should not be added without
this kind of validation, and the user should confirm explicitly even if it passes.

## Caveats

- Swap accrual is modeled as `|differential| / 365` per day held — an
  approximation of the true broker roll/swap point, which also embeds a
  broker-specific spread on top of the raw rate differential. Real accrued
  interest (tracked live via `InterestJournal` / IB Flex reports) may differ.
- FRED policy rates are lagged {RATE_LAG_DAYS} days to avoid look-ahead, but IB's
  actual swap points reprice continuously off overnight funding markets, not
  monthly OECD releases — this is a proxy, not a live-accurate cost.
- Stop-loss is checked once per day (EOD close), not intrabar — live execution
  with `place_order_with_stop` reacts faster (or slower, on gaps) than this.
- Single train/test split, same limitation noted in the other MC reports here.
- Costs modeled on turnover only; exotic (ZAR/TRY/MXN) slippage at weekly
  rebalance is uncertain, same caveat as `13-mc-momentum.md`.
- Re-run with `/trade-review` once enough live carry paper data accumulates to
  cross-check the swap-accrual approximation against real `InterestJournal` data.
""")
    print(f"\nReport written to {report}")


if __name__ == "__main__":
    main()
