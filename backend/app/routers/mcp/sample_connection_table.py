from typing import Any

from mcp.types import ToolAnnotations

from app.routers.connection_metadata import sample_connection_table

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="sample_connection_table",
    title="Sample Connection Table",
    description=(
        "Return a small bounded row sample from one saved connection table. Use "
        "this after get_connection_metadata to inspect real value shapes, identifier "
        "formats, timestamp/currency values, null examples, and candidate "
        "relationship keys before proposing overlays. Inputs are connection_id, "
        "table_name, optional columns, and limit; raw SQL is not accepted. Google "
        "Sheets virtual worksheet tables are reconstructed from googlesheets_cell."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def sample_table(
    connection_id: int,
    table_name: str,
    limit: int = 3,
    columns: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch a bounded sample from a saved connection table."""

    return await run_mcp_action(
        sample_connection_table(
            connection_id,
            table_name,
            limit=limit,
            columns=columns,
        )
    )
