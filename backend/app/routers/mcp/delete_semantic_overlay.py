from typing import Any

from mcp.types import ToolAnnotations

from app.collection_build_service import remove_collection_overlay

from .common import mcp_server, run_mcp_action
from .management import AppSlug, app_context


@mcp_server.tool(
    name="delete_semantic_overlay",
    title="Delete App Semantic Overlay",
    description=(
        "Delete a generated semantic overlay only after the user explicitly "
        "approves cleanup or removal. Use preview_dependency_impact first, then "
        "list_semantic_overlays and get_semantic_overlay to confirm its path, "
        "purpose and provenance. "
        "The file must be writable and owned by the selected App; source-generated, "
        "shared read-only and other-App models cannot be deleted."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
async def delete_semantic_overlay(
    collection: AppSlug,
    path: str,
) -> dict[str, Any]:
    """Delete one writable semantic overlay owned by the selected App."""

    app = await app_context(collection, write=True)

    return await run_mcp_action(remove_collection_overlay(int(app["id"]), path))
