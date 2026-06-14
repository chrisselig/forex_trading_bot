from __future__ import annotations

from loguru import logger
from sqlalchemy import select

from forex_bot.data.database import get_session
from forex_bot.data.schemas import OrderRecord, TradeRecord
from forex_bot.models.orders import Trade


class AnomalyDetector:
    """Detect anomalies in trade execution and alert via Telegram.

    Checks after every trade close:
    - Slippage exceeds 2x the historical average
    - 3+ consecutive losing trades (losing streak)
    """

    def __init__(self, notifier):
        self._notifier = notifier

    async def check_trade(self, trade: Trade) -> None:
        """Run all anomaly checks for a closed trade."""
        if trade.is_open or trade.pnl is None:
            return

        await self._check_slippage(trade)
        await self._check_losing_streak()

    async def _check_slippage(self, trade: Trade) -> None:
        """Alert if this trade's slippage exceeds 2x the historical average."""
        if trade.slippage_pips is None:
            return

        async with get_session() as session:
            result = await session.execute(
                select(OrderRecord.slippage_pips).where(
                    OrderRecord.status == "FILLED",
                    OrderRecord.slippage_pips.isnot(None),
                )
            )
            all_slippages = [r[0] for r in result.all()]

        if len(all_slippages) < 5:
            return  # Not enough data to establish baseline

        avg_slippage = sum(abs(s) for s in all_slippages) / len(all_slippages)
        if avg_slippage == 0:
            return

        if abs(trade.slippage_pips) > avg_slippage * 2:
            await self._notifier.send_raw(
                f"*ANOMALY — HIGH SLIPPAGE*\n\n"
                f"*{trade.instrument}* {trade.side}\n"
                f"Slippage: `{trade.slippage_pips:+.1f}` pips\n"
                f"Average: `{avg_slippage:.1f}` pips\n"
                f"Ratio: `{abs(trade.slippage_pips) / avg_slippage:.1f}x` average\n\n"
                f"_Check spread conditions and liquidity._"
            )
            logger.warning(
                f"Anomaly: {trade.instrument} slippage {trade.slippage_pips:+.1f} pips "
                f"({abs(trade.slippage_pips) / avg_slippage:.1f}x avg)"
            )

    async def _check_losing_streak(self) -> None:
        """Alert if the last 3+ closed trades are all losses."""
        async with get_session() as session:
            result = await session.execute(
                select(TradeRecord)
                .where(
                    TradeRecord.closed_at.isnot(None),
                    TradeRecord.pnl.isnot(None),
                )
                .order_by(TradeRecord.closed_at.desc())
                .limit(3)
            )
            recent = result.scalars().all()

        if len(recent) < 3:
            return

        if all(r.pnl <= 0 for r in recent):
            total_loss = sum(r.pnl for r in recent)
            total_pips = sum(r.pnl_pips for r in recent if r.pnl_pips is not None)
            instruments = ", ".join(r.instrument for r in recent)
            await self._notifier.send_raw(
                f"*ANOMALY — LOSING STREAK*\n\n"
                f"Last 3 trades are all losses.\n"
                f"Pairs: `{instruments}`\n"
                f"Combined P&L: `${total_loss:,.2f}` ({total_pips:+.1f} pips)\n\n"
                f"_Review whether market conditions have changed._"
            )
            logger.warning(f"Anomaly: 3 consecutive losses ({total_loss:,.2f})")
