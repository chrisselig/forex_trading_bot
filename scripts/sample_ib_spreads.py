#!/usr/bin/env python3
"""Standalone IDEALPRO spread sampler for USDZAR / USDTRY (spec 17, Phase A.4).

Connects to a running TWS/Gateway, snapshots live bid/ask for the exotic
pairs the ambient/event straddle trades, appends one row per pair to
scripts/data/ib_spread_samples.csv, and exits. Run hourly on weekdays via
cron to accumulate a real IDEALPRO spread series for a future report — the
trade journal only holds ~30 spreads at trade time, which is far too few and
too event-clustered to characterise the true spread distribution.

WHY THIS EXISTS: report 17 found Dukascopy's exotic tick spreads (retail
feed) run 3-8x wider than the handful of real IDEALPRO entry_spread_pips in
the trade journal. Neither source is adequate to cost an all-day ambient
strategy: Dukascopy is the wrong venue, the journal is tiny and only sampled
at ~12:00/14:00 UTC on event days. This sampler builds the missing dataset —
IDEALPRO spreads across all sessions, event and non-event days alike.

SAFETY:
  - clientId=9 ALWAYS. clientId=1 is the live bot — never use it here.
  - Read-only: reqMktData snapshots only. Places no orders.
  - Connects, samples, disconnects, exits. Holds no persistent session.

Usage:
    python scripts/sample_ib_spreads.py                 # port 7497 (default)
    python scripts/sample_ib_spreads.py --port 4002     # paper gateway
    python scripts/sample_ib_spreads.py --host 127.0.0.1 --port 7497

Suggested cron (weekdays, hourly, 06:00-21:00 MT — DO NOT install
automatically; add manually if you want the collection running):

    0 6-21 * * 1-5 /home/doopdeep/anaconda3/envs/forex-bot/bin/python \\
        /home/doopdeep/00_data_projects/forex_trading_bot/scripts/sample_ib_spreads.py \\
        >> /home/doopdeep/ibc/logs/ib_spread_sampler.log 2>&1
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import UTC, datetime
from pathlib import Path

from ib_async import IB, Forex

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_CSV = PROJECT_ROOT / "scripts" / "data" / "ib_spread_samples.csv"

PAIRS = ["USDZAR", "USDTRY"]
PIP_SIZE = 0.0001  # both pairs quote to 4 dp

CLIENT_ID = 9  # NEVER 1 — that is the live bot
SNAPSHOT_WAIT_S = 6.0
CSV_HEADER = [
    "timestamp_utc", "pair", "bid", "ask", "mid", "spread_pips", "session_anchor",
]


def _session_anchor(hour_utc: int) -> str:
    """Nearest of the report-17 session anchors (03/09/14/20 UTC)."""
    anchors = [3, 9, 14, 20]
    best = min(anchors, key=lambda h: min(abs(hour_utc - h), 24 - abs(hour_utc - h)))
    return f"{best:02d}:00"


def sample(host: str, port: int) -> int:
    ib = IB()
    try:
        ib.connect(host, port, clientId=CLIENT_ID, timeout=15, readonly=True)
    except Exception as exc:  # noqa: BLE001 — standalone tool, report loudly and exit
        print(f"ERROR: could not connect to TWS at {host}:{port} "
              f"(clientId={CLIENT_ID}): {exc}", file=sys.stderr)
        return 1

    rows: list[dict] = []
    try:
        for pair in PAIRS:
            contract = Forex(pair)
            ib.qualifyContracts(contract)
            ticker = ib.reqMktData(contract, snapshot=True)
            ib.sleep(SNAPSHOT_WAIT_S)
            bid, ask = ticker.bid, ticker.ask
            ib.cancelMktData(contract)
            if bid is None or ask is None or bid != bid or ask != ask or bid <= 0 or ask <= 0:
                print(f"WARN: no valid quote for {pair} (bid={bid}, ask={ask})",
                      file=sys.stderr)
                continue
            now = datetime.now(UTC)
            spread_pips = (ask - bid) / PIP_SIZE
            rows.append({
                "timestamp_utc": now.isoformat(),
                "pair": pair,
                "bid": bid,
                "ask": ask,
                "mid": (bid + ask) / 2,
                "spread_pips": round(spread_pips, 2),
                "session_anchor": _session_anchor(now.hour),
            })
            print(f"{pair}: bid={bid} ask={ask} spread={spread_pips:.1f} pips")
    finally:
        ib.disconnect()

    if not rows:
        print("ERROR: no valid quotes sampled — nothing written", file=sys.stderr)
        return 2

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    write_header = not OUT_CSV.exists()
    with OUT_CSV.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_HEADER)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)
    print(f"appended {len(rows)} row(s) -> {OUT_CSV}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Sample IDEALPRO spreads for USDZAR/USDTRY")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7497,
                        help="TWS/Gateway port (7497 paper TWS, 4002 paper gateway)")
    args = parser.parse_args()
    sys.exit(sample(args.host, args.port))


if __name__ == "__main__":
    main()
