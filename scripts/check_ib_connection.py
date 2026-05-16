#!/usr/bin/env python3
"""Verify IB Gateway connectivity: connect, print account summary, fetch one bar."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from forex_bot.broker.client import IBClient
from forex_bot.broker.pricing import PricingService
from forex_bot.broker.accounts import AccountService
from forex_bot.reporting.dashboard import Dashboard


async def main():
    dashboard = Dashboard()

    print("Connecting to IB Gateway...")
    async with IBClient() as client:
        print("Connected!\n")

        # Account summary
        account_service = AccountService(client)
        summary = await account_service.get_summary()
        dashboard.show_account(summary)

        # Positions
        positions = await account_service.get_positions()
        if positions:
            print(f"\nOpen positions: {len(positions)}")
            for pos in positions:
                print(f"  {pos.side} {pos.quantity} {pos.instrument} @ {pos.avg_cost}")
        else:
            print("\nNo open positions.")

        # Fetch one historical bar
        pricing = PricingService(client)
        bars = await pricing.get_historical_bars("EURUSD", duration="1 D", bar_size="1 hour")
        if bars:
            last = bars[-1]
            print(f"\nLatest EURUSD 1h bar:")
            print(f"  Time:  {last.timestamp}")
            print(f"  Open:  {last.open:.5f}")
            print(f"  High:  {last.high:.5f}")
            print(f"  Low:   {last.low:.5f}")
            print(f"  Close: {last.close:.5f}")

        print("\nAll checks passed!")


if __name__ == "__main__":
    asyncio.run(main())
