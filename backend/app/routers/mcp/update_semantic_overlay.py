import difflib

from typing import Any

from mcp.types import ToolAnnotations

from app.cube.model import update_model_file

from .common import (
    generated_overlay_path,
    mcp_server,
    parse_overlay_yaml,
    require_complete_overlay_manifest,
    semantic_overlay_write_lock,
    wait_for_compiled_model_names,
    wait_for_removed_model_names,
)


@mcp_server.tool(
    name="update_semantic_overlay",
    title="Update Semantic Overlay",
    description=(
        "Update an existing generated semantic overlay and fail if the path does "
        "not exist. Use get_semantic_overlay first, preserve approved provenance, "
        "then validate the complete replacement YAML with "
        "validate_semantic_overlay and obtain explicit user approval. Returns a "
        "unified diff, updated manifest status, compile status, and removal status "
        "for model names deleted by the edit. Hand-authored overlays cannot be "
        "modified by this tool."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def update_semantic_overlay(path: str, content: str) -> dict[str, Any]:
    """Replace an existing generated overlay and report the authored diff."""

    async with semantic_overlay_write_lock:
        normalized = generated_overlay_path(path)
        manifest = require_complete_overlay_manifest(content)
        updated = update_model_file(normalized, content)
        previous_content = str(updated.pop("previous_content"))
        previous = parse_overlay_yaml(previous_content)
        file = updated.get("file") if isinstance(updated.get("file"), dict) else {}
        expected_names = [*file.get("cube_names", []), *file.get("view_names", [])]
        previous_names = _model_names(previous)
        removed_names = sorted(set(previous_names) - set(expected_names))
        diff = "\n".join(
            difflib.unified_diff(
                previous_content.splitlines(),
                content.splitlines(),
                fromfile=normalized,
                tofile=normalized,
                lineterm="",
            )
        )
        result = {
            **updated,
            "diff": diff,
            "manifest": manifest,
            "cube": await wait_for_compiled_model_names(expected_names),
        }

        if removed_names:
            result["removed_models"] = await wait_for_removed_model_names(removed_names)

        return result


def _model_names(parsed: dict[str, Any]) -> list[str]:
    names: list[str] = []

    for key in ("cubes", "views"):
        items = parsed.get(key)

        if not isinstance(items, list):
            continue

        names.extend(
            item["name"]
            for item in items
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        )

    return names
