from __future__ import annotations

from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import select

from forex_bot.data.database import get_session
from forex_bot.data.schemas import TradeRecord, OrderRecord


class WeeklyReporter:
    """Generate and send a weekly performance summary via Telegram.

    Scheduled for Sunday 3 PM MT (21:00 UTC) — after AU Sunday session
    but before quiet hours.
    """

    def __init__(self, notifier):
        self._notifier = notifier

    async def send_report(self) -> None:
        """Build and send the weekly performance report."""
        try:
            now = datetime.now(UTC)
            week_start = now - timedelta(days=7)
            trades = await self._get_closed_trades(since=week_start)
            orders = await self._get_filled_orders(since=week_start)

            lines = ["*WEEKLY PERFORMANCE REPORT*", ""]

            if not trades:
                lines.append("_No trades closed this week._")
                lines.append("")
                lines.append(f"_{now.strftime('%b %d, %Y')}_")
                await self._notifier.send_raw("\n".join(lines))
                return

            # Summary stats
            wins = [t for t in trades if t.pnl > 0]
            losses = [t for t in trades if t.pnl <= 0]
            total_pnl = sum(t.pnl for t in trades)
            total_pips = sum(t.pnl_pips for t in trades if t.pnl_pips is not None)
            win_rate = len(wins) / len(trades) * 100

            total_commission = sum(
                t.commission for t in trades if t.commission is not None
            )
            net_pnl = total_pnl - total_commission
            pnl_sign = "+" if total_pnl >= 0 else ""
            net_sign = "+" if net_pnl >= 0 else ""
            pips_sign = "+" if total_pips >= 0 else ""

            lines.extend([
                f"Trades: `{len(trades)}`  Won: `{len(wins)}`  Lost: `{len(losses)}`",
                f"Win rate: `{win_rate:.0f}%`",
                "",
                f"*Gross P&L: `{pnl_sign}${total_pnl:,.2f}` ({pips_sign}{total_pips:.1f} pips)*",
            ])
            if total_commission > 0:
                lines.append(f"Commissions: `${total_commission:,.2f}`")
                lines.append(f"*Net P&L: `{net_sign}${net_pnl:,.2f}`*")

            # Avg win / avg loss
            if wins:
                avg_win = sum(t.pnl for t in wins) / len(wins)
                lines.append(f"Avg win: `+${avg_win:,.2f}`")
            if losses:
                avg_loss = sum(t.pnl for t in losses) / len(losses)
                lines.append(f"Avg loss: `${avg_loss:,.2f}`")

            # Profit factor
            gross_wins = sum(t.pnl for t in wins) if wins else 0
            gross_losses = abs(sum(t.pnl for t in losses)) if losses else 0
            pf = gross_wins / gross_losses if gross_losses > 0 else float("inf")
            if pf != float("inf"):
                lines.append(f"Profit factor: `{pf:.2f}`")

            # Breakdown by pair
            pairs: dict[str, list] = {}
            for t in trades:
                pairs.setdefault(t.instrument, []).append(t)

            if len(pairs) > 1:
                lines.extend(["", "*By pair:*"])
                for pair, pair_trades in sorted(pairs.items()):
                    pair_pnl = sum(t.pnl for t in pair_trades)
                    pair_wins = sum(1 for t in pair_trades if t.pnl > 0)
                    p_sign = "+" if pair_pnl >= 0 else ""
                    lines.append(
                        f"  {pair}: `{len(pair_trades)}` trades, "
                        f"`{pair_wins}/{len(pair_trades)}` won, "
                        f"`{p_sign}${pair_pnl:,.2f}`"
                    )

            # Breakdown by event type
            event_types = await self._get_event_breakdown(trades)
            if len(event_types) > 1:
                lines.extend(["", "*By event:*"])
                for event_name, evt_data in sorted(event_types.items()):
                    e_sign = "+" if evt_data["pnl"] >= 0 else ""
                    lines.append(
                        f"  {event_name}: `{evt_data['count']}` trades, "
                        f"`{e_sign}${evt_data['pnl']:,.2f}`"
                    )

            # Spread / slippage
            spreads = [o.entry_spread_pips for o in orders if o.entry_spread_pips is not None]
            slippages = [o.slippage_pips for o in orders if o.slippage_pips is not None]
            if spreads or slippages:
                lines.extend(["", "*Execution quality:*"])
                if spreads:
                    lines.append(f"  Avg spread: `{sum(spreads) / len(spreads):.1f}` pips")
                if slippages:
                    avg_slip = sum(abs(s) for s in slippages) / len(slippages)
                    lines.append(f"  Avg slippage: `{avg_slip:.1f}` pips")

            # MC comparison (expected ranges from analysis)
            lines.extend(["", "*vs MC expectations:*"])
            # USDZAR: E[P&L]=+17.1 pips/trade, CI=[+12.0, +22.8]
            # USDTRY: E[P&L]=+13.6 pips/trade, CI=[+9.5, +17.8]
            for pair, mc in [("USDZAR", (12.0, 22.8)), ("USDTRY", (9.5, 17.8))]:
                pair_trades = pairs.get(pair, [])
                if not pair_trades:
                    continue
                pair_pips = [t.pnl_pips for t in pair_trades if t.pnl_pips is not None]
                if not pair_pips:
                    continue
                avg_pips = sum(pair_pips) / len(pair_pips)
                in_range = mc[0] <= avg_pips <= mc[1]
                status = "IN RANGE" if in_range else "OUTSIDE CI"
                if avg_pips < mc[0]:
                    status = "BELOW CI"
                elif avg_pips > mc[1]:
                    status = "ABOVE CI"
                lines.append(
                    f"  {pair}: `{avg_pips:+.1f}` pips/trade "
                    f"(MC CI: [{mc[0]:+.1f}, {mc[1]:+.1f}]) — _{status}_"
                )

            lines.extend(["", f"_{now.strftime('%b %d, %Y')}_"])

            await self._notifier.send_raw("\n".join(lines))
            logger.info(f"Weekly report sent: {len(trades)} trades, P&L=${total_pnl:,.2f}")

        except Exception as e:
            logger.error(f"Weekly report failed: {e}")

    async def _get_closed_trades(self, since: datetime) -> list:
        """Get all trades closed since the given datetime."""
        async with get_session() as session:
            result = await session.execute(
                select(TradeRecord)
                .where(
                    TradeRecord.closed_at.isnot(None),
                    TradeRecord.pnl.isnot(None),
                    TradeRecord.closed_at >= since,
                )
                .order_by(TradeRecord.closed_at.asc())
            )
            return result.scalars().all()

    async def _get_filled_orders(self, since: datetime) -> list:
        """Get all filled orders since the given datetime."""
        async with get_session() as session:
            result = await session.execute(
                select(OrderRecord)
                .where(
                    OrderRecord.status == "FILLED",
                    OrderRecord.filled_at.isnot(None),
                    OrderRecord.filled_at >= since,
                )
            )
            return result.scalars().all()

    async def _get_event_breakdown(self, trades: list) -> dict[str, dict]:
        """Group trades by their event title."""
        from forex_bot.data.schemas import EventRecord

        event_ids = [t.event_id for t in trades if t.event_id is not None]
        if not event_ids:
            return {}

        async with get_session() as session:
            result = await session.execute(
                select(EventRecord).where(EventRecord.id.in_(event_ids))
            )
            events = {e.id: e.title for e in result.scalars().all()}

        breakdown: dict[str, dict] = {}
        for t in trades:
            name = events.get(t.event_id, "Unknown") if t.event_id else "Unknown"
            if name not in breakdown:
                breakdown[name] = {"count": 0, "pnl": 0.0}
            breakdown[name]["count"] += 1
            breakdown[name]["pnl"] += t.pnl

        return breakdown
