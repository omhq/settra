from typing import Any

from mcp.types import ToolAnnotations

from app.collection_build_service import write_collection_overlay
from app.cube.projection import (
    OverlayCreateProjectionInput,
    semantic_response_projector,
)
from app.semantic.overlays import (
    require_complete_overlay_manifest,
)

from .common import mcp_server, run_mcp_action
from .management import AppSlug, app_context


@mcp_server.tool(
    name="create_semantic_overlay",
    title="Create Semantic Overlay",
    description=(
        "Create a new user-approved semantic overlay under overlays/generated and "
        "fail if the path already exists. Use only after inspecting relevant "
        "connections, cubes, source fields, and existing overlays, then running "
        "validate_semantic_overlay. Record purpose, originating user requirement, "
        "grain, approved assumptions, relationships, metric definitions, evidence, "
        "and validation results under each model's meta.settra. After creation this "
        "tool waits for the declared models to compile and returns a compact status; "
        "compiler diagnostics are included only when compilation is incomplete."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
async def create_semantic_overlay(
    app: AppSlug,
    path: str,
    content: str,
) -> dict[str, Any]:
    """Create a generated Cube YAML overlay without overwriting existing work."""

    context = await app_context(app, write=True)
    created = await run_mcp_action(
        write_collection_overlay(
            int(context["id"]),
            path=path,
            content=content,
            create=True,
        )
    )
    file = created.get("file") if isinstance(created.get("file"), dict) else {}
    expected_names = [*file.get("cube_names", []), *file.get("view_names", [])]

    return semantic_response_projector.overlay_create(
        OverlayCreateProjectionInput(
            created=bool(created.get("created")),
            path=str(file.get("path") or path),
            model_names=expected_names,
            manifest=require_complete_overlay_manifest(content),
            compile_status=created["cube"],
        )
    )
