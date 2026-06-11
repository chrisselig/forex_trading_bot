from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from loguru import logger

from forex_bot.data.schemas import Base

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
DB_PATH = DATA_DIR / "forex_bot.db"

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        url = f"sqlite+aiosqlite:///{DB_PATH}"
        _engine = create_async_engine(url, echo=False)
        logger.debug(f"Created database engine: {DB_PATH}")
    return _engine


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(_get_engine(), expire_on_commit=False)
    return _session_factory


async def init_db() -> None:
    """Create all database tables and add any missing columns."""
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
    logger.info(f"Database initialized at {DB_PATH}")


def _add_missing_columns(connection) -> None:
    """Add columns that were added after initial schema creation.

    SQLAlchemy create_all does NOT alter existing tables. This handles
    schema evolution for SQLite without requiring Alembic.
    """
    migrations = [
        ("trades", "entry_spread_pips", "FLOAT"),
        ("trades", "fill_price", "FLOAT"),
        ("trades", "slippage_pips", "FLOAT"),
        ("orders", "entry_spread_pips", "FLOAT"),
        ("orders", "slippage_pips", "FLOAT"),
    ]
    for table, column, col_type in migrations:
        try:
            connection.execute(
                __import__("sqlalchemy").text(
                    f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                )
            )
            logger.info(f"Added column {table}.{column}")
        except Exception:
            # Column already exists — expected on subsequent runs
            pass


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session."""
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
