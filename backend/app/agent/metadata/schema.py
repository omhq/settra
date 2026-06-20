import json

from typing import Any

import aiofiles
import asyncpg

from app.agent.consts import (
    DATA_DIR,
    STEAMPIPE_DB_PASSWORD,
    STEAMPIPE_HOST,
    STEAMPIPE_PORT,
)
from app.agent.metadata.google_sheets import add_google_sheets_worksheet_tables
from app.agent.metadata.utils import quote_ident


async def get_schema_with_descriptions(
    schema: str,
    *,
    use_cache: bool = True,
    refresh_steampipe_cache: bool = False,
    connection_credentials: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    metadata = (
        await _get_cached_metadata(schema)
        if use_cache and not refresh_steampipe_cache
        else []
    )

    if metadata:
        return metadata

    pg = await asyncpg.connect(
        host=STEAMPIPE_HOST,
        port=STEAMPIPE_PORT,
        database="steampipe",
        user="steampipe",
        password=STEAMPIPE_DB_PASSWORD,
        timeout=10,
    )

    try:
        if refresh_steampipe_cache:
            await refresh_steampipe_connection_cache(pg, schema)

        table_rows = await pg.fetch(
            """
            SELECT
                t.table_name,
                pg_catalog.obj_description(
                    (quote_ident($1) || '.' || quote_ident(t.table_name))::regclass,
                    'pg_class'
                ) AS table_description
            FROM information_schema.tables t
            WHERE t.table_schema = $1
            ORDER BY t.table_name
            """,
            schema,
        )

        rows = await pg.fetch(
            """
            SELECT
                c.table_name,
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.ordinal_position,
                pg_catalog.obj_description(
                    (quote_ident($1) || '.' || quote_ident(c.table_name))::regclass,
                    'pg_class'
                ) AS table_description,
                pg_catalog.col_description(
                    (quote_ident($1) || '.' || quote_ident(c.table_name))::regclass,
                    c.ordinal_position
                ) AS description
            FROM information_schema.columns c
            WHERE c.table_schema = $1
            ORDER BY c.table_name, c.ordinal_position
            """,
            schema,
        )

        tables: dict[str, dict[str, Any]] = {}

        for row in table_rows:
            tables[row["table_name"]] = {
                "name": row["table_name"],
                "description": row["table_description"] or "",
                "columns": [],
            }

        for row in rows:
            table = tables.setdefault(
                row["table_name"],
                {
                    "name": row["table_name"],
                    "description": row["table_description"] or "",
                    "columns": [],
                },
            )

            table["columns"].append(
                {
                    "name": row["column_name"],
                    "type": row["data_type"],
                    "nullable": row["is_nullable"] == "YES",
                    "description": row["description"] or "",
                }
            )

        await add_google_sheets_worksheet_tables(
            pg,
            schema,
            tables,
            connection_credentials=connection_credentials,
        )

        return list(tables.values())
    finally:
        await pg.close()


async def refresh_steampipe_connection_cache(
    pg: asyncpg.Connection,
    schema: str,
) -> None:
    await pg.fetchrow(
        "SELECT steampipe_internal.meta_connection_cache_clear($1)",
        schema,
    )


async def _get_cached_metadata(schema: str) -> list[dict[str, Any]]:
    path = DATA_DIR / "metadata" / f"{schema}.json"
    tables = []

    if not path.exists():
        return []

    async with aiofiles.open(path) as f:
        data = json.loads(await f.read())

    for table_name, table_meta in data.get("tables", {}).items():
        tables.append(
            {
                "name": table_name,
                "description": table_meta.get("description", ""),
                "columns": table_meta.get("columns", []),
                "ddl": table_meta.get("ddl", ""),
                "metadata": table_meta.get("metadata", {}),
            }
        )

    return tables
