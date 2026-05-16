from __future__ import annotations

from loguru import logger

from forex_bot.broker.client import IBClient
from forex_bot.broker.accounts import AccountService


class Reconciler:
    """Reconciles local state with IB on startup."""

    def __init__(self, client: IBClient):
        self._client = client
        self._account_service = AccountService(client)

    async def reconcile(self) -> dict:
        """Sync local state with IB. Returns summary of current state."""
        await self._client.ensure_connected()

        # Fetch current state from IB
        positions = await self._account_service.get_positions()
        open_orders = await self._client.get_open_orders()
        summary = await self._account_service.get_summary()

        state = {
            "account_id": summary.account_id,
            "net_liquidation": summary.net_liquidation,
            "open_positions": len(positions),
            "open_orders": len(open_orders),
            "positions": positions,
            "orders": open_orders,
        }

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
