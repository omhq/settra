from typing import Any

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
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE connections SET status = 'failed' WHERE id = ?",
                (connection_id,),
            )
            await db.commit()

        return {
            "id": connection_id,
            "status": "failed",
            "detail": (
                "Config file missing - edit the connection to re-enter credentials"
            ),
        }

    creds = await read_connection_credentials(slug)
    connectors = await load_connectors()
    connector = connectors.get(plugin, {})
    creds = normalize_credentials(connector, creds)
    status = "active"
    detail = None

    if connector:
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
                SELECT state, error
                FROM steampipe_internal.steampipe_connection
                WHERE name = $1
                """,
                slug,
            )

            if conn_row:
                fdw_state = conn_row["state"]
                fdw_error = conn_row["error"] or None

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

            test_table = connector.get("test_table")

            if status == "active" and test_table:
                try:
                    test_sql = (
                        f"SELECT 1 FROM {quote_ident(slug)}."
                        f"{quote_ident(str(test_table))} LIMIT 1"
                    )
                    await pg.fetchrow(test_sql)
                except Exception as exc:
                    status = "failed"
                    fdw_error = str(exc)
                    detail = f"FDW query failed: {exc}"
        finally:
            await pg.close()
    except Exception:
        fdw_state = "unreachable"

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
        "fdw_state": fdw_state,
        "fdw_error": fdw_error,
        "fdw_table_count": fdw_table_count,
    }
