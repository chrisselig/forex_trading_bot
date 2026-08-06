from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy import func, select

from forex_bot.data.database import get_session
from forex_bot.data.schemas import InterestAccrualRecord
from forex_bot.models.interest import InterestAccrualRow


class InterestJournal:
    """Persists real, IB-computed interest accrual rows and aggregates them
    per currency over common reporting periods.

    Upserts are keyed on (currency, from_date, to_date) — the same daily
    fetch is used for both the ongoing daily job and one-off historical
    backfills, so re-fetching an already-seen day is a no-op and any gap
    (e.g. bot downtime) self-heals on the next fetch.
    """

    async def upsert_rows(self, rows: list[InterestAccrualRow]) -> int:
        """Insert new rows / update existing ones. Returns the number written."""
        written = 0
        async with get_session() as session:
            for row in rows:
                existing = (
                    await session.execute(
                        select(InterestAccrualRecord).where(
                            InterestAccrualRecord.currency == row.currency,
                            InterestAccrualRecord.from_date == row.from_date,
                            InterestAccrualRecord.to_date == row.to_date,
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    existing.amount_cad = row.amount_cad
                else:
                    session.add(
                        InterestAccrualRecord(
                            currency=row.currency,
                            from_date=row.from_date,
                            to_date=row.to_date,
                            amount_cad=row.amount_cad,
                        )
                    )
                written += 1
            await session.commit()
        logger.info(f"Interest journal: upserted {written} accrual row(s)")
        return written

    async def sum_by_currency(self, since: datetime | None = None) -> dict[str, float]:
        """Sum accrued interest per currency, optionally restricted to rows
        whose from_date is on or after `since`."""
        async with get_session() as session:
            query = select(
                InterestAccrualRecord.currency,
                func.sum(InterestAccrualRecord.amount_cad),
            ).group_by(InterestAccrualRecord.currency)
            if since is not None:
                query = query.where(InterestAccrualRecord.from_date >= since)
            result = await session.execute(query)
            return {currency: total or 0.0 for currency, total in result.all()}

    async def get_period_summary(self, now: datetime | None = None) -> dict[str, dict[str, float]]:
        """Returns {"all_time": {...}, "this_year": {...}, "this_month": {...}},
        each a per-currency interest total in CAD."""
        now = now or datetime.utcnow()
        year_start = datetime(now.year, 1, 1)
        month_start = datetime(now.year, now.month, 1)
        return {
            "all_time": await self.sum_by_currency(),
            "this_year": await self.sum_by_currency(since=year_start),
            "this_month": await self.sum_by_currency(since=month_start),
        }

    async def earliest_date(self) -> datetime | None:
        """Oldest from_date on record, or None if the journal is empty."""
        async with get_session() as session:
            result = await session.execute(select(func.min(InterestAccrualRecord.from_date)))
            return result.scalar_one_or_none()
