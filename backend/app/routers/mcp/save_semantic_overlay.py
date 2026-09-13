from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from app.collection_service import validate_overlay_for_collection
from app.cube.model import save_model_file
from app.cube.projection import (
    OverlayCreateProjectionInput,
    semantic_response_projector,
)
from app.semantic.overlays import (
    generated_overlay_path,
    parse_overlay_yaml,
    semantic_overlay_write_lock,
    semantic_overlay_manifest,
    wait_for_compiled_model_names,
)

from .common import mcp_server, require_mcp_write_access


@mcp_server.tool(
    name="save_semantic_overlay",
    title="Save Semantic Overlay (Deprecated)",
    description=(
        "Deprecated compatibility upsert for overlays/generated. Prefer "
        "create_semantic_overlay for a new path or update_semantic_overlay for an "
        "existing path so accidental replacement is impossible and updates return "
        "a diff. The same inspection, validation, provenance, and explicit user "
        "approval requirements apply."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def save_semantic_overlay(
    collection: Annotated[
        str,
        Field(description="Selected collection slug from list_collections."),
    ],
    path: str,
    content: str,
) -> dict[str, Any]:
    """Upsert a generated Cube YAML overlay for backward compatibility."""

    require_mcp_write_access()
    async with semantic_overlay_write_lock:
        normalized = generated_overlay_path(path)
        await validate_overlay_for_collection(collection, content)
        saved = save_model_file(normalized, content)
        file = saved.get("file") if isinstance(saved.get("file"), dict) else {}
        expected_names = [*file.get("cube_names", []), *file.get("view_names", [])]
        manifest = semantic_overlay_manifest(parse_overlay_yaml(content))
        compile_status = await wait_for_compiled_model_names(expected_names)

        return semantic_response_projector.overlay_create(
            OverlayCreateProjectionInput(
                created=bool(saved.get("ok")),
                path=str(file.get("path") or normalized),
                model_names=expected_names,
                manifest=manifest,
                compile_status=compile_status,
                deprecated=True,
            )
        )
