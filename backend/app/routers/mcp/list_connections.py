import aiosqlite

from mcp.types import ToolAnnotations

from app.db import DB_PATH

from .common import mcp_server


@mcp_server.tool(
    name="list_connections",
    title="List Connections",
    description=(
        "List saved Settra connections without secrets, including connection slugs "
        "used in generated cube names and sql_table schemas. Use this before "
        "inspecting connection metadata or drafting user-specific semantic overlays."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_connections() -> list[dict[str, object]]:
    """List non-secret saved connections."""

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("""
            SELECT id, name, slug, plugin, status, created_at
            FROM connections
            ORDER BY created_at DESC
            """) as cur:
            rows = await cur.fetchall()

    return [dict(row) for row in rows]
