from typing import Any

from mcp.types import ToolAnnotations

from app.cube.model import save_model_file

from .common import (
    generated_overlay_path,
    mcp_server,
    parse_overlay_yaml,
    semantic_overlay_write_lock,
    semantic_overlay_manifest,
    wait_for_compiled_model_names,
)


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
async def save_semantic_overlay(path: str, content: str) -> dict[str, Any]:
    """Upsert a generated Cube YAML overlay for backward compatibility."""

    async with semantic_overlay_write_lock:
        normalized = generated_overlay_path(path)
        saved = save_model_file(normalized, content)
        file = saved.get("file") if isinstance(saved.get("file"), dict) else {}
        expected_names = [*file.get("cube_names", []), *file.get("view_names", [])]

        return {
            **saved,
            "deprecated": True,
            "manifest": semantic_overlay_manifest(parse_overlay_yaml(content)),
            "cube": await wait_for_compiled_model_names(expected_names),
        }
