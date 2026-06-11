from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text

from forex_bot.data.trade_journal import TradeJournal
from forex_bot.models.account import AccountSummary
from forex_bot.models.events import EconomicEvent
from forex_bot.reporting.performance import PerformanceStats
from forex_bot.risk.circuit_breaker import CircuitBreaker, CircuitState

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


class Dashboard:
    """Rich terminal output for trading bot status."""

    def __init__(self):
        self.console = Console()

    def show_account(self, summary: AccountSummary) -> None:
        """Display account summary."""
        table = Table(title="Account Summary", show_header=False)
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Account", summary.account_id)
        table.add_row("Net Liquidation", f"${summary.net_liquidation:,.2f}")
        table.add_row("Cash", f"${summary.total_cash:,.2f}")
        table.add_row("Buying Power", f"${summary.buying_power:,.2f}")
        table.add_row("Unrealized P&L", f"${summary.unrealized_pnl:,.2f}")
        table.add_row("Realized P&L", f"${summary.realized_pnl:,.2f}")
        self.console.print(table)

    def show_events(self, events: list[EconomicEvent]) -> None:
        """Display upcoming events."""
        table = Table(title="Upcoming Events")
        table.add_column("Time (ET)", style="cyan")
        table.add_column("Event", style="white")
        table.add_column("Impact", style="red")
        table.add_column("Forecast", style="yellow")
        table.add_column("Previous", style="dim")
        table.add_column("Actual", style="green")

        for event in events:
            et_time = event.scheduled_at.replace(tzinfo=UTC).astimezone(ET)
            time_str = et_time.strftime("%a %b %d %I:%M %p ET")
            table.add_row(
                time_str,
                event.title,
                event.impact.value.upper(),
                event.forecast or "-",
                event.previous or "-",
                event.actual or "-",
            )

        self.console.print(table)

    def show_performance(self, stats: PerformanceStats, title: str = "Performance") -> None:
        """Display performance statistics."""
        table = Table(title=title, show_header=False)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Total Trades", str(stats.total_trades))
        table.add_row("Win Rate", f"{stats.win_rate:.1f}%")
        table.add_row("Total P&L", f"${stats.total_pnl:,.2f}")
        table.add_row("Avg Win", f"${stats.avg_win:,.2f}")
        table.add_row("Avg Loss", f"${stats.avg_loss:,.2f}")
        table.add_row("Profit Factor", f"{stats.profit_factor:.2f}")
        table.add_row("Max Drawdown", f"${stats.max_drawdown:,.2f}")
        table.add_row("Sharpe Ratio", f"{stats.sharpe_ratio:.2f}")
        table.add_row("Avg P&L (pips)", f"{stats.avg_pnl_pips:.1f}")
        table.add_row("Avg Spread (pips)", f"{stats.avg_spread_pips:.1f}")
        table.add_row("Avg Slippage (pips)", f"{stats.avg_slippage_pips:+.1f}")
        table.add_row("Total Slippage (pips)", f"{stats.total_slippage_pips:+.1f}")
        self.console.print(table)

    def show_circuit_breaker(self, cb: CircuitBreaker) -> None:
        """Display circuit breaker status."""
        state = cb.state
        if state == CircuitState.ACTIVE:
            style = "green"
        elif state == CircuitState.COOLDOWN:
            style = "yellow"
        else:
            style = "red"

        text = Text(f"Circuit Breaker: {state.value}", style=style)
        if cb.halt_reason:
            text.append(f"\nReason: {cb.halt_reason}", style="red")
        self.console.print(Panel(text, title="Safety Status"))

    def show_trades(self, trades: list) -> None:
        """Display recent trades."""
        table = Table(title="Recent Trades")
        table.add_column("ID", style="dim")
        table.add_column("Pair", style="cyan")
        table.add_column("Side")
        table.add_column("Qty", justify="right")
        table.add_column("Entry", justify="right")
        table.add_column("Exit", justify="right")
        table.add_column("P&L", justify="right")
        table.add_column("Strategy", style="dim")

        for trade in trades:
            pnl_style = "green" if trade.pnl and trade.pnl > 0 else "red"
            side_style = "green" if trade.side.value == "BUY" else "red"
            table.add_row(
                str(trade.id or ""),
                trade.instrument,
                Text(trade.side.value, style=side_style),
                f"{trade.quantity:,.0f}",
                f"{trade.entry_price:.5f}",
                f"{trade.exit_price:.5f}" if trade.exit_price else "-",
                Text(f"${trade.pnl:,.2f}" if trade.pnl else "-", style=pnl_style),
                trade.strategy,
            )

        self.console.print(table)
