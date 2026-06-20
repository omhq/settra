import logging

from typing import Any

import asyncpg
import aiosqlite

from fastapi import HTTPException

from app.db import DB_PATH
from app.routers.connection_config import (
    load_connectors,
    normalize_credentials,
    quote_ident,
    read_connection_credentials,
    validate_connection_fields,
    validate_provider_credentials,
)
from app.routers.constants import (
    STEAMPIPE_CONFIG_DIR,
    STEAMPIPE_DB_PASSWORD,
    STEAMPIPE_HOST,
    STEAMPIPE_PORT,
)

logger = logging.getLogger(__name__)


async def retry_connection_status(connection_id: int) -> dict[str, Any]:
    connection = await _load_connection(connection_id)

    if not connection:
        raise HTTPException(404, "Connection not found")

    return await _collect_connection_diagnostics(
        connection,
        validate_provider=True,
        persist_status=True,
    )


async def list_connection_fdw_diagnostics() -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("""
            SELECT id, name, slug, plugin, status, created_at
            FROM connections
            ORDER BY created_at DESC, id DESC
            """) as cur:
            rows = [dict(row) for row in await cur.fetchall()]

    return [
        await _collect_connection_diagnostics(
            connection,
            validate_provider=False,
            persist_status=False,
        )
        for connection in rows
    ]


async def refresh_connection_fdw_cache(connection_id: int) -> dict[str, Any]:
    connection = await _load_connection(connection_id)

    if not connection:
        raise HTTPException(404, "Connection not found")

    return await _collect_connection_diagnostics(
        connection,
        validate_provider=False,
        persist_status=False,
        clear_meta_cache=True,
    )


async def _load_connection(connection_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            """
            SELECT id, name, slug, plugin, status, created_at
            FROM connections
            WHERE id = ?
            """,
            (connection_id,),
        ) as cur:
            row = await cur.fetchone()

    return dict(row) if row else None


