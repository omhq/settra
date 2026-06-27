from typing import Any

from mcp.types import ToolAnnotations

from app.routers.connection_metadata import profile_connection_table

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="profile_connection_table",
    title="Profile Connection Table",
    description=(
        "Use this bounded profiler when evaluating candidate dimensions, measures, "
        "identifiers, or cross-application relationship keys. Do not infer a "
        "business relationship solely because fields have similar names; inspect "
        "uniqueness, null rates, example values, and overlap before proposing an "
        "overlay. This tool does not run arbitrary SQL or full-table scans. Google "
        "Sheets virtual worksheet tables are reconstructed from googlesheets_cell."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def profile_table(
    connection_id: int,
    table_name: str,
    limit: int = 500,
    columns: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch a bounded sample-based profile for a saved connection table."""

    return await run_mcp_action(
        profile_connection_table(
            connection_id,
            table_name,
            limit=limit,
            columns=columns,
        )
    )
