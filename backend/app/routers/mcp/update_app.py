from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from app.collection_service import update_collection

from .common import mcp_server, run_mcp_action
from .management import AppSlug, app_context, app_projection


@mcp_server.tool(
    name="update_app",
    title="Update Data Artifact",
    description=(
        "Update an artifact's name, description, agent instructions, or pipe membership. "
        "Omitted fields retain their current values. pipe_ids replaces the complete "
        "membership list, so inspect get_app_context before changing it. "
        "Call preview_dependency_impact before removing any source ID."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def update_app(
    app: AppSlug,
    name: Annotated[str | None, Field(min_length=1, max_length=120)] = None,
    description: Annotated[str | None, Field(max_length=1000)] = None,
    agent_instructions: Annotated[str | None, Field(max_length=10000)] = None,
    pipe_ids: Annotated[list[int] | None, Field(max_length=100)] = None,
) -> dict[str, Any]:
    current = await app_context(app, write=True)
    updated = await run_mcp_action(
        update_collection(
            int(current["id"]),
            name=name if name is not None else str(current["name"]),
            description=(
                description
                if description is not None
                else str(current.get("description") or "")
            ),
            agent_instructions=(
                agent_instructions
                if agent_instructions is not None
                else str(current.get("agent_instructions") or "")
            ),
            pipe_ids=(
                pipe_ids
                if pipe_ids is not None
                else [int(value) for value in current.get("pipe_ids", [])]
            ),
        )
    )
    return app_projection(updated)
