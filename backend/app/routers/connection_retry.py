from typing import Any

import logging

import aiosqlite
import asyncpg

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
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            "SELECT slug, plugin FROM connections WHERE id = ?",
            (connection_id,),
        ) as cur:
            row = await cur.fetchone()

    if not row:
        raise HTTPException(404, "Connection not found")

    slug, plugin = row["slug"], row["plugin"]

    if not (STEAMPIPE_CONFIG_DIR / f"{slug}.spc").exists():
        detail = "Config file missing - edit the connection to re-enter credentials"

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE connections SET status = 'failed' WHERE id = ?",
                (connection_id,),
            )
            await db.commit()

        return {
            "id": connection_id,
            "status": "failed",
            "detail": detail,
            "error": detail,
            "warnings": [],
        }

    creds = await read_connection_credentials(slug)
    connectors = await load_connectors()
    connector = connectors.get(plugin, {})
    creds = normalize_credentials(connector, creds)
    status = "active"
    detail = None
    warnings: list[str] = []

    if not connector:
        status = "failed"
        detail = f"Connector metadata for '{plugin}' was not found."
    else:
        try:
            validate_connection_fields(connector, creds)
        except HTTPException as exc:
            status = "failed"
            detail = str(exc.detail)

    if status == "active" and connector:
        try:
            await validate_provider_credentials(connector, creds)
        except HTTPException as exc:
            status = "failed"
            detail = str(exc.detail)

    fdw_state = None
    fdw_error = None
    fdw_table_count = None
    fdw_plugin = None
    fdw_plugin_instance = None
    fdw_config_file = None

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
            conn_row = await pg.fetchrow(
                """
                SELECT state, error, plugin, plugin_instance, file_name
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
        await db.execute(
            "UPDATE connections SET status = ? WHERE id = ?",
            (status, connection_id),
        )
        await db.commit()

    return {
        "id": connection_id,
        "status": status,
        "detail": detail,
        "error": detail,
        "warnings": list(dict.fromkeys(warnings)),
        "fdw_state": fdw_state,
        "fdw_error": fdw_error,
        "fdw_table_count": fdw_table_count,
        "fdw_plugin": fdw_plugin,
        "fdw_plugin_instance": fdw_plugin_instance,
        "fdw_config_file": fdw_config_file,
    }
