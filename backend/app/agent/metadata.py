import json

from typing import Any

import aiofiles
import aiosqlite
import asyncpg

from app.agent.consts import (
    DATA_DIR,
    STEAMPIPE_DB_PASSWORD,
    STEAMPIPE_HOST,
    STEAMPIPE_PORT,
)
from app.common.config import DB_PATH


async def get_semantic_metadata(plugin: str) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            """
            SELECT table_name, content
            FROM semantic_metadata
            WHERE plugin = ?
            ORDER BY table_name
            """,
            (plugin,),
        ) as cur:
            rows = await cur.fetchall()

    metadata: dict[str, Any] = {}

    for row in rows:
        metadata[row["table_name"]] = json.loads(row["content"])

    return metadata


async def get_schema_with_descriptions(schema: str) -> list[dict[str, Any]]:
    metadata = await _get_cached_metadata(schema)

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
    finally:
        await pg.close()

    tables: dict[str, dict[str, Any]] = {}

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

    return list(tables.values())


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
            }
        )

    return tables
