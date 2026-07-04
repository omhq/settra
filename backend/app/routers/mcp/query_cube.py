from typing import Any

from mcp.types import ToolAnnotations

from app.cube.query import (
    bounded_mcp_cube_query,
    execute_cube_query_payload,
    normalize_cube_query_payload,
)
from app.cube.projection import (
    QueryResultProjectionInput,
    semantic_response_projector,
)

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="query_cube",
    title="Query Cube",
    description=(
        "Execute a bounded Cube REST query against existing compiled semantics. "
        "Pass Cube query JSON using measures, dimensions, filters, timeDimensions, "
        "segments, limit, offset, order, and timezone. Results contain one data "
        "array plus row_count and an optional total; Cube execution internals are "
        "omitted. limit defaults to 100 rows and is capped at 500 per query. Use "
        "this to answer questions and verify saved overlays; raw SQL is not accepted."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def query_cube(query: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    """Execute a Cube semantic query."""

    return await run_mcp_action(_execute_bounded_cube_query(query))


async def _execute_bounded_cube_query(
    query: dict[str, Any] | list[dict[str, Any]],
) -> dict[str, Any]:
    normalized_query = normalize_cube_query_payload({"query": query})
    bounded_query = bounded_mcp_cube_query(normalized_query)
    response = await execute_cube_query_payload({"query": bounded_query})

    return semantic_response_projector.query_result(
        QueryResultProjectionInput(response=response)
    )
