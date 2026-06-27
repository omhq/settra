from typing import Any

from mcp.types import ToolAnnotations

from .common import get_overlay_detail, mcp_server, run_mcp_action


@mcp_server.tool(
    name="get_semantic_overlay",
    title="Get Semantic Overlay",
    description=(
        "Read one hand-authored or generated semantic overlay by path. Returns the "
        "exact Cube YAML, normalized meta.settra provenance and evidence manifest, "
        "declared model compile status, and compiled metadata when available. Use "
        "this before reusing, extending, debugging, or updating an existing overlay."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def get_semantic_overlay(path: str) -> dict[str, Any]:
    """Read a semantic overlay and its provenance manifest."""

    return await run_mcp_action(get_overlay_detail(path))
