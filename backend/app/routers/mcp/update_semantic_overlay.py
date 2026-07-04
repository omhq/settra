import difflib

from typing import Any

from mcp.types import ToolAnnotations

from app.cube.model import update_model_file
from app.cube.projection import (
    OverlayUpdateProjectionInput,
    semantic_response_projector,
)

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
        "validate_semantic_overlay and obtain explicit user approval. Returns model "
        "changes, compile status, and a compact diff summary. Set include_diff=true "
        "to return the full unified diff. Hand-authored overlays cannot be modified "
        "by this tool."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def update_semantic_overlay(
    path: str,
    content: str,
    include_diff: bool = False,
) -> dict[str, Any]:
    """Replace an existing generated overlay and report the authored diff."""

    async with semantic_overlay_write_lock:
        normalized = generated_overlay_path(path)
        require_complete_overlay_manifest(content)
        updated = update_model_file(normalized, content)
        previous_content = str(updated.pop("previous_content"))
        previous = parse_overlay_yaml(previous_content)
        current = parse_overlay_yaml(content)
        file = updated.get("file") if isinstance(updated.get("file"), dict) else {}
        expected_names = [*file.get("cube_names", []), *file.get("view_names", [])]
        previous_models = _model_definitions(previous)
        current_models = _model_definitions(current)
        previous_names = set(previous_models)
        current_names = set(current_models)
        added_names = sorted(current_names - previous_names)
        removed_names = sorted(previous_names - current_names)
        changed_names = sorted(
            name
            for name in previous_names & current_names
            if previous_models[name] != current_models[name]
        )
        diff = "\n".join(
            difflib.unified_diff(
                previous_content.splitlines(),
                content.splitlines(),
                fromfile=normalized,
                tofile=normalized,
                lineterm="",
            )
        )
        compile_status = await wait_for_compiled_model_names(expected_names)
        removal_status = None

        if removed_names:
            removal_status = await wait_for_removed_model_names(removed_names)

        return semantic_response_projector.overlay_update(
            OverlayUpdateProjectionInput(
                updated=bool(updated.get("updated")),
                path=str(file.get("path") or normalized),
                models_added=added_names,
                models_changed=changed_names,
                models_removed=removed_names,
                compile_status=compile_status,
                diff=diff,
                include_diff=include_diff,
                removal_status=removal_status,
            )
        )


def _model_definitions(parsed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    definitions: dict[str, dict[str, Any]] = {}

    for key in ("cubes", "views"):
        items = parsed.get(key)

        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue

            definitions[item["name"]] = {
                "type": key.removesuffix("s"),
                "definition": item,
            }

    return definitions
