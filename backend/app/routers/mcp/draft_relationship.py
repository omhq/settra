from typing import Annotated, Any, Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from app.collection_build_service import relationship_draft

from .common import mcp_server, run_mcp_action
from .management import AppSlug, app_context


@mcp_server.tool(
    name="draft_relationship",
    title="Draft App Relationship",
    description=(
        "Prepare complete App-scoped Cube YAML to create, edit or remove one "
        "relationship without saving it. Review and validate the returned content, "
        "then persist it with create_semantic_overlay or update_semantic_overlay. "
        "For edits or removals, pass the relationship id from list_relationships."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def draft_relationship(
    app: AppSlug,
    source_cube: Annotated[str, Field(min_length=1, max_length=255)],
    target_cube: Annotated[str, Field(max_length=255)] = "",
    source_member: Annotated[str, Field(max_length=255)] = "",
    target_member: Annotated[str, Field(max_length=255)] = "",
    relationship: Literal["many_to_one", "one_to_many", "one_to_one"] = ("many_to_one"),
    source_primary_key: Annotated[str, Field(max_length=255)] = "",
    target_primary_key: Annotated[str, Field(max_length=255)] = "",
    existing_id: Annotated[str | None, Field(max_length=520)] = None,
    remove: bool = False,
) -> dict[str, Any]:
    context = await app_context(app, write=True)

    return await run_mcp_action(
        relationship_draft(
            int(context["id"]),
            source_cube=source_cube,
            target_cube=target_cube,
            source_member=source_member,
            target_member=target_member,
            relationship=relationship,
            source_primary_key=source_primary_key,
            target_primary_key=target_primary_key,
            existing_id=existing_id,
            remove=remove,
        )
    )
