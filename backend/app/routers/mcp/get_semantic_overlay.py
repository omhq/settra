from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from app.collection_service import collection_overlay_prefix, require_collection
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
    app: Annotated[
        str,
        Field(description="Selected artifact slug returned by list_apps."),
    ],
    path: str,
) -> dict[str, Any]:
    """Read exact overlay YAML with compact validation status."""

    context = await run_mcp_action(require_collection(app))

    return await run_mcp_action(
        get_overlay_detail(
            path,
            allowed_names=set(context["cube_names"]),
            owned_prefix=collection_overlay_prefix(context["id"]),
        )
    )
