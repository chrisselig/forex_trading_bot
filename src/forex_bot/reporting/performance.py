from __future__ import annotations

import math
from dataclasses import dataclass

from forex_bot.data.database import get_session
from forex_bot.data.schemas import OrderRecord
from forex_bot.data.trade_journal import TradeJournal


@dataclass
class PerformanceStats:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    avg_pnl_pips: float = 0.0
    avg_spread_pips: float = 0.0
    avg_slippage_pips: float = 0.0
    total_slippage_pips: float = 0.0


class PerformanceTracker:
    """Calculates trading performance metrics."""

    def __init__(self, journal: TradeJournal):
        self._journal = journal

    async def get_stats(self, strategy: str | None = None) -> PerformanceStats:
        """Calculate performance statistics from trade history."""
        trades = await self._journal.get_trades(strategy=strategy, limit=1000)
        closed = [t for t in trades if not t.is_open and t.pnl is not None]

        if not closed:
            return PerformanceStats()

        wins = [t for t in closed if t.pnl > 0]
        losses = [t for t in closed if t.pnl <= 0]

        total_wins = sum(t.pnl for t in wins) if wins else 0
        total_losses = abs(sum(t.pnl for t in losses)) if losses else 0

        # Calculate max drawdown
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in sorted(closed, key=lambda x: x.closed_at or x.opened_at):
            cumulative += t.pnl
            peak = max(peak, cumulative)
            dd = peak - cumulative
            max_dd = max(max_dd, dd)

        # Calculate Sharpe ratio (simplified, annualized)
        pnls = [t.pnl for t in closed]
        avg_pnl = sum(pnls) / len(pnls)
        if len(pnls) > 1:
            std_pnl = math.sqrt(sum((p - avg_pnl) ** 2 for p in pnls) / (len(pnls) - 1))
            sharpe = (avg_pnl / std_pnl) * math.sqrt(252) if std_pnl > 0 else 0.0
        else:
            sharpe = 0.0

        pips = [t.pnl_pips for t in closed if t.pnl_pips is not None]

        # Spread/slippage stats from order records (active data flow)
        spread_stats = await self._get_spread_slippage_stats()

        return PerformanceStats(
            total_trades=len(closed),
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate=len(wins) / len(closed) * 100 if closed else 0,
            total_pnl=sum(t.pnl for t in closed),
            avg_win=total_wins / len(wins) if wins else 0,
            avg_loss=total_losses / len(losses) if losses else 0,
            max_drawdown=max_dd,
            profit_factor=total_wins / total_losses if total_losses > 0 else float("inf"),
            sharpe_ratio=sharpe,
            avg_pnl_pips=sum(pips) / len(pips) if pips else 0,
            avg_spread_pips=spread_stats["avg_spread"],
            avg_slippage_pips=spread_stats["avg_slippage"],
            total_slippage_pips=spread_stats["total_slippage"],
        )

    async def _get_spread_slippage_stats(self) -> dict[str, float]:
        """Get spread and slippage averages from filled orders."""
        from sqlalchemy import select

        async with get_session() as session:
            result = await session.execute(
                select(OrderRecord).where(OrderRecord.status == "FILLED")
            )
            records = result.scalars().all()

        spreads = [r.entry_spread_pips for r in records if r.entry_spread_pips is not None]
        slippages = [r.slippage_pips for r in records if r.slippage_pips is not None]

        return {
            "avg_spread": sum(spreads) / len(spreads) if spreads else 0.0,
            "avg_slippage": sum(slippages) / len(slippages) if slippages else 0.0,
            "total_slippage": sum(slippages) if slippages else 0.0,
        }

    async def get_stats_by_strategy(self) -> dict[str, PerformanceStats]:
        """Get performance stats broken down by strategy."""
        all_trades = await self._journal.get_trades(limit=1000)
        strategies = set(t.strategy for t in all_trades if t.strategy)
        result = {}
        for strat in strategies:
            result[strat] = await self.get_stats(strategy=strat)
        return result
