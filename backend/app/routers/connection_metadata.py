import json

from datetime import datetime, timezone
from typing import Any

import aiofiles
import aiosqlite
import asyncpg

from fastapi import HTTPException

from app.agent.metadata import refresh_steampipe_connection_cache
from app.db import DB_PATH
from app.routers.constants import (
    DATA_DIR,
    STEAMPIPE_DB_PASSWORD,
    STEAMPIPE_HOST,
    STEAMPIPE_PORT,
)


async def generate_connection_metadata(connection_id: int) -> dict[str, Any]:
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

    try:
        pg = await asyncpg.connect(
            host=STEAMPIPE_HOST,
            port=STEAMPIPE_PORT,
            database="steampipe",
            user="steampipe",
            password=STEAMPIPE_DB_PASSWORD,
            timeout=10,
        )
    except Exception as exc:
        raise HTTPException(503, f"Cannot connect to steampipe: {exc}") from exc

    try:
        await refresh_steampipe_connection_cache(pg, slug)

        tables = await pg.fetch(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = $1
            ORDER BY table_name
            """,
            slug,
        )

        columns = await pg.fetch(
            """
            SELECT
                c.table_name,
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.ordinal_position,
                pg_catalog.col_description(
                    (quote_ident($1) || '.' || quote_ident(c.table_name))::regclass,
                    c.ordinal_position
                ) AS description
            FROM information_schema.columns c
            WHERE c.table_schema = $1
            ORDER BY c.table_name, c.ordinal_position
            """,
            slug,
        )
    except Exception as exc:
        raise HTTPException(503, f"steampipe query failed: {exc}") from exc
    finally:
        await pg.close()

    if not tables:
        raise HTTPException(
            404, f"No tables found for schema '{slug}' - is the plugin loaded?"
        )

    tables_map: dict[str, list] = {row["table_name"]: [] for row in tables}

    for column in columns:
        table_name = column["table_name"]
        column_meta: dict = {
            "name": column["column_name"],
            "type": column["data_type"],
            "nullable": column["is_nullable"] == "YES",
        }

        if column["description"]:
            column_meta["description"] = column["description"]

        tables_map.setdefault(table_name, []).append(column_meta)

    live_schema = [
        {
            "name": table_name,
            "columns": columns,
        }
        for table_name, columns in sorted(tables_map.items())
    ]

    return await write_connection_metadata_cache(
        connection_id=connection_id,
        slug=slug,
        plugin=plugin,
        live_schema=live_schema,
    )


async def write_connection_metadata_cache(
    *,
    connection_id: int,
    slug: str,
    plugin: str,
    live_schema: list[dict[str, Any]],
) -> dict[str, Any]:
    metadata = {
        "connection_id": connection_id,
        "slug": slug,
        "plugin": plugin,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tables": {
            table_name: {
                **(
                    {"description": str(table.get("description") or "")}
                    if table.get("description")
                    else {}
                ),
                **(
                    {"metadata": table.get("metadata")}
                    if isinstance(table.get("metadata"), dict)
                    else {}
                ),
                "columns": columns,
                "ddl": _ddl(slug, table_name, columns),
            }
            for table_name, table, columns in _metadata_tables(live_schema)
        },
    }
    metadata_dir = DATA_DIR / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    out_path = metadata_dir / f"{slug}.json"

    async with aiofiles.open(out_path, "w") as f:
        await f.write(json.dumps(metadata, indent=2))

    return metadata


def _metadata_tables(
    live_schema: list[dict[str, Any]],
) -> list[tuple[str, dict[str, Any], list[dict[str, Any]]]]:
    tables = []

    for table in live_schema:
        table_name = str(table.get("name") or "")

        if not table_name:
            continue

        raw_columns = table.get("columns", [])
        columns = raw_columns if isinstance(raw_columns, list) else []

        tables.append((table_name, table, columns))

    return sorted(tables, key=lambda item: item[0])


def _ddl(schema: str, table_name: str, columns: list) -> str:
    lines = []

    for column in columns:
        line = f"  {column['name']} {column['type'].upper()}"

        if not column["nullable"]:
            line += " NOT NULL"
        if column.get("description"):
            line += f"  -- {column['description']}"

        lines.append(line)

    return f"CREATE TABLE {schema}.{table_name} (\n" + ",\n".join(lines) + "\n);"
