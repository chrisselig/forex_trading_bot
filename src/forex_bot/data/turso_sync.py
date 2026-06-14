from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger


class TursoSyncer:
    """Push trade and order data to Turso on execution events.

    Fire-and-forget pattern — never crashes the bot on Turso errors.
    Falls back silently if TURSO_DATABASE_URL or TURSO_AUTH_TOKEN are missing.
    """

    def __init__(
        self,
        database_url: str,
        auth_token: str,
        account_type: str = "paper",
        enabled: bool = True,
    ):
        self._database_url = database_url
        self._auth_token = auth_token
        self._account_type = account_type
        self._enabled = enabled and bool(database_url) and bool(auth_token)
        self._conn: Any = None

        if not self._enabled:
            logger.warning("Turso sync disabled (missing database_url or auth_token)")

    def _get_connection(self) -> Any:
        """Lazy-connect to Turso on first use."""
        if self._conn is None:
            try:
                import libsql_experimental as libsql

                self._conn = libsql.connect(
                    database=self._database_url,
                    auth_token=self._auth_token,
                )
                logger.info(f"Connected to Turso: {self._database_url}")
            except Exception as e:
                logger.error(f"Turso connection failed: {e}")
                self._enabled = False
                raise
        return self._conn

    async def push_order(
        self,
        *,
        order_id: int,
        ib_order_id: int | None,
        instrument: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None,
        stop_loss: float | None,
        take_profit: float | None,
        status: str,
        event_id: int | None,
        strategy: str,
        entry_spread_pips: float | None,
        created_at: datetime,
    ) -> None:
        """Push an order to Turso (INSERT OR REPLACE)."""
        if not self._enabled:
            return
        try:
            conn = self._get_connection()
            conn.execute(
                "INSERT OR REPLACE INTO orders "
                "(id, ib_order_id, instrument, side, order_type, quantity, price, "
                "stop_loss, take_profit, status, event_id, strategy, "
                "entry_spread_pips, slippage_pips, created_at, filled_at, fill_price, account_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, NULL, ?)",
                (
                    order_id, ib_order_id, instrument, side, order_type,
                    quantity, price, stop_loss, take_profit, status,
                    event_id, strategy, entry_spread_pips,
                    created_at.isoformat() if created_at else None,
                    self._account_type,
                ),
            )
            conn.commit()
            logger.debug(f"Turso: pushed order #{order_id}")
        except Exception as e:
            logger.error(f"Turso push_order failed: {e}")

    async def push_order_status(
        self,
        *,
        order_id: int,
        status: str,
        fill_price: float | None = None,
        filled_at: datetime | None = None,
        slippage_pips: float | None = None,
    ) -> None:
        """Update an order's status in Turso."""
        if not self._enabled:
            return
        try:
            conn = self._get_connection()
            conn.execute(
                "UPDATE orders SET status = ?, fill_price = COALESCE(?, fill_price), "
                "filled_at = COALESCE(?, filled_at), slippage_pips = COALESCE(?, slippage_pips) "
                "WHERE id = ?",
                (
                    status,
                    fill_price,
                    filled_at.isoformat() if filled_at else None,
                    slippage_pips,
                    order_id,
                ),
            )
            conn.commit()
            logger.debug(f"Turso: updated order #{order_id} -> {status}")
        except Exception as e:
            logger.error(f"Turso push_order_status failed: {e}")

    async def push_trade(
        self,
        *,
        trade_id: int,
        order_id: int | None,
        instrument: str,
        side: str,
        quantity: float,
        entry_price: float,
        stop_loss: float | None,
        take_profit: float | None,
        entry_spread_pips: float | None,
        event_id: int | None,
        strategy: str,
        opened_at: datetime,
    ) -> None:
        """Push a new trade to Turso."""
        if not self._enabled:
            return
        try:
            conn = self._get_connection()
            conn.execute(
                "INSERT OR REPLACE INTO trades "
                "(id, order_id, instrument, side, quantity, entry_price, "
                "exit_price, stop_loss, take_profit, pnl, pnl_pips, "
                "event_id, strategy, opened_at, closed_at, notes, "
                "entry_spread_pips, fill_price, slippage_pips, account_type) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, NULL, ?, ?, ?, NULL, NULL, ?, NULL, NULL, ?)",
                (
                    trade_id, order_id, instrument, side, quantity,
                    entry_price, stop_loss, take_profit, event_id, strategy,
                    opened_at.isoformat() if opened_at else None,
                    entry_spread_pips,
                    self._account_type,
                ),
            )
            conn.commit()
            logger.debug(f"Turso: pushed trade #{trade_id}")
        except Exception as e:
            logger.error(f"Turso push_trade failed: {e}")

    async def push_trade_fill(
        self,
        *,
        order_id: int,
        fill_price: float,
        slippage_pips: float | None,
    ) -> None:
        """Update a trade's fill price and slippage in Turso."""
        if not self._enabled:
            return
        try:
            conn = self._get_connection()
            conn.execute(
                "UPDATE trades SET fill_price = ?, slippage_pips = ? WHERE order_id = ?",
                (fill_price, slippage_pips, order_id),
            )
            conn.commit()
            logger.debug(f"Turso: updated trade fill for order #{order_id}")
        except Exception as e:
            logger.error(f"Turso push_trade_fill failed: {e}")

    async def push_trade_close(
        self,
        *,
        trade_id: int,
        exit_price: float,
        pnl: float,
        pnl_pips: float,
        closed_at: datetime,
    ) -> None:
        """Update a trade's exit in Turso."""
        if not self._enabled:
            return
        try:
            conn = self._get_connection()
            conn.execute(
                "UPDATE trades SET exit_price = ?, pnl = ?, pnl_pips = ?, closed_at = ? "
                "WHERE id = ?",
                (exit_price, pnl, pnl_pips, closed_at.isoformat(), trade_id),
            )
            conn.commit()
            logger.debug(f"Turso: closed trade #{trade_id}")
        except Exception as e:
            logger.error(f"Turso push_trade_close failed: {e}")

    async def push_event(
        self,
        *,
        event_id: int,
        title: str,
        country: str,
        impact: str,
        scheduled_at: datetime,
        actual: str | None,
        forecast: str | None,
        previous: str | None,
        fred_series: str | None,
        created_at: datetime,
    ) -> None:
        """Push an event to Turso (INSERT OR REPLACE)."""
        if not self._enabled:
            return
        try:
            conn = self._get_connection()
            conn.execute(
                "INSERT OR REPLACE INTO events "
                "(id, title, country, impact, scheduled_at, actual, forecast, "
                "previous, fred_series, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id, title, country, impact,
                    scheduled_at.isoformat() if scheduled_at else None,
                    actual, forecast, previous, fred_series,
                    created_at.isoformat() if created_at else None,
                ),
            )
            conn.commit()
            logger.debug(f"Turso: pushed event #{event_id} ({title})")
        except Exception as e:
            logger.error(f"Turso push_event failed: {e}")

    async def push_event_actual(
        self,
        *,
        event_id: int,
        actual: str,
    ) -> None:
        """Update an event's actual value in Turso."""
        if not self._enabled:
            return
        try:
            conn = self._get_connection()
            conn.execute(
                "UPDATE events SET actual = ? WHERE id = ?",
                (actual, event_id),
            )
            conn.commit()
            logger.debug(f"Turso: updated event #{event_id} actual={actual}")
        except Exception as e:
            logger.error(f"Turso push_event_actual failed: {e}")
