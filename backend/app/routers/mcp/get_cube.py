from typing import Any

from mcp.types import ToolAnnotations

from app.cube.query import cube_by_name

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="get_cube",
    title="Get Cube",
    description=(
        "Fetch full Cube metadata and source definition for one compiled cube or "
        "view. Use this before creating overlays to inspect available measures, "
        "dimensions, segments, joins, source SQL, source type, and connection "
        "context. Use get_semantic_overlay when source_path points to an overlay "
        "and you need its authored YAML, assumptions, or evidence."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def get_cube(name: str) -> dict[str, Any]:
    """Fetch metadata for a single cube or view."""

    if not name.strip():
        raise ValueError("name is required")

    return await run_mcp_action(cube_by_name(name))
