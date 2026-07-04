#!/usr/bin/env python3
"""One-time cleanup for near-duplicate event rows created by the pre-fix
Forex Factory / static-calendar ping-pong bug (see EventStore.save_events).

Before the source-aware save_events fix, every calendar refresh cycle saved
Forex Factory events first, then static-calendar events (config/static_
events.yaml). Because EventStore.save_events treated any same-day match at
a different time as a "reschedule", events covered by both feeds (e.g. BOJ
Policy Rate) got a fresh duplicate row inserted whenever the two feeds'
insert order or exact-match window lined up wrong, and existing rows kept
flip-flopping between the two feeds' times. This script removes the stale
duplicate rows left over from that period and backfills the new `source`
column so the source-aware fix has a clean baseline to work from.

Dedup rule: group events by (title, country). Within a group, sort by
scheduled_at and cluster rows that are within 2 days of their neighbor
(transitively) into the same duplicate group. Any cluster with more than
one row is a duplicate group; keep the row with the highest id (most
recently created — this matches Forex Factory's more precise timestamps
for events covered by both feeds, and the corrected/latest entry for
static-only events) and delete the rest.

Before deleting a row, any orders/trades referencing it via event_id are
remapped to point at the surviving row so no journal entry loses its event
link.

Defaults to a dry run (prints what would change, writes nothing). Pass
--execute to actually write. If TURSO_DATABASE_URL / TURSO_AUTH_TOKEN are
set, the same deletions and event_id remaps are mirrored to Turso by local
event id (matching how TursoSyncer pushes use the local DB id as the Turso
event id). Turso mirroring is skipped cleanly (with a log line) if those
env vars are unset, and never crashes the script on a Turso error.

This script does not run itself against the database — it must be invoked
explicitly with --execute after review.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "forex_bot.db"
STATIC_EVENTS_PATH = PROJECT_ROOT / "config" / "static_events.yaml"

# Two rows for the same (title, country) within this window are treated as
# duplicates of one event, not two distinct occurrences.
_DUP_WINDOW = timedelta(days=2)


def ensure_source_column(conn: sqlite3.Connection) -> None:
    """Add the `source` column to events if this DB predates it.

    Guarded by a PRAGMA table_info check so re-running is a no-op — mirrors
    the app's own migration helper in forex_bot.data.database.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
    if "source" in columns:
        return
    conn.execute("ALTER TABLE events ADD COLUMN source TEXT NOT NULL DEFAULT 'ff'")
    conn.commit()
    logger.info("Added events.source column (default 'ff')")


def load_static_index() -> dict[tuple[str, str], set[datetime]]:
    """Parse config/static_events.yaml into {(title, country): {dates}}.

    Used to (a) know which (title, country) pairs are static events at all,
    and (b) know which exact dates the static calendar currently claims for
    them, so surviving rows can be tagged with the correct source.
    """
    index: dict[tuple[str, str], set[datetime]] = defaultdict(set)
    if not STATIC_EVENTS_PATH.exists():
        logger.warning(f"{STATIC_EVENTS_PATH} not found — no static events to index")
        return index

    with open(STATIC_EVENTS_PATH) as f:
        data = yaml.safe_load(f) or {}

    for entry in data.get("static_events", []):
        title = entry.get("title", "")
        country = entry.get("country", "")
        for date_str in entry.get("dates", []):
            try:
                index[(title, country)].add(datetime.fromisoformat(date_str))
            except ValueError:
                logger.warning(f"Skipping unparseable static event date: {date_str}")
    return index


def fetch_all_events(conn: sqlite3.Connection) -> list[tuple[int, str, str, datetime]]:
    """Return (id, title, country, scheduled_at) for every event row."""
    rows = conn.execute("SELECT id, title, country, scheduled_at FROM events").fetchall()
    return [
        (row_id, title, country, datetime.fromisoformat(scheduled_at))
        for row_id, title, country, scheduled_at in rows
    ]


def find_duplicate_groups(
    events: list[tuple[int, str, str, datetime]],
) -> list[list[tuple[int, str, str, datetime]]]:
    """Cluster events by (title, country), then by proximity in time.

    Within a (title, country) bucket, sort by scheduled_at and start a new
    cluster whenever the gap to the previous row exceeds _DUP_WINDOW. Only
    clusters with more than one row are duplicate groups.
    """
    by_key: dict[tuple[str, str], list[tuple[int, str, str, datetime]]] = defaultdict(list)
    for ev in events:
        by_key[(ev[1], ev[2])].append(ev)

    groups: list[list[tuple[int, str, str, datetime]]] = []
    for bucket in by_key.values():
        bucket.sort(key=lambda ev: ev[3])
        cluster: list[tuple[int, str, str, datetime]] = []
        for ev in bucket:
            if cluster and (ev[3] - cluster[-1][3]) > _DUP_WINDOW:
                if len(cluster) > 1:
                    groups.append(cluster)
                cluster = []
            cluster.append(ev)
        if len(cluster) > 1:
            groups.append(cluster)
    return groups


