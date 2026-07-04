from typing import Any

from mcp.types import ToolAnnotations

from app.agent.consts import TABLE_SAMPLE_VALUE_MAX_CHARS
from app.cube.projection import (
    TableSampleProjectionInput,
    semantic_response_projector,
)
from app.routers.connection_metadata import sample_connection_table

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="sample_connection_table",
    title="Sample Connection Table",
    description=(
        "Return a compact bounded row sample from one saved connection table. "
        "Column names are returned once and rows are positional arrays. Scalar "
        f"values are capped at {TABLE_SAMPLE_VALUE_MAX_CHARS} characters; truncated "
        "columns are reported explicitly. Use this after get_connection_metadata "
        "to inspect real value shapes, identifier formats, timestamp/currency "
        "values, null examples, and candidate relationship keys before proposing "
        "overlays. Inputs are connection_id, table_name, optional columns, and "
        "limit; raw SQL is not accepted. Google Sheets virtual worksheet tables "
        "are reconstructed from googlesheets_cell."
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

    response = await run_mcp_action(
        sample_connection_table(
            connection_id,
            table_name,
            limit=limit,
            columns=columns,
        )
    )

    # TODO: If full values become necessary, add a separate explicit, narrowly
    # scoped retrieval tool. The default sample response must remain bounded.
    return semantic_response_projector.table_sample(
        TableSampleProjectionInput(response=response)
    )
