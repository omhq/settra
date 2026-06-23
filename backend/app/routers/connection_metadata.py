import json

from datetime import datetime, timezone
from typing import Any

import aiofiles
import aiosqlite

from fastapi import HTTPException

from app.agent.metadata import get_schema_with_descriptions
from app.db import DB_PATH
from app.routers.connection_config import read_connection_credentials
from app.routers.constants import (
    DATA_DIR,
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
    credentials = await read_connection_credentials(slug)

    try:
        live_schema = await get_schema_with_descriptions(
            slug,
            use_cache=False,
            refresh_steampipe_cache=True,
            connection_credentials=credentials,
        )
    except Exception as exc:
        raise HTTPException(503, f"metadata refresh failed: {exc}") from exc

    if not live_schema:
        raise HTTPException(
            404, f"No tables found for schema '{slug}' - is the plugin loaded?"
        )

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
