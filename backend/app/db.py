import asyncio

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import asyncpg
from alembic import command
from alembic.config import Config

from app.common.config import (
    APP_DB_DATABASE,
    APP_DB_HOST,
    APP_DB_PASSWORD,
    APP_DB_PORT,
    APP_DB_SCHEMA,
    APP_DB_USER,
)

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()
_ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


async def init_db() -> None:
    """Upgrade the product schema and initialize its connection pool."""

    await asyncio.to_thread(_run_migrations)
    await get_pool()


def _run_migrations() -> None:
    config = Config(str(_ALEMBIC_INI))
    command.upgrade(config, "head")


async def get_pool() -> asyncpg.Pool:
    global _pool

    if _pool is not None:
        return _pool

    async with _pool_lock:
        if _pool is None:
            _pool = await asyncpg.create_pool(
                host=APP_DB_HOST,
                port=APP_DB_PORT,
                database=APP_DB_DATABASE,
                user=APP_DB_USER,
                password=APP_DB_PASSWORD,
                min_size=1,
                max_size=10,
                command_timeout=60,
                server_settings={
                    "search_path": f"{APP_DB_SCHEMA},public",
                    "timezone": "UTC",
                },
            )

    return _pool


@asynccontextmanager
async def db_connection() -> AsyncIterator[asyncpg.Connection]:
    pool = await get_pool()
    async with pool.acquire() as connection:
        yield connection


async def close_db() -> None:
    global _pool

    if _pool is None:
        return

    await _pool.close()
    _pool = None
