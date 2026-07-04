#!/usr/bin/env python3
"""One-time cleanup for orders stuck SUBMITTED/PENDING due to a journal bug.

Before the fix in this branch, ExecutionEngine journaled orders before
placing them with IB and never persisted ib_order_id back onto the
OrderRecord row. That meant PositionMonitor's fill/cancel/reject handlers
(which key off OrderRecord.ib_order_id) could never find these rows, so they
stayed PENDING/SUBMITTED forever with no matching trade.

This script marks those orphaned rows CANCELLED. It only touches rows where
ib_order_id IS NULL AND status IN ('PENDING', 'SUBMITTED') — orders that
already have an ib_order_id are unaffected by the bug and are left alone.

Defaults to a dry run (prints what would change, writes nothing). Pass
--execute to actually write. If TURSO_DATABASE_URL / TURSO_AUTH_TOKEN are
set, the same status change is mirrored to the Turso `orders` table by
local order id (matching how TursoSyncer pushes use the local DB id as
order_id).
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "forex_bot.db"

_STALE_STATUSES = ("PENDING", "SUBMITTED")


def find_stale_order_ids(conn: sqlite3.Connection) -> list[int]:
    """Return database IDs of orders orphaned by the ib_order_id bug."""
    placeholders = ",".join("?" for _ in _STALE_STATUSES)
    cursor = conn.execute(
        f"SELECT id FROM orders WHERE ib_order_id IS NULL "
        f"AND status IN ({placeholders})",
        _STALE_STATUSES,
    )
    return [row[0] for row in cursor.fetchall()]


def cancel_stale_orders(conn: sqlite3.Connection, order_ids: list[int]) -> None:
    """Mark the given order IDs CANCELLED in the local SQLite DB."""
    if not order_ids:
        return
    placeholders = ",".join("?" for _ in order_ids)
    conn.execute(
        f"UPDATE orders SET status = 'CANCELLED' WHERE id IN ({placeholders})",
        order_ids,
    )
    conn.commit()


def mirror_to_turso(order_ids: list[int]) -> None:
    """Mirror the CANCELLED status to Turso for the same local order IDs.

    Skips silently (with a log line) if Turso credentials are not
    configured — this cleanup must never require Turso to run.
    """
    database_url = os.environ.get("TURSO_DATABASE_URL", "")
    auth_token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if not database_url or not auth_token:
        logger.info("Turso credentials not set — skipping Turso mirror")
        return
    if not order_ids:
        return

    import libsql_experimental as libsql

    conn = libsql.connect(database=database_url, auth_token=auth_token)
    for order_id in order_ids:
        conn.execute(
            "UPDATE orders SET status = 'CANCELLED' WHERE id = ?",
            (order_id,),
        )
    conn.commit()
    logger.info(f"Turso: mirrored CANCELLED status for {len(order_ids)} order(s)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cancel stale orders orphaned by the pre-fix ib_order_id journaling bug"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually write changes. Without this flag the script only reports what it would do.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicitly request a dry run (this is the default with no flags).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dry_run = not args.execute

    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    try:
        order_ids = find_stale_order_ids(conn)
        print(f"Found {len(order_ids)} stale order(s) (ib_order_id IS NULL, status in {_STALE_STATUSES})")

        if dry_run:
            print("Dry run — no changes written. Re-run with --execute to apply.")
            if order_ids:
                print(f"Would cancel order IDs: {order_ids}")
            return

        cancel_stale_orders(conn, order_ids)
        print(f"Updated {len(order_ids)} row(s) to status=CANCELLED")
    finally:
        conn.close()

    mirror_to_turso(order_ids)


if __name__ == "__main__":
    main()
