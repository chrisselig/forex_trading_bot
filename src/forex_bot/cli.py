from __future__ import annotations

import asyncio
from typing import Optional

import typer
from rich.console import Console

app = typer.Typer(name="forex-bot", help="Event-driven forex trading bot for IBKR")
console = Console()

# Distinct clientId so CLI commands can connect to IB while the live bot
# (clientId=1) is running — IB rejects a duplicate clientId. (Spread sampler
# uses 9; CLI uses 8.)
CLI_CLIENT_ID = 8


def _run(coro):
    """Run an async function synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


@app.command()
def run():
    """Start the trading bot."""
    from forex_bot.scheduler.orchestrator import Orchestrator

    orchestrator = Orchestrator()
    asyncio.run(orchestrator.run_forever())


@app.command()
def status():
    """Show current bot status and account summary."""
    async def _status():
        from forex_bot.broker.client import IBClient
        from forex_bot.broker.pricing import PricingService
        from forex_bot.config import get_settings
        from forex_bot.data.database import init_db
        from forex_bot.data.trade_journal import TradeJournal
        from forex_bot.execution.engine import ExecutionEngine
        from forex_bot.execution.monitor import PositionMonitor
        from forex_bot.reporting.dashboard import Dashboard
        from forex_bot.risk.circuit_breaker import CircuitBreaker
        from forex_bot.risk.manager import RiskManager
        from forex_bot.strategy.carry import CarryManager

        dashboard = Dashboard()
        # Distinct clientId so this works while the live bot holds clientId=1.
        async with IBClient(client_id=CLI_CLIENT_ID) as client:
            summary = await client.get_account_summary()
            positions = await client.get_portfolio()

            # Carry (IDEALPRO spot FX) never appears in ib.positions()/
            # ib.portfolio() — it settles as currency cash-balance changes,
            # not a broker "position" — so it's tracked and priced separately.
            carry_pnl = []
            if get_settings().carry.enabled:
                await init_db()
                journal = TradeJournal()
                pricing = PricingService(client)
                circuit_breaker = CircuitBreaker()
                risk_manager = RiskManager(client, circuit_breaker, journal)
                engine = ExecutionEngine(client, risk_manager, circuit_breaker, journal)
                monitor = PositionMonitor(client, journal, circuit_breaker)
                carry_manager = CarryManager(client, engine, journal, pricing, monitor)
                await carry_manager.restore_state()
                carry_pnl = await carry_manager.get_open_positions_pnl()

            dashboard.show_account(summary)

            rows = [(p.instrument, p.side, p.quantity, p.avg_cost, p.unrealized_pnl) for p in positions]
            rows += [
                (p.instrument, p.side, p.quantity, p.entry_price, p.unrealized_pnl_cad)
                for p in carry_pnl
            ]
            if rows:
                console.print(f"\n[cyan]Open Positions: {len(rows)}[/cyan]")
                for instrument, side, quantity, avg_cost, pnl in sorted(rows, key=lambda r: -abs(r[4])):
                    color = "green" if pnl >= 0 else "red"
                    console.print(
                        f"  {side} {quantity:,.0f} {instrument} "
                        f"@ {avg_cost:.5g}  "
                        f"[{color}]{pnl:+,.2f}[/{color}]"
                    )
            else:
                console.print("\n[dim]No open positions[/dim]")

    asyncio.run(_status())


@app.command()
def events(hours: int = typer.Option(168, help="Hours ahead to look for events")):
    """Show upcoming economic events."""
    async def _events():
        from forex_bot.calendar.scraper import ForexFactoryScraper
        from forex_bot.calendar.parser import EventParser
        from forex_bot.reporting.dashboard import Dashboard

        dashboard = Dashboard()
        scraper = ForexFactoryScraper()
        parser = EventParser()

        raw_events = await scraper.fetch_week()
        filtered = parser.filter_events(raw_events)
        dashboard.show_events(filtered)
        console.print(f"\n[dim]{len(filtered)} target events found[/dim]")

    asyncio.run(_events())


@app.command()
def history(limit: int = typer.Option(20, help="Number of recent trades")):
    """Show trade history."""
    async def _history():
        from forex_bot.data.database import init_db
        from forex_bot.data.trade_journal import TradeJournal
        from forex_bot.reporting.dashboard import Dashboard

        await init_db()
        journal = TradeJournal()
        dashboard = Dashboard()
        trades = await journal.get_trades(limit=limit)
        if trades:
            dashboard.show_trades(trades)
        else:
            console.print("[dim]No trades recorded yet[/dim]")

    asyncio.run(_history())


@app.command()
def performance(strategy: Optional[str] = typer.Option(None, help="Filter by strategy")):
    """Show trading performance statistics."""
    async def _performance():
        from forex_bot.data.database import init_db
        from forex_bot.data.trade_journal import TradeJournal
        from forex_bot.reporting.performance import PerformanceTracker
        from forex_bot.reporting.dashboard import Dashboard

        await init_db()
        journal = TradeJournal()
        tracker = PerformanceTracker(journal)
        dashboard = Dashboard()

        if strategy:
            stats = await tracker.get_stats(strategy=strategy)
            dashboard.show_performance(stats, title=f"Performance: {strategy}")
        else:
            stats = await tracker.get_stats()
            dashboard.show_performance(stats)
            # Also show per-strategy breakdown
            by_strategy = await tracker.get_stats_by_strategy()
            for name, s in by_strategy.items():
                dashboard.show_performance(s, title=f"Strategy: {name}")

    asyncio.run(_performance())


@app.command(name="test-connection")
def test_connection():
    """Test connection to IB Gateway."""
    async def _test():
        from forex_bot.broker.client import IBClient
        from forex_bot.broker.pricing import PricingService
        from forex_bot.reporting.dashboard import Dashboard

        dashboard = Dashboard()
        try:
            async with IBClient() as client:
                console.print("[green]Connected to IB Gateway[/green]")
                summary = await client.get_account_summary()
                dashboard.show_account(summary)

                # Fetch one historical bar
                pricing = PricingService(client)
                bars = await pricing.get_historical_bars("EURUSD", duration="1 D", bar_size="1 hour")
                if bars:
                    last = bars[-1]
                    console.print(
                        f"\n[cyan]Latest EURUSD 1h bar:[/cyan] "
                        f"O={last.open:.5f} H={last.high:.5f} "
                        f"L={last.low:.5f} C={last.close:.5f}"
                    )
                console.print("\n[green]All checks passed![/green]")
        except Exception as e:
            console.print(f"[red]Connection failed: {e}[/red]")
            raise typer.Exit(1)

    asyncio.run(_test())


@app.command()
def calendar(
    days: int = typer.Option(30, help="Days ahead to include"),
    output: Optional[str] = typer.Option(None, help="Write JSON to this file path"),
):
    """Export upcoming tradeable events as JSON for the web dashboard."""
    async def _calendar():
        from pathlib import Path

        from forex_bot.calendar.export import DEFAULT_CALENDAR_PATH, export_calendar_json

        if output:
            out_path = Path(output)
        elif output is None:
            # No --output flag: print to stdout, don't write file
            out_path = None
        else:
            out_path = DEFAULT_CALENDAR_PATH

        json_str = await export_calendar_json(output_path=out_path, days=days)

        if out_path:
            console.print(f"[green]Calendar exported to {out_path}[/green]")
        else:
            console.print(json_str)

    asyncio.run(_calendar())


@app.command(name="backfill-actuals")
def backfill_actuals(
    hours: int = typer.Option(168, help="Hours to look back for missing actuals"),
):
    """Backfill missing actual values from Forex Factory."""
    async def _backfill():
        from rich.table import Table

        from forex_bot.calendar.scraper import ForexFactoryScraper
        from forex_bot.calendar.store import EventStore
        from forex_bot.data.database import init_db

        await init_db()
        store = EventStore()
        scraper = ForexFactoryScraper()

        missing = await store.get_events_missing_actuals(since_hours=hours)
        if not missing:
            console.print("[green]0 events missing actuals — nothing to backfill[/green]")
            return

        console.print(f"[yellow]Found {len(missing)} events missing actuals, fetching FF data...[/yellow]")

        ff_events = await scraper.fetch_week()
        await store.update_actuals(ff_events)

        # Re-query to show final state
        still_missing = await store.get_events_missing_actuals(since_hours=hours)
        filled = len(missing) - len(still_missing)

        table = Table(title="Backfill Results")
        table.add_column("Metric", style="cyan")
        table.add_column("Count", justify="right")
        table.add_row("Events missing actuals (before)", str(len(missing)))
        table.add_row("Actuals filled", str(filled))
        table.add_row("Still missing", str(len(still_missing)))
        console.print(table)

        if still_missing:
            detail = Table(title="Still Missing")
            detail.add_column("Event", style="yellow")
            detail.add_column("Scheduled (UTC)")
            for evt in still_missing:
                detail.add_row(evt.title, evt.scheduled_at.strftime("%Y-%m-%d %H:%M"))
            console.print(detail)

    asyncio.run(_backfill())


@app.command()
def backtest(
    months: int = typer.Option(6, help="Months of history to backtest"),
    strategy_name: Optional[str] = typer.Option(None, help="Strategy to backtest"),
):
    """Run a historical backtest."""
    async def _backtest():
        from forex_bot.data.database import init_db

        await init_db()
        console.print(f"[yellow]Backtesting over {months} months...[/yellow]")
        console.print("[dim]Backtest runner will be available after historical data is loaded.[/dim]")
        console.print("[dim]Use: forex-bot fetch-history first, then re-run backtest.[/dim]")

    asyncio.run(_backtest())


if __name__ == "__main__":
    app()
