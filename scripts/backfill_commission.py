"""Backfill commission onto trade rows that missed it.

Fixes trades whose commission report arrived BEFORE the trade row was created
(the commission landed on the order, not the trade). Copies the order's
commission onto the trade in SQLite and re-pushes it to Turso so the dashboard
shows it. Idempotent — only touches trades with a NULL commission whose order
has one.

Usage:
    python scripts/backfill_commission.py
"""

from __future__ import annotations

import asyncio

from loguru import logger
from sqlalchemy import select

from forex_bot.config import get_settings
from forex_bot.data.database import get_session, init_db
from forex_bot.data.schemas import OrderRecord, TradeRecord
from forex_bot.data.turso_sync import TursoSyncer


async def main() -> None:
    await init_db()

    fixed: list[tuple[int, int, float]] = []  # (trade_id, order_id, commission)
    async with get_session() as session:
        rows = (
            await session.execute(
                select(TradeRecord, OrderRecord)
                .join(OrderRecord, TradeRecord.order_id == OrderRecord.id)
                .where(TradeRecord.commission.is_(None), OrderRecord.commission.isnot(None))
            )
        ).all()
        for trade_rec, order_rec in rows:
            trade_rec.commission = order_rec.commission
            fixed.append((trade_rec.id, trade_rec.order_id, order_rec.commission))
        await session.commit()

    logger.info(f"SQLite: backfilled commission on {len(fixed)} trade(s): {fixed}")

    if not fixed:
        return

    settings = get_settings()
    turso = TursoSyncer(
        database_url=settings.turso.database_url,
        auth_token=settings.turso.auth_token,
        account_type=settings.broker.account_type,
        enabled=settings.turso.enabled,
    )
    for _trade_id, order_id, commission in fixed:
        await turso.push_commission(order_id=order_id, commission=commission)
    logger.info(f"Turso: re-pushed commission for {len(fixed)} order(s)")


if __name__ == "__main__":
    asyncio.run(main())
