from typing import Any

from mcp.types import ToolAnnotations

from app.routers.connection_metadata import generate_connection_metadata

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="get_connection_metadata",
    title="Get Connection Metadata",
    description=(
        "Refresh and return non-secret table and column metadata for one saved "
        "connection. Use this to discover live source fields before profiling, "
        "sampling, or drafting an overlay. For Google Sheets, this includes "
        "worksheet tables synthesized from header rows, such as target_revenue."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def get_connection_metadata(connection_id: int) -> dict[str, Any]:
    """Fetch live non-secret schema metadata for a saved connection."""

    return await run_mcp_action(generate_connection_metadata(connection_id))
