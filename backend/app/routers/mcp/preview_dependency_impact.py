from typing import Annotated, Any, Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from app.dependency_impact_service import (
    preview_model_deletion,
    preview_source_removal,
    preview_source_schema_change,
)

from .common import mcp_server, run_mcp_action
from .management import AppSlug, app_context, required_text


@mcp_server.tool(
    name="preview_dependency_impact",
    title="Preview Dependency Impact",
    description=(
        "Preview affected semantic models, relationships, artifact graph steps and named "
        "results before deleting an artifact model, removing a source from "
        "an artifact, or changing a source schema. Model deletion and artifact source removal "
        "are exact previews. Source schema changes are conservative until the next "
        "Drive schema is known. This tool never changes data."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def preview_dependency_impact(
    action: Literal["delete_model", "remove_source", "change_source_schema"],
    app: AppSlug | None = None,
    path: Annotated[
        str | None,
        Field(
            max_length=500,
            description="Artifact model path required for delete_model.",
        ),
    ] = None,
    connection_id: Annotated[
        int | None,
        Field(gt=0, description="Source ID required for source actions."),
    ] = None,
) -> dict[str, Any]:
    if action == "delete_model":
        context = await app_context(
            required_text(app, "app", action),
        )

        return await run_mcp_action(
            preview_model_deletion(
                int(context["id"]),
                required_text(path, "path", action),
            )
        )

    if connection_id is None:
        raise ValueError(f"connection_id is required for {action}")

    if action == "remove_source":
        context = await app_context(
            required_text(app, "app", action),
        )

        return await run_mcp_action(
            preview_source_removal(int(context["id"]), connection_id)
        )

    context = await app_context(app) if app is not None else None

    return await run_mcp_action(
        preview_source_schema_change(
            connection_id,
            collection_id=int(context["id"]) if context is not None else None,
        )
    )
