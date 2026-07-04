from typing import Any

from mcp.types import ToolAnnotations

from app.cube.query import cube_by_name

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="get_cube",
    title="Get Cube",
    description=(
        "Fetch one compact semantic definition for a compiled cube or view. The "
        "response merges authored Cube YAML with compiled availability and keeps "
        "member names, types, meaningful descriptions, SQL, filters, references, "
        "relationships, source table or SQL, connection context, and non-default "
        "access behavior. Repeated Cube prefixes, duplicate source definitions, "
        "empty collections, and default UI metadata are omitted. Use this before "
        "creating overlays. When source.path identifies an overlay, use "
        "get_semantic_overlay for its full assumptions and evidence."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def get_cube(name: str) -> dict[str, Any]:
    """Fetch compact semantics for a single cube or view."""

    if not name.strip():
        raise ValueError("name is required")

    return await run_mcp_action(cube_by_name(name))