def decide_keeps(
    groups: list[list[tuple[int, str, str, datetime]]],
) -> dict[int, int]:
    """Map deleted id -> surviving id for every duplicate group.

    Keep rule: highest id (most recently created) wins.
    """
    remap: dict[int, int] = {}
    for group in groups:
        keeper = max(group, key=lambda ev: ev[0])
        title, country = keeper[1], keeper[2]
        print(f"Duplicate group: {title!r} ({country})")
        for ev in sorted(group, key=lambda e: e[0]):
            tag = "KEEP" if ev[0] == keeper[0] else "DELETE"
            print(f"  [{tag}] id={ev[0]} scheduled_at={ev[3]}")
            if ev[0] != keeper[0]:
                remap[ev[0]] = keeper[0]
    return remap


def compute_sources(
    events: list[tuple[int, str, str, datetime]],
    deleted_ids: set[int],
    static_index: dict[tuple[str, str], set[datetime]],
) -> dict[int, str]:
    """Compute the correct `source` for every surviving row.

    Rows whose (title, country) is a static event get 'static' if their
    scheduled_at exactly matches a date still in static_events.yaml,
    otherwise 'ff' (this is how the FF-owned BOJ 03:19 row and the FF-owned
    Monetary Policy Statement row are distinguished from statically-sourced
    survivors). Rows for titles that aren't static events at all default to
    'ff'.
    """
    sources: dict[int, str] = {}
    for row_id, title, country, scheduled_at in events:
        if row_id in deleted_ids:
            continue
        dates = static_index.get((title, country))
        if dates and scheduled_at in dates:
            sources[row_id] = "static"
        else:
            sources[row_id] = "ff"
    return sources


def apply_changes(
    conn: sqlite3.Connection,
    remap: dict[int, int],
    sources: dict[int, str],
) -> None:
    """Remap references, delete losing rows, and set source on survivors."""
    for deleted_id, keeper_id in remap.items():
        conn.execute(
            "UPDATE orders SET event_id = ? WHERE event_id = ?", (keeper_id, deleted_id)
        )
        conn.execute(
            "UPDATE trades SET event_id = ? WHERE event_id = ?", (keeper_id, deleted_id)
        )
    if remap:
        placeholders = ",".join("?" for _ in remap)
        conn.execute(
            f"DELETE FROM events WHERE id IN ({placeholders})", list(remap.keys())
        )
    for row_id, source in sources.items():
        conn.execute("UPDATE events SET source = ? WHERE id = ?", (source, row_id))
    conn.commit()


def mirror_to_turso(remap: dict[int, int]) -> None:
    """Mirror the same event_id remap + deletions to Turso.

    Skips silently (with a log line) if Turso credentials are not
    configured — this cleanup must never require Turso to run. Never
    raises: a Turso outage or schema mismatch must not fail the local
    cleanup, which has already committed by the time this runs.
    """
    database_url = os.environ.get("TURSO_DATABASE_URL", "")
    auth_token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if not database_url or not auth_token:
        logger.info("Turso credentials not set — skipping Turso mirror")
        return
    if not remap:
        return

    try:
        import libsql_experimental as libsql

        conn: Any = libsql.connect(database=database_url, auth_token=auth_token)
        for deleted_id, keeper_id in remap.items():
            conn.execute(
                "UPDATE orders SET event_id = ? WHERE event_id = ?",
                (keeper_id, deleted_id),
            )
            conn.execute(
                "UPDATE trades SET event_id = ? WHERE event_id = ?",
                (keeper_id, deleted_id),
            )
        for deleted_id in remap:
            conn.execute("DELETE FROM events WHERE id = ?", (deleted_id,))
        conn.commit()
        logger.info(f"Turso: mirrored dedup for {len(remap)} deleted event(s)")
    except Exception as e:
        logger.error(f"Turso mirror failed (local changes already committed): {e}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove stale duplicate event rows left by the pre-fix FF/static ping-pong bug"
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

    static_index = load_static_index()

    conn = sqlite3.connect(DB_PATH)
    try:
        ensure_source_column(conn)
        events = fetch_all_events(conn)
        groups = find_duplicate_groups(events)

        if not groups:
            print("No duplicate event groups found.")
            return

        remap = decide_keeps(groups)
        sources = compute_sources(events, set(remap.keys()), static_index)

        print(f"\n{len(remap)} row(s) to delete across {len(groups)} duplicate group(s).")
        print(f"{len(sources)} surviving row(s) will have source recomputed.")

        if dry_run:
            print("\nDry run — no changes written. Re-run with --execute to apply.")
            return

        apply_changes(conn, remap, sources)
        print(f"\nDeleted {len(remap)} row(s), recomputed source for {len(sources)} row(s).")
    finally:
        conn.close()

    if not dry_run:
        mirror_to_turso(remap)


if __name__ == "__main__":
    main()
