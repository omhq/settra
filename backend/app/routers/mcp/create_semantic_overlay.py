from typing import Any

from mcp.types import ToolAnnotations

from app.cube.model import create_model_file

from .common import (
    generated_overlay_path,
    mcp_server,
    require_complete_overlay_manifest,
    semantic_overlay_write_lock,
    wait_for_compiled_model_names,
)


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
        "tool waits for the declared models to compile."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
async def create_semantic_overlay(path: str, content: str) -> dict[str, Any]:
    """Create a generated Cube YAML overlay without overwriting existing work."""

    async with semantic_overlay_write_lock:
        normalized = generated_overlay_path(path)
        manifest = require_complete_overlay_manifest(content)
        created = create_model_file(normalized, content)
        file = created.get("file") if isinstance(created.get("file"), dict) else {}
        expected_names = [*file.get("cube_names", []), *file.get("view_names", [])]

        return {
            **created,
            "manifest": manifest,
            "cube": await wait_for_compiled_model_names(expected_names),
        }
