from __future__ import annotations

from loguru import logger
from ib_async import IB

from forex_bot.broker.client import IBClient
from forex_bot.models.account import AccountSummary
from forex_bot.models.orders import Position, OrderSide


class AccountService:
    """Account information and position management."""

    def __init__(self, client: IBClient):
        self._client = client

    @property
    def ib(self) -> IB:
        return self._client.ib

    async def get_summary(self) -> AccountSummary:
        return await self._client.get_account_summary()

    async def get_positions(self) -> list[Position]:
        """Get current positions as our Position model."""
        await self._client.ensure_connected()
        ib_positions = self.ib.positions()
        positions = []
        for pos in ib_positions:
            if pos.position == 0:
                continue
            positions.append(
                Position(
                    instrument=pos.contract.localSymbol or pos.contract.symbol,
                    side=OrderSide.BUY if pos.position > 0 else OrderSide.SELL,
                    quantity=abs(pos.position),
                    avg_cost=pos.avgCost,
                    unrealized_pnl=0.0,
                    market_value=abs(pos.position) * pos.avgCost,
                )
            )
        return positions

    async def get_net_liquidation(self) -> float:
        summary = await self.get_summary()
        return summary.net_liquidation

    async def get_buying_power(self) -> float:
        summary = await self.get_summary()
        return summary.buying_power
