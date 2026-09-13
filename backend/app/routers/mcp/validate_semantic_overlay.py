from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from app.cube.projection import (
    OverlayValidationProjectionInput,
    semantic_response_projector,
)
from app.semantic.overlay_validation import validate_semantic_overlay_document

from .common import mcp_server, require_mcp_write_access, run_mcp_action


@mcp_server.tool(
    name="validate_semantic_overlay",
    title="Validate Semantic Overlay",
    description=(
        "Validate proposed Cube YAML without leaving it persisted. Use this after "
        "inspect/profile/draft and before asking the user to approve creation or "
        "an update. For replacements, set path to the existing generated overlay "
        "path so the validator can distinguish an update from a duplicate model. "
        "The validator checks declared models, references, and the structured "
        "meta.settra manifest for purpose, requirement, grain, approved "
        "assumptions, relationships, metrics, and evidence. It performs an "
        "ephemeral Cube compile, runs optional Cube REST test_queries, and removes "
        "the validation file. valid reports technical success; ready_to_save also "
        "requires a complete provenance manifest. Successful validation is compact; "
        "compiler and cleanup diagnostics are included when validation fails."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    structured_output=True,
)
async def validate_semantic_overlay(
    collection: Annotated[
        str,
        Field(description="Selected collection slug from list_collections."),
    ],
    content: Annotated[
        str,
        Field(description="Complete Cube YAML overlay content to validate."),
    ],
    path: Annotated[
        str,
        Field(
            description=(
                "Proposed generated overlay path. For updates, pass the existing "
                "generated overlay path exactly; using a temporary path for a "
                "replacement will correctly fail with DUPLICATE_MODEL_NAME."
            )
        ),
    ] = "generated/validation.yaml",
    test_queries: Annotated[
        list[dict[str, Any]] | None,
        Field(description="Optional Cube REST query objects to run after compile."),
    ] = None,
) -> dict[str, Any]:
    """Expose semantic overlay validation through MCP."""

    require_mcp_write_access()
    result = await run_mcp_action(
        validate_semantic_overlay_document(
            collection=collection,
            content=content,
            path=path,
            test_queries=test_queries,
        )
    )
    return semantic_response_projector.overlay_validation(
        OverlayValidationProjectionInput(result=result)
    )
