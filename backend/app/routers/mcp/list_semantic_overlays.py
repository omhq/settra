from typing import Any, Literal

from mcp.types import ToolAnnotations
from pydantic import Field
from typing import Annotated

from app.collection_service import collection_overlay_prefix, require_collection
from app.semantic.overlays import list_overlay_details

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="list_semantic_overlays",
    title="List Semantic Overlays",
    description=(
        "List authored semantic overlay files, including overlays that are empty, "
        "partially compiled, or failed to compile and therefore do not appear in "
        "list_cubes. Returns only each path, declared model names, compile status, "
        "manifest status, and purpose. Exact YAML and detailed provenance belong in "
        "get_semantic_overlay. Use this before creating or extending an overlay to "
        "find related or duplicate semantics. scope may be all, generated, or "
        "hand_authored."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_semantic_overlays(
    artifact: Annotated[
        str,
        Field(description="Selected artifact slug returned by list_artifacts."),
    ],
    scope: Literal["all", "generated", "hand_authored"] = "all",
) -> dict[str, Any]:
    """List compact summaries of hand-authored and generated overlays."""

    context = await run_mcp_action(require_collection(artifact))

    return await run_mcp_action(
        list_overlay_details(
            scope,
            allowed_names=set(context["cube_names"]),
            owned_prefix=collection_overlay_prefix(context["id"]),
        )
    )