async def _collect_connection_diagnostics(
    connection: dict[str, Any],
    *,
    validate_provider: bool,
    persist_status: bool,
    clear_meta_cache: bool = False,
) -> dict[str, Any]:
    connection_id = int(connection["id"])
    name = str(connection.get("name") or "")
    slug = str(connection.get("slug") or "")
    plugin = str(connection.get("plugin") or "")
    status = str(connection.get("status") or "active")
    detail = None
    warnings: list[str] = []

    if not slug:
        raise HTTPException(500, "Connection slug is missing")

    if not (STEAMPIPE_CONFIG_DIR / f"{slug}.spc").exists():
        detail = "Config file missing - edit the connection to re-enter credentials"

        if persist_status:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE connections SET status = 'failed' WHERE id = ?",
                    (connection_id,),
                )
                await db.commit()

        return {
            "id": connection_id,
            "name": name,
            "slug": slug,
            "plugin": plugin,
            "status": "failed",
            "detail": detail,
            "error": detail,
            "warnings": [],
        }

    connectors = await load_connectors()
    connector = connectors.get(plugin, {})

    if not connector:
        warnings.append(f"Connector metadata for '{plugin}' was not found.")
    elif validate_provider:
        creds = await read_connection_credentials(slug)
        creds = normalize_credentials(connector, creds)

        try:
            validate_connection_fields(connector, creds)
        except HTTPException as exc:
            status = "failed"
            detail = str(exc.detail)

        if status == "active":
            try:
                await validate_provider_credentials(connector, creds)
            except HTTPException as exc:
                status = "failed"
                detail = str(exc.detail)

    fdw_state = None
    fdw_error = None
    fdw_table_count = None
    fdw_column_count = None
    fdw_plugin = None
    fdw_plugin_instance = None
    fdw_config_file = None
    fdw_schema_mode = None
    fdw_schema_hash = None
    cache_cleared = False
    semantic_table_count = None
    semantic_column_count = None

    try:
        pg = await asyncpg.connect(
            host=STEAMPIPE_HOST,
            port=STEAMPIPE_PORT,
            database="steampipe",
            user="steampipe",
            password=STEAMPIPE_DB_PASSWORD,
            timeout=5,
        )
        try:
            if clear_meta_cache:
                await pg.fetchrow(
                    "SELECT steampipe_internal.meta_connection_cache_clear($1)",
                    slug,
                )

                cache_cleared = True

            conn_row = await pg.fetchrow(
                """
                SELECT
                    state,
                    error,
                    plugin,
                    plugin_instance,
                    file_name,
                    schema_mode,
                    schema_hash
                FROM steampipe_internal.steampipe_connection
                WHERE name = $1
                """,
                slug,
            )

            if conn_row:
                fdw_state = conn_row["state"]
                fdw_error = conn_row["error"] or None
                fdw_plugin = conn_row["plugin"] or None
                fdw_plugin_instance = conn_row["plugin_instance"] or None
                fdw_config_file = conn_row["file_name"] or None
                fdw_schema_mode = conn_row["schema_mode"] or None
                fdw_schema_hash = conn_row["schema_hash"] or None
            else:
                warnings.append("Steampipe has not registered this connection yet.")

            count_row = await pg.fetchrow(
                """
                SELECT COUNT(*)::int AS n
                FROM information_schema.tables
                WHERE table_schema = $1
                """,
                slug,
            )

            if count_row is not None:
                fdw_table_count = count_row["n"]

                if fdw_table_count == 0:
                    warnings.append(
                        "Steampipe currently exposes 0 tables for this connection."
                    )

            column_row = await pg.fetchrow(
                """
                SELECT COUNT(*)::int AS n
                FROM information_schema.columns
                WHERE table_schema = $1
                """,
                slug,
            )

            if column_row is not None:
                fdw_column_count = column_row["n"]

            test_table = connector.get("test_table")

            if test_table:
                try:
                    test_sql = (
                        f"SELECT 1 FROM {quote_ident(slug)}."
                        f"{quote_ident(str(test_table))} LIMIT 1"
                    )

                    await pg.fetchrow(test_sql)
                except Exception as exc:
                    fdw_error = str(exc)
                    warnings.append(f"Steampipe test query failed: {exc}")
        finally:
            await pg.close()
    except Exception as exc:
        logger.warning(
            "Steampipe retry diagnostics failed connection_id=%s slug=%s error=%s",
            connection_id,
            slug,
            exc,
        )

        fdw_state = "unreachable"
        fdw_error = str(exc)

        warnings.append(f"Could not reach Steampipe for diagnostics: {exc}")

    if fdw_state and str(fdw_state).lower() not in {"ready", "connected"}:
        warnings.append(f"Steampipe connection state is {fdw_state}.")

        if not fdw_error and (fdw_plugin_instance or fdw_plugin):
            warnings.append(
                "Steampipe tried to load "
                f"{fdw_plugin_instance or fdw_plugin}; confirm that exact "
                "plugin spec is installed in the Steampipe container."
            )

    if fdw_error and not any(fdw_error in warning for warning in warnings):
        warnings.append(f"Steampipe reported: {fdw_error}")

    async with aiosqlite.connect(DB_PATH) as db:
        semantic_counts = await _connection_semantic_counts(db, connection_id)
        semantic_table_count = semantic_counts["table_count"]
        semantic_column_count = semantic_counts["column_count"]

        if persist_status:
            await db.execute(
                "UPDATE connections SET status = ? WHERE id = ?",
                (status, connection_id),
            )
            await db.commit()

    return {
        "id": connection_id,
        "name": name,
        "slug": slug,
        "plugin": plugin,
        "status": status,
        "detail": detail,
        "error": detail,
        "warnings": list(dict.fromkeys(warnings)),
        "fdw_state": fdw_state,
        "fdw_error": fdw_error,
        "fdw_table_count": fdw_table_count,
        "fdw_column_count": fdw_column_count,
        "fdw_plugin": fdw_plugin,
        "fdw_plugin_instance": fdw_plugin_instance,
        "fdw_config_file": fdw_config_file,
        "fdw_schema_mode": fdw_schema_mode,
        "fdw_schema_hash": fdw_schema_hash,
        "semantic_table_count": semantic_table_count,
        "semantic_column_count": semantic_column_count,
        "cache_cleared": cache_cleared,
    }


async def _connection_semantic_counts(
    db: aiosqlite.Connection,
    connection_id: int,
) -> dict[str, int]:
    async with db.execute(
        """
        SELECT
            COUNT(DISTINCT t.id) AS table_count,
            COUNT(c.id) AS column_count
        FROM semantic_tables t
        LEFT JOIN semantic_columns c ON c.semantic_table_id = t.id
        WHERE t.connection_id = ?
        """,
        (connection_id,),
    ) as cur:
        row = await cur.fetchone()

    return {
        "table_count": int(row[0] or 0) if row else 0,
        "column_count": int(row[1] or 0) if row else 0,
    }
