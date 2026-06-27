from typing import Any

from mcp.types import ToolAnnotations

from .common import list_overlay_details, mcp_server, run_mcp_action


@mcp_server.tool(
    name="list_semantic_overlays",
    title="List Semantic Overlays",
    description=(
        "List authored semantic overlay files, including overlays that are empty, "
        "partially compiled, or failed to compile and therefore do not appear in "
        "list_cubes. Returns each path, source type, declared models, compile state, "
        "purpose, originating requirement, and manifest completeness. Use this "
        "before creating or extending an overlay to find related or duplicate "
        "semantics. scope may be all, generated, or hand_authored."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_semantic_overlays(scope: str = "all") -> dict[str, Any]:
    """List hand-authored and generated semantic overlays."""

    return await run_mcp_action(list_overlay_details(scope))
