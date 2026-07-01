from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from loguru import logger

from forex_bot.broker.contracts import get_pip_size
from forex_bot.models.account import AccountSummary
from forex_bot.models.events import EconomicEvent
from forex_bot.models.orders import Order, OrderSide, Trade
from forex_bot.reporting.performance import PerformanceStats
from forex_bot.risk.circuit_breaker import CircuitBreaker, CircuitState

ET = ZoneInfo("America/New_York")
MT = ZoneInfo("America/Edmonton")

# Quiet hours in Mountain Time — ALL alerts suppressed (no exceptions)
QUIET_START_HOUR = 20   # 8:30 PM MT
QUIET_START_MINUTE = 30
QUIET_END_HOUR = 5      # 5:00 AM MT (bot cron starts at 5 AM MT)
QUIET_END_MINUTE = 0


class TelegramNotifier:
    """Sends trade alerts and status updates via Telegram Bot API."""

    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True):
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._enabled = enabled and bool(bot_token) and bool(chat_id)
        self._base_url = f"https://api.telegram.org/bot{bot_token}"
        self._connection_lost_notified = False

        if not self._enabled:
            logger.warning("Telegram notifications disabled (missing token or chat_id)")

    def _is_quiet_hours(self) -> bool:
        """Check if we're in the overnight quiet period (all alerts suppressed).

        Uses Mountain Time (America/Edmonton) with proper DST handling.
        Quiet window: 8:30 PM MT to 5:00 AM MT.
        """
        now_mt = datetime.now(MT)
        current = now_mt.hour * 60 + now_mt.minute
        start = QUIET_START_HOUR * 60 + QUIET_START_MINUTE
        end = QUIET_END_HOUR * 60 + QUIET_END_MINUTE
        # Window wraps midnight (20:30 -> 05:00)
        return current >= start or current < end

    async def _send(self, text: str, silent: bool = False, critical: bool = False) -> None:
        """Send a message via Telegram. Silently logs errors — never crashes the bot.

        Args:
            text: Message content (Markdown).
            silent: Send without sound (disable_notification).
            critical: Unused — all alerts suppressed during quiet hours (8:30 PM - 5:00 AM MT).
        """
        if not self._enabled:
            return

        if self._is_quiet_hours():
            logger.debug(f"Telegram suppressed (quiet hours): {text[:80]}...")
            return

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self._base_url}/sendMessage",
                    json={
                        "chat_id": self._chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                        "disable_notification": silent,
                    },
                )
                if resp.status_code != 200:
                    logger.error(f"Telegram API error {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    # ------------------------------------------------------------------
    # Time formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt_et(dt: datetime | None) -> str:
        """Format a UTC datetime as Eastern Time string."""
        if dt is None:
            return "—"
        if dt.tzinfo is None:
            from datetime import timezone
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ET).strftime("%b %d %I:%M:%S %p ET")

    @staticmethod
    def _fmt_price(price: float | None, pair: str = "") -> str:
        """Format a price with appropriate decimal places."""
        if price is None:
            return "—"
        pip_size = get_pip_size(pair) if pair else 0.0001
        decimals = 2 if pip_size >= 0.01 else 5
        return f"{price:.{decimals}f}"

    @staticmethod
    def _arrow(side: OrderSide) -> str:
        return "LONG" if side == OrderSide.BUY else "SHORT"

    @staticmethod
    def _risk_reward(tp: float | None, sl: float | None, entry: float | None, side: OrderSide) -> str:
        """Calculate reward:risk ratio."""
        if not all([tp, sl, entry]):
            return "—"
        if side == OrderSide.BUY:
            reward = tp - entry
            risk = entry - sl
        else:
            reward = entry - tp
            risk = sl - entry
        if risk <= 0:
            return "—"
        return f"{reward / risk:.1f}:1"

    # ------------------------------------------------------------------
    # Trade Opened
    # ------------------------------------------------------------------

    async def notify_trade_opened(
        self,
        order: Order,
        event: EconomicEvent | None = None,
        account: AccountSummary | None = None,
        spread_pips: float | None = None,
    ) -> None:
        """Notify when a new trade is placed."""
        pair = order.instrument
        pip_size = get_pip_size(pair)
        entry = self._fmt_price(order.price, pair)
        sl = self._fmt_price(order.stop_loss, pair)
        tp = self._fmt_price(order.take_profit, pair)
        rr = self._risk_reward(order.take_profit, order.stop_loss, order.price, order.side)

        sl_pips = tp_pips = "—"
        if order.price and order.stop_loss:
            sl_pips = f"{abs(order.price - order.stop_loss) / pip_size:.1f}"
        if order.price and order.take_profit:
            tp_pips = f"{abs(order.price - order.take_profit) / pip_size:.1f}"

        lines = [
            "*NEW TRADE OPENED*",
            "",
            f"*{pair}* {self._arrow(order.side)} ({order.order_type})",
            f"Strategy: `{order.strategy}`",
            "",
            f"Entry: `{entry}`",
            f"Stop Loss: `{sl}` ({sl_pips} pips)",
            f"Take Profit: `{tp}` ({tp_pips} pips)",
            f"R:R: `{rr}`",
            f"Size: `{order.quantity:,.0f}` units",
        ]

        if spread_pips is not None:
            lines.append(f"Spread: `{spread_pips:.1f}` pips")

        if event:
            lines.append("")
            lines.append(f"*Event:* {event.title}")
            lines.append(f"Scheduled: {self._fmt_et(event.scheduled_at)}")
            if event.forecast:
                lines.append(f"Forecast: `{event.forecast}`  Prev: `{event.previous or '—'}`")

        if account:
            lines.append("")
            lines.append(f"Account NLV: `${account.net_liquidation:,.2f}`")
            if account.unrealized_pnl != 0:
                lines.append(f"Open P&L: `${account.unrealized_pnl:,.2f}`")

        lines.append("")
        lines.append(f"_{self._fmt_et(order.created_at)}_")

        await self._send("\n".join(lines), critical=True)

    # ------------------------------------------------------------------
    # Trade Filled
    # ------------------------------------------------------------------

    async def notify_order_filled(
        self,
        order_id: int,
        instrument: str,
        side: OrderSide,
        fill_price: float,
        quantity: float,
    ) -> None:
        """Notify when an order is filled by IB."""
        pair = instrument
        lines = [
            "*ORDER FILLED*",
            "",
            f"*{pair}* {self._arrow(side)}",
            f"Fill: `{self._fmt_price(fill_price, pair)}`",
            f"Size: `{quantity:,.0f}` units",
            f"IB Order: `#{order_id}`",
            "",
            f"_{self._fmt_et(datetime.utcnow())}_",
        ]

        await self._send("\n".join(lines), critical=True)

    # ------------------------------------------------------------------
    # Trade Closed
    # ------------------------------------------------------------------

    async def notify_trade_closed(
        self,
        trade: Trade,
        event: EconomicEvent | None = None,
        account: AccountSummary | None = None,
        daily_pnl: float | None = None,
    ) -> None:
        """Notify when a trade is closed with full P&L details."""
        pair = trade.instrument
        pnl = trade.pnl or 0
        pnl_pips = trade.pnl_pips or 0
        is_win = pnl > 0
        result = "WIN" if is_win else "LOSS"
        pnl_sign = "+" if pnl >= 0 else ""

        # Determine exit reason
        exit_reason = "Manual/Timeout"
        if trade.exit_price and trade.take_profit:
            pip_size = get_pip_size(pair)
            if abs(trade.exit_price - trade.take_profit) < pip_size * 2:
                exit_reason = "Take Profit"
        if trade.exit_price and trade.stop_loss:
            pip_size = get_pip_size(pair)
            if abs(trade.exit_price - trade.stop_loss) < pip_size * 2:
                exit_reason = "Stop Loss"

        # Duration
        duration = "—"
        if trade.opened_at and trade.closed_at:
            delta = trade.closed_at - trade.opened_at
            mins = int(delta.total_seconds() / 60)
            if mins < 60:
                duration = f"{mins}m"
            else:
                duration = f"{mins // 60}h {mins % 60}m"

        lines = [
            f"*TRADE CLOSED — {result}*",
            "",
            f"*{pair}* {self._arrow(trade.side)}",
            f"Strategy: `{trade.strategy}`",
            "",
            f"Entry: `{self._fmt_price(trade.entry_price, pair)}`",
            f"Exit: `{self._fmt_price(trade.exit_price, pair)}`",
            f"Closed by: _{exit_reason}_",
            f"Duration: `{duration}`",
            "",
            f"*P&L: `{pnl_sign}${pnl:,.2f}` ({pnl_sign}{pnl_pips:.1f} pips)*",
        ]

        if event and event.has_actual:
            surprise = event.surprise_pct
            lines.append("")
            lines.append(f"*Event:* {event.title}")
            lines.append(f"Actual: `{event.actual}`  Forecast: `{event.forecast}`  Prev: `{event.previous or '—'}`")
            if surprise is not None:
                lines.append(f"Surprise: `{surprise:+.1f}%`")

        if account or daily_pnl is not None:
            lines.append("")
            if account:
                lines.append(f"Account NLV: `${account.net_liquidation:,.2f}`")
            if daily_pnl is not None:
                dpnl_sign = "+" if daily_pnl >= 0 else ""
                lines.append(f"Daily P&L: `{dpnl_sign}${daily_pnl:,.2f}`")

        lines.append("")
        lines.append(f"_{self._fmt_et(trade.closed_at)}_")

        await self._send("\n".join(lines), critical=True)

    # ------------------------------------------------------------------
    # Risk Alerts
    # ------------------------------------------------------------------

    async def notify_signal_rejected(
        self,
        instrument: str,
        strategy: str,
        violations: list[str],
        event: EconomicEvent | None = None,
    ) -> None:
        """Notify when a signal is rejected by the risk manager."""
        lines = [
            "*SIGNAL REJECTED*",
            "",
            f"*{instrument}* — `{strategy}`",
            "",
            "Violations:",
        ]
        for v in violations:
            lines.append(f"  - {v}")

        if event:
            lines.append("")
            lines.append(f"Event: {event.title} ({self._fmt_et(event.scheduled_at)})")

        lines.append("")
        lines.append(f"_{self._fmt_et(datetime.utcnow())}_")

        await self._send("\n".join(lines), critical=True)

    async def notify_circuit_breaker(self, circuit_breaker: CircuitBreaker) -> None:
        """Notify on circuit breaker state change (COOLDOWN or HALTED)."""
        state = circuit_breaker.state
        if state == CircuitState.ACTIVE:
            return

        if state == CircuitState.HALTED:
            lines = [
                "*CIRCUIT BREAKER — HALTED*",
                "",
                f"Reason: {circuit_breaker.halt_reason}",
                "",
                "*All trading is STOPPED.*",
                "Manual reset required via `forex-bot reset-circuit`.",
                "",
                f"_{self._fmt_et(datetime.utcnow())}_",
            ]
        else:
            lines = [
                "*CIRCUIT BREAKER — COOLDOWN*",
                "",
                "Trading paused for 30 minutes.",
                "",
                f"_{self._fmt_et(datetime.utcnow())}_",
            ]

        await self._send("\n".join(lines), critical=True)

    # ------------------------------------------------------------------
    # Connection Alerts
    # ------------------------------------------------------------------

    async def notify_connection_lost(self) -> None:
        """Log when IB connection is lost. No Telegram alert (too noisy from daily TWS restart)."""
        if self._connection_lost_notified:
            return
        self._connection_lost_notified = True
        logger.warning("IB connection lost — attempting reconnection")

    async def notify_connection_restored(self) -> None:
        """Log when IB connection is restored. No Telegram alert."""
        self._connection_lost_notified = False
        logger.info("IB connection restored")

    async def notify_straddle_missed(self, event: EconomicEvent, seconds_to_event: float) -> None:
        """Notify when a pre-event straddle was skipped because it was too late to place.

        Fires on a late start (bot restarted inside the pre-event window) when
        the remaining lead time is below the safe minimum.
        """
        if seconds_to_event < 0:
            timing = f"event was {abs(seconds_to_event) / 60:.0f} min ago"
        else:
            timing = f"only {seconds_to_event:.0f}s of lead remained"
        await self._send(
            f"*STRADDLE MISSED*\n\n"
            f"No pre-event straddle placed for *{event.title}*\n"
            f"Scheduled: {self._fmt_et(event.scheduled_at)}\n"
            f"Reason: {timing} (late start)\n\n"
            f"_{self._fmt_et(datetime.utcnow())}_",
            critical=True,
        )

    async def notify_preflight_failed(self, event: EconomicEvent) -> None:
        """Notify when pre-flight connection check fails before an event."""
        await self._send(
            f"*PRE-FLIGHT FAILED*\n\n"
            f"Could not connect to IB before *{event.title}*\n"
            f"Scheduled: {self._fmt_et(event.scheduled_at)}\n\n"
            f"*Trades may not execute!*\n\n"
            f"_{self._fmt_et(datetime.utcnow())}_",
            critical=True,
        )

    # ------------------------------------------------------------------
    # Daily Summary
    # ------------------------------------------------------------------

    async def notify_daily_summary(
        self,
        stats: PerformanceStats,
        daily_pnl: float,
        account: AccountSummary | None = None,
        circuit_state: CircuitState = CircuitState.ACTIVE,
    ) -> None:
        """End-of-day performance summary."""
        dpnl_sign = "+" if daily_pnl >= 0 else ""

        lines = [
            "*DAILY SUMMARY*",
            "",
            f"Trades today: `{stats.total_trades}`",
            f"Won: `{stats.winning_trades}`  Lost: `{stats.losing_trades}`",
        ]

        if stats.total_trades > 0:
            lines.extend([
                f"Win rate: `{stats.win_rate:.0f}%`",
                f"Avg win: `${stats.avg_win:,.2f}`  Avg loss: `${stats.avg_loss:,.2f}`",
                f"Profit factor: `{stats.profit_factor:.2f}`",
                "",
                f"*Daily P&L: `{dpnl_sign}${daily_pnl:,.2f}`*",
                f"Avg pips: `{stats.avg_pnl_pips:+.1f}`",
            ])
        else:
            lines.extend([
                "",
                "_No trades executed today._",
            ])

        if account:
            lines.extend([
                "",
                f"Account NLV: `${account.net_liquidation:,.2f}`",
                f"Open P&L: `${account.unrealized_pnl:,.2f}`",
            ])

        if circuit_state != CircuitState.ACTIVE:
            lines.extend([
                "",
                f"Circuit Breaker: *{circuit_state}*",
            ])

        lines.append("")
        lines.append(f"_{self._fmt_et(datetime.utcnow())}_")

        await self._send("\n".join(lines))

    # ------------------------------------------------------------------
    # Event Alerts
    # ------------------------------------------------------------------

    async def notify_event_upcoming(self, event: EconomicEvent, minutes: int) -> None:
        """Notify that a high-impact event is approaching."""
        lines = [
            f"*EVENT IN {minutes} MIN*",
            "",
            f"*{event.title}* ({event.country})",
            f"Scheduled: {self._fmt_et(event.scheduled_at)}",
        ]

        if event.forecast:
            lines.append(f"Forecast: `{event.forecast}`  Prev: `{event.previous or '—'}`")

        lines.append("")
        lines.append(f"_{self._fmt_et(datetime.utcnow())}_")

        await self._send("\n".join(lines), silent=True)

    # ------------------------------------------------------------------
    # Bot Lifecycle
    # ------------------------------------------------------------------

    async def notify_bot_started(self, account: AccountSummary | None = None) -> None:
        """Notify that the trading bot has started."""
        lines = [
            "*BOT STARTED*",
            "",
        ]

        if account:
            lines.extend([
                f"Account: `{account.account_id}`",
                f"NLV: `${account.net_liquidation:,.2f}`",
                f"Buying power: `${account.buying_power:,.2f}`",
                "",
            ])

        lines.append(f"_{self._fmt_et(datetime.utcnow())}_")

        await self._send("\n".join(lines))

    async def send_raw(self, text: str) -> None:
        """Send an arbitrary message. Used for one-off warnings like calendar validation."""
        await self._send(text)

    async def notify_bot_stopped(self, reason: str = "normal shutdown") -> None:
        """Notify that the trading bot has stopped."""
        await self._send(
            f"*BOT STOPPED*\n\n"
            f"Reason: {reason}\n\n"
            f"_{self._fmt_et(datetime.utcnow())}_"
        )
