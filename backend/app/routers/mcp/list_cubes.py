from typing import Any

from mcp.types import ToolAnnotations

from app.cube.query import semantic_catalog

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="list_cubes",
    title="List Cubes",
    description=(
        "List compiled Cube cubes, views, measures, dimensions, segments, joins, "
        "and source labels exposed by Settra. Use this first to find existing "
        "governed semantics before proposing or drafting overlays. Search accepts "
        "natural phrases such as 'stripe sandbox customer' and generated names. "
        "Use list_semantic_overlays when you need authored overlay provenance or "
        "models that failed to compile."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_cubes(search: str | None = None) -> dict[str, Any]:
    """List compiled Cube semantic metadata."""

    return await run_mcp_action(semantic_catalog(search=search))
