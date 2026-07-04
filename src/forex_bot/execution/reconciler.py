from __future__ import annotations

import asyncio

from loguru import logger
from ib_async import Trade as IBTrade
from pydantic import BaseModel, ConfigDict

from forex_bot.broker.client import IBClient
from forex_bot.broker.accounts import AccountService
from forex_bot.models.orders import Position


class ReconcileState(BaseModel):
    """Snapshot of broker-side state at startup."""

    model_config = ConfigDict(arbitrary_types_allowed=True)  # IBTrade objects

    account_id: str
    net_liquidation: float
    positions: list[Position]
    orders: list[IBTrade]

    @property
    def open_positions(self) -> int:
        return len(self.positions)

    @property
    def open_orders(self) -> int:
        return len(self.orders)


class Reconciler:
    """Reconciles local state with IB on startup."""

    def __init__(self, client: IBClient):
        self._client = client
        self._account_service = AccountService(client)

    async def reconcile(self) -> ReconcileState:
        """Sync local state with IB. Returns summary of current state."""
        await self._client.ensure_connected()

        # Independent requests — fetch concurrently
        positions, open_orders, summary = await asyncio.gather(
            self._account_service.get_positions(),
            self._client.get_open_orders(),
            self._account_service.get_summary(),
        )

        state = ReconcileState(
            account_id=summary.account_id,
            net_liquidation=summary.net_liquidation,
            positions=positions,
            orders=open_orders,
        )

        logger.info(
            f"Reconciled with IB: account={summary.account_id} "
            f"NLV=${summary.net_liquidation:,.2f} "
            f"positions={len(positions)} orders={len(open_orders)}"
        )

        if positions:
            for pos in positions:
                logger.info(f"  Position: {pos.side} {pos.quantity} {pos.instrument} @ {pos.avg_cost}")

        if open_orders:
            logger.info(f"  {len(open_orders)} open orders found")

        return state
