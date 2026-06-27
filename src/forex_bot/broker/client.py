from __future__ import annotations

from loguru import logger
from ib_async import IB

from forex_bot.config import get_settings
from forex_bot.broker.exceptions import ConnectionError
from forex_bot.models.account import AccountSummary


class IBClient:
    """Manages the connection to IB Gateway/TWS via ib_async."""

    def __init__(self, host: str | None = None, port: int | None = None, client_id: int | None = None):
        settings = get_settings()
        self._host = host or settings.broker.host
        self._port = port or settings.broker.port
        self._client_id = client_id or settings.broker.client_id
        self._timeout = settings.broker.timeout
        self.ib = IB()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self.ib.isConnected()

    async def connect(self) -> None:
        """Connect to IB Gateway/TWS."""
        if self.is_connected:
            logger.debug("Already connected to IB")
            return
        try:
            logger.info(f"Connecting to IB Gateway at {self._host}:{self._port} (clientId={self._client_id})")
            await self.ib.connectAsync(
                host=self._host,
                port=self._port,
                clientId=self._client_id,
                timeout=self._timeout,
            )
            self._connected = True
            logger.info("Successfully connected to IB Gateway")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to IB Gateway at {self._host}:{self._port}: {e}") from e

    async def disconnect(self) -> None:
        """Disconnect from IB Gateway/TWS."""
        if self.is_connected:
            self.ib.disconnect()
            self._connected = False
            logger.info("Disconnected from IB Gateway")

    async def ensure_connected(self) -> None:
        """Reconnect if the connection was lost."""
        if not self.is_connected:
            logger.warning("IB connection lost, attempting reconnect...")
            await self.connect()

    async def get_account_summary(self) -> AccountSummary:
        """Fetch account summary from IB."""
        await self.ensure_connected()
        summary_items = await self.ib.accountSummaryAsync()
        data: dict[str, str] = {}
        for item in summary_items:
            data[item.tag] = item.value

        return AccountSummary(
            account_id=data.get("AccountCode", ""),
            net_liquidation=float(data.get("NetLiquidation", 0)),
            total_cash=float(data.get("TotalCashValue", 0)),
            buying_power=float(data.get("BuyingPower", 0)),
            gross_position_value=float(data.get("GrossPositionValue", 0)),
            maintenance_margin=float(data.get("MaintMarginReq", 0)),
            unrealized_pnl=float(data.get("UnrealizedPnL", 0)),
            realized_pnl=float(data.get("RealizedPnL", 0)),
        )

    async def get_positions(self) -> list:
        """Fetch current positions from IB."""
        await self.ensure_connected()
        return self.ib.positions()

    async def get_open_orders(self) -> list:
        """Fetch all open orders from IB."""
        await self.ensure_connected()
        return await self.ib.reqAllOpenOrdersAsync()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
