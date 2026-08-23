from mcp.types import ToolAnnotations
from pydantic import Field
from typing import Annotated

from app.collection_service import require_collection
from app.db import db_connection
from app.routers.constants import GOOGLE_SHEETS_KEY

from .common import mcp_server, run_mcp_action


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
async def list_connections(
    collection: Annotated[
        str,
        Field(description="Selected collection slug from list_collections."),
    ],
) -> list[dict[str, object]]:
    """List connected sheet data within one collection without secrets."""

    context = await run_mcp_action(require_collection(collection))
    pipe_ids = [int(pipe_id) for pipe_id in context["pipe_ids"]]

    if not pipe_ids:
        return []

    async with db_connection() as db:
        rows = await db.fetch("""
            SELECT id, name, slug, plugin, status, created_at
            FROM connections
            WHERE plugin = $1 AND id = ANY($2::bigint[])
            ORDER BY created_at DESC
            """, GOOGLE_SHEETS_KEY, pipe_ids)

    return [dict(row) for row in rows]
