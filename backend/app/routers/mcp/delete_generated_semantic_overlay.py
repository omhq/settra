from typing import Any

from mcp.types import ToolAnnotations

from app.cube.model import delete_generated_model_file

from .common import (
    generated_overlay_path,
    mcp_server,
    semantic_overlay_write_lock,
    wait_for_removed_model_names,
)


@mcp_server.tool(
    name="delete_generated_semantic_overlay",
    title="Delete Generated Semantic Overlay",
    description=(
        "Delete a generated semantic overlay only after the user explicitly "
        "approves cleanup or removal. Use list_semantic_overlays or "
        "get_semantic_overlay first to confirm the path, purpose, dependencies, and "
        "provenance. This cannot delete bundled connector templates, generated "
        "connection models, or hand-authored overlays."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
async def delete_generated_semantic_overlay(path: str) -> dict[str, Any]:
    """Delete a generated Cube YAML overlay file."""

    async with semantic_overlay_write_lock:
        normalized = generated_overlay_path(path)
        deleted = delete_generated_model_file(normalized)
        file = (
            deleted.get("deleted") if isinstance(deleted.get("deleted"), dict) else {}
        )
        removed_names = [*file.get("cube_names", []), *file.get("view_names", [])]

        return {
            **deleted,
            "cube": await wait_for_removed_model_names(removed_names),
        }
