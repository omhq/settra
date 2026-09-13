from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from app.collection_service import collection_cube_names
from app.semantic.overlays import get_overlay_detail

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="get_semantic_overlay",
    title="Get Semantic Overlay",
    description=(
        "Read one hand-authored or generated semantic overlay by path. Returns the "
        "exact Cube YAML once, compact compile status and model names, and manifest "
        "completeness with missing fields. Parsed provenance and full compiled Cube "
        "metadata are omitted because they duplicate the YAML; use get_cube for a "
        "compiled model's compact semantics. Use this before reusing, extending, "
        "debugging, or updating an existing overlay."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def get_semantic_overlay(
    collection: Annotated[
        str,
        Field(description="Selected collection slug from list_collections."),
    ],
    path: str,
) -> dict[str, Any]:
    """Read exact overlay YAML with compact validation status."""

    allowed_names = await run_mcp_action(collection_cube_names(collection))
    return await run_mcp_action(get_overlay_detail(path, allowed_names=allowed_names))
