from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

from loguru import logger

# After a failure, skip pushes for this long before trying again. A transient
# Turso outage must not permanently disable sync for the process lifetime.
_RETRY_BACKOFF_SECONDS = 300.0
# Remind the operator that pushes are being skipped at most this often.
_SKIP_LOG_INTERVAL_SECONDS = 600.0


class TursoSyncer:
    """Push trade and order data to Turso on execution events.

    Fire-and-forget pattern — never crashes the bot on Turso errors.
    Falls back silently if TURSO_DATABASE_URL or TURSO_AUTH_TOKEN are missing.

    libsql_experimental is synchronous; every statement runs via
    asyncio.to_thread so a slow/unreachable Turso endpoint can never stall
    the event loop on the order hot path.
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
        self._retry_after: float = 0.0
        self._last_skip_log: float = 0.0

        if not self._enabled:
            logger.warning("Turso sync disabled (missing database_url or auth_token)")

    def _active(self) -> bool:
        """Whether pushes should currently be attempted."""
        if not self._enabled:
            return False
        now = time.monotonic()
        if now < self._retry_after:
            if now - self._last_skip_log > _SKIP_LOG_INTERVAL_SECONDS:
                self._last_skip_log = now
                logger.warning(
                    f"Turso sync degraded — skipping pushes for another "
                    f"{self._retry_after - now:.0f}s after a failure"
                )
            return False
        return True

    def _record_failure(self, op: str, error: Exception) -> None:
        """Log a push failure and back off; drop the connection so the next
        attempt reconnects fresh."""
        logger.error(f"Turso {op} failed: {error}")
        self._conn = None
        self._retry_after = time.monotonic() + _RETRY_BACKOFF_SECONDS

    def _get_connection(self) -> Any:
        """Lazy-connect to Turso on first use (runs in a worker thread)."""
        if self._conn is None:
            import libsql_experimental as libsql

            self._conn = libsql.connect(
                database=self._database_url,
                auth_token=self._auth_token,
            )
            logger.info(f"Connected to Turso: {self._database_url}")
        return self._conn

    def _execute_sync(self, statements: list[tuple[str, tuple]]) -> None:
        """Run statements + commit synchronously (call via asyncio.to_thread)."""
        conn = self._get_connection()
        for sql, params in statements:
            conn.execute(sql, params)
        conn.commit()

    async def _push(self, op: str, statements: list[tuple[str, tuple]]) -> bool:
        """Execute statements off the event loop; never raises."""
        if not self._active():
            return False
        try:
            await asyncio.to_thread(self._execute_sync, statements)
            return True
        except Exception as e:
            self._record_failure(op, e)
            return False

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
        ok = await self._push(
            "push_order",
            [(
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
            )],
        )
        if ok:
            logger.debug(f"Turso: pushed order #{order_id}")

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
        ok = await self._push(
            "push_order_status",
            [(
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
            )],
        )
        if ok:
            logger.debug(f"Turso: updated order #{order_id} -> {status}")

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
        ok = await self._push(
            "push_trade",
            [(
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
            )],
        )
        if ok:
            logger.debug(f"Turso: pushed trade #{trade_id}")

    async def push_trade_fill(
        self,
        *,
        order_id: int,
        fill_price: float,
        slippage_pips: float | None,
    ) -> None:
        """Update a trade's fill price and slippage in Turso."""
        ok = await self._push(
            "push_trade_fill",
            [(
                "UPDATE trades SET fill_price = ?, slippage_pips = ? WHERE order_id = ?",
                (fill_price, slippage_pips, order_id),
            )],
        )
        if ok:
            logger.debug(f"Turso: updated trade fill for order #{order_id}")

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
        ok = await self._push(
            "push_trade_close",
            [(
                "UPDATE trades SET exit_price = ?, pnl = ?, pnl_pips = ?, closed_at = ? "
                "WHERE id = ?",
                (exit_price, pnl, pnl_pips, closed_at.isoformat(), trade_id),
            )],
        )
        if ok:
            logger.debug(f"Turso: closed trade #{trade_id}")

    async def push_commission(
        self,
        *,
        order_id: int,
        commission: float,
    ) -> None:
        """Update commission on an order and its matching trade in Turso."""
        ok = await self._push(
            "push_commission",
            [
                ("UPDATE orders SET commission = ? WHERE id = ?", (commission, order_id)),
                ("UPDATE trades SET commission = ? WHERE order_id = ?", (commission, order_id)),
            ],
        )
        if ok:
            logger.debug(f"Turso: updated commission for order #{order_id}: ${commission:.4f}")

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
        ok = await self._push(
            "push_event",
            [(
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
            )],
        )
        if ok:
            logger.debug(f"Turso: pushed event #{event_id} ({title})")

    async def push_event_actual(
        self,
        *,
        event_id: int,
        actual: str,
    ) -> None:
        """Update an event's actual value in Turso."""
        ok = await self._push(
            "push_event_actual",
            [(
                "UPDATE events SET actual = ? WHERE id = ?",
                (actual, event_id),
            )],
        )
        if ok:
            logger.debug(f"Turso: updated event #{event_id} actual={actual}")
