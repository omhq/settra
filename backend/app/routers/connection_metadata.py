import json

from datetime import datetime, timezone
from typing import Any

import aiofiles
import aiosqlite
import asyncpg

from fastapi import HTTPException

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

    metadata = {
        "connection_id": connection_id,
        "slug": slug,
        "plugin": plugin,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tables": {
            table_name: {
                "columns": columns,
                "ddl": _ddl(slug, table_name, columns),
            }
            for table_name, columns in sorted(tables_map.items())
        },
    }
    metadata_dir = DATA_DIR / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    out_path = metadata_dir / f"{slug}.json"

    async with aiofiles.open(out_path, "w") as f:
        await f.write(json.dumps(metadata, indent=2))

    return metadata


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
