from __future__ import annotations

import asyncio
from typing import Optional

import typer
from rich.console import Console

app = typer.Typer(name="forex-bot", help="Event-driven forex trading bot for IBKR")
console = Console()


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
        from forex_bot.broker.accounts import AccountService
        from forex_bot.reporting.dashboard import Dashboard
        from forex_bot.risk.circuit_breaker import CircuitBreaker

        dashboard = Dashboard()
        async with IBClient() as client:
            account_service = AccountService(client)
            summary = await account_service.get_summary()
            positions = await account_service.get_positions()
            dashboard.show_account(summary)
            if positions:
                console.print(f"\n[cyan]Open Positions: {len(positions)}[/cyan]")
                for pos in positions:
                    console.print(f"  {pos.side} {pos.quantity} {pos.instrument} @ {pos.avg_cost}")
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
