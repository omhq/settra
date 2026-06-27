from typing import Any

from mcp.types import ToolAnnotations

from app.cube.query import execute_cube_query_payload

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="query_cube",
    title="Query Cube",
    description=(
        "Execute a Cube REST query against existing compiled semantics. Pass Cube "
        "query JSON using measures, dimensions, filters, timeDimensions, segments, "
        "limit, offset, order, and timezone. Use this to answer questions and "
        "verify saved overlays; raw SQL is not accepted."
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

    return await run_mcp_action(execute_cube_query_payload({"query": query}))
