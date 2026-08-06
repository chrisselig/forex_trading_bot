"""One-off backfill of real, IB-computed interest accrual history.

Runs the exact same fetch+upsert operation as the daily scheduled job
(Orchestrator._fetch_interest_accruals) immediately instead of waiting for
the next scheduled run. Safe to re-run any time — upserts are keyed on
(currency, from_date, to_date), so already-seen days are a no-op.

The Flex Query itself is configured in IBKR Account Management with
Period="Last 365 Calendar Days" and Breakout by Day=Yes, so a single run
covers the full trailing year regardless of when it's run.

Usage:
    python scripts/backfill_flex_interest.py
"""

from __future__ import annotations

import asyncio

from loguru import logger

from forex_bot.broker.flex_query import FlexQueryClient
from forex_bot.config import get_settings
from forex_bot.data.database import init_db
from forex_bot.data.interest_journal import InterestJournal


async def main() -> None:
    await init_db()

    settings = get_settings()
    flex_cfg = settings.flex_query
    if not flex_cfg.enabled or not flex_cfg.token or not flex_cfg.query_id:
        logger.error("Flex Query is not configured (check IB_FLEX_TOKEN / IB_FLEX_QUERY_ID in .env)")
        return

    client = FlexQueryClient(token=flex_cfg.token, query_id=flex_cfg.query_id)
    logger.info("Requesting Flex statement (this can take a minute or more while IB generates it)...")
    rows = await client.fetch_interest_accruals(
        max_attempts=flex_cfg.poll_max_attempts,
        retry_interval_s=flex_cfg.poll_retry_interval_seconds,
    )
    logger.info(f"Fetched {len(rows)} interest accrual row(s)")

    journal = InterestJournal()
    written = await journal.upsert_rows(rows)
    logger.info(f"Backfill complete: upserted {written} row(s)")

    summary = await journal.get_period_summary()
    for period, totals in summary.items():
        logger.info(f"{period}: {totals}")


if __name__ == "__main__":
    asyncio.run(main())
