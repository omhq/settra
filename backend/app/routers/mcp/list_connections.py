import aiosqlite

from mcp.types import ToolAnnotations

from app.db import DB_PATH
from app.routers.constants import GOOGLE_SHEETS_KEY

from .common import mcp_server


@mcp_server.tool(
    name="list_connections",
    title="List Sheet Data",
    description=(
        "List connected sheet data without secrets, including slugs used "
        "in generated cube names and sql_table schemas. Use this before inspecting "
        "worksheet metadata or drafting sheet-specific semantic overlays."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_connections() -> list[dict[str, object]]:
    """List connected sheet data without secrets."""

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("""
            SELECT id, name, slug, plugin, status, created_at
            FROM connections
            WHERE plugin = ?
            ORDER BY created_at DESC
            """, (GOOGLE_SHEETS_KEY,)) as cur:
            rows = await cur.fetchall()

    return [dict(row) for row in rows]
