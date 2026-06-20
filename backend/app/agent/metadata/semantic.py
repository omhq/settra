import json

from typing import Any

import aiosqlite

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
