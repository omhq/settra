import difflib

from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from app.collection_build_service import write_collection_overlay
from app.cube.projection import (
    OverlayUpdateProjectionInput,
    semantic_response_projector,
)
from app.semantic.overlays import (
    parse_overlay_yaml,
)

from .common import mcp_server, run_mcp_action
from .management import ArtifactSlug, artifact_context


@mcp_server.tool(
    name="update_semantic_overlay",
    title="Update Semantic Overlay",
    description=(
        "Update an existing generated semantic overlay and fail if the path does "
        "not exist. Use get_semantic_overlay first, preserve approved provenance, "
        "and pass its exact content as expected_content so concurrent edits cannot "
        "be overwritten. Then validate the complete replacement YAML with "
        "validate_semantic_overlay using this same path, and obtain explicit user "
        "approval. Returns model changes, compile status, and a compact diff "
        "summary. Set include_diff=true to return the full unified diff. "
        "Hand-authored overlays cannot be modified by this tool."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def update_semantic_overlay(
    artifact: ArtifactSlug,
    path: str,
    content: str,
    expected_content: Annotated[
        str,
        Field(description="Exact content returned by get_semantic_overlay."),
    ],
    include_diff: bool = False,
) -> dict[str, Any]:
    """Replace an existing generated overlay and report the authored diff."""

    context = await artifact_context(artifact, write=True)
    updated = await run_mcp_action(
        write_collection_overlay(
            int(context["id"]),
            path=path,
            content=content,
            create=False,
            expected_content=expected_content,
        )
    )
    previous = parse_overlay_yaml(expected_content)
    current = parse_overlay_yaml(content)
    file = updated.get("file") if isinstance(updated.get("file"), dict) else {}
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
            expected_content.splitlines(),
            content.splitlines(),
            fromfile=path,
            tofile=path,
            lineterm="",
        )
    )

    return semantic_response_projector.overlay_update(
        OverlayUpdateProjectionInput(
            updated=bool(updated.get("updated")),
            path=str(file.get("path") or path),
            models_added=added_names,
            models_changed=changed_names,
            models_removed=removed_names,
            compile_status=updated["cube"],
            diff=diff,
            include_diff=include_diff,
            removal_status=updated.get("removal"),
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
