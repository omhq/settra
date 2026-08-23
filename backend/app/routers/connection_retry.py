from __future__ import annotations

import logging

from typing import Any

import asyncpg

from fastapi import HTTPException

from app.db import db_connection
from app.routers.constants import (
    GOOGLE_SHEETS_KEY,
    POSTGRES_DATABASE,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from app.sync.config import config_path, read_sync_config
from app.sync.loader import run_connection_sync
from app.sync.secrets import load_google_oauth_secret

logger = logging.getLogger(__name__)


async def retry_connection_status(connection_id: int) -> dict[str, Any]:
    await run_connection_sync(connection_id, trigger="retry")
    connection = await _load_connection(connection_id)

    if not connection:
        raise HTTPException(404, "Connection not found")

    return await _collect_connection_diagnostics(connection)


async def list_connection_diagnostics() -> list[dict[str, Any]]:
    async with db_connection() as db:
        rows = await db.fetch(
            """
            SELECT id, name, slug, plugin, status, created_at,
                   last_sync_started_at, last_synced_at, last_sync_error
            FROM connections
            WHERE plugin = $1
            ORDER BY created_at DESC, id DESC
            """,
            GOOGLE_SHEETS_KEY,
        )

    return [await _collect_connection_diagnostics(dict(connection)) for connection in rows]


async def refresh_connection_data(connection_id: int) -> dict[str, Any]:
    await run_connection_sync(connection_id, trigger="refresh")
    connection = await _load_connection(connection_id)

    if not connection:
        raise HTTPException(404, "Connection not found")

    return await _collect_connection_diagnostics(connection)


async def _load_connection(connection_id: int) -> dict[str, Any] | None:
    async with db_connection() as db:
        row = await db.fetchrow(
            """
            SELECT id, name, slug, plugin, status, created_at,
                   last_sync_started_at, last_synced_at, last_sync_error
            FROM connections
            WHERE id = $1 AND plugin = $2
            """,
            connection_id,
            GOOGLE_SHEETS_KEY,
        )

    return dict(row) if row else None


async def _collect_connection_diagnostics(
    connection: dict[str, Any],
) -> dict[str, Any]:
    slug = str(connection["slug"])
    warnings: list[str] = []
    config = await read_sync_config(slug)
    oauth = await load_google_oauth_secret(required=False)

    if not config_path(slug).is_file():
        warnings.append("Sync YAML is missing; edit this source to recreate it.")

    if not oauth:
        warnings.append("Google OAuth is disconnected; the durable snapshot is read-only.")

    table_count: int | None = None
    column_count: int | None = None
    postgres_state = "unreachable"
    postgres_error = None

    try:
        pg = await asyncpg.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DATABASE,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            timeout=5,
        )
        try:
            table_count = await pg.fetchval(
                """
                SELECT COUNT(*)::int
                FROM information_schema.tables
                WHERE table_schema = $1
                  AND table_name NOT LIKE '\\_dlt\\_%' ESCAPE '\\'
                """,
                slug,
            )
            column_count = await pg.fetchval(
                """
                SELECT COUNT(*)::int
                FROM information_schema.columns
                WHERE table_schema = $1
                  AND table_name NOT LIKE '\\_dlt\\_%' ESCAPE '\\'
                  AND column_name NOT LIKE '\\_dlt\\_%' ESCAPE '\\'
                """,
                slug,
            )
            postgres_state = "ready"
        finally:
            await pg.close()
    except Exception as exc:
        postgres_error = str(exc)
        warnings.append(f"PostgreSQL is unavailable: {exc}")

    schedule = config.get("load", {}).get("schedule", {}) if config else {}
    status = str(connection.get("status") or "pending")
    sync_state = (
        "failed"
        if status == "failed"
        else "empty"
        if postgres_state == "ready" and table_count == 0
        else postgres_state
    )

    return {
        **connection,
        "status": status,
        "detail": connection.get("last_sync_error"),
        "error": connection.get("last_sync_error"),
        "warnings": warnings,
        "sync_state": sync_state,
        "postgres_state": postgres_state,
        "postgres_error": postgres_error,
        "table_count": table_count,
        "column_count": column_count,
        "oauth_connected": bool(oauth),
        "schedule": schedule,
    }
