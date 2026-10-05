from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from app.collection_service import create_collection

from .common import require_mcp_write_access, mcp_server, run_mcp_action
from .management import artifact_projection


@mcp_server.tool(
    name="create_artifact",
    title="Create Data Artifact",
    description=(
        "Create an artifact and optionally add existing Google Drive pipes by ID. "
        "Use list_connections to discover pipe IDs. The artifact owns its instructions, "
        "semantic models, relationships and an executable artifact graph."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
async def create_artifact(
    name: Annotated[str, Field(min_length=1, max_length=120)],
    description: Annotated[str, Field(max_length=1000)] = "",
    agent_instructions: Annotated[str, Field(max_length=10000)] = "",
    pipe_ids: Annotated[list[int] | None, Field(max_length=100)] = None,
) -> dict[str, Any]:
    require_mcp_write_access()
    artifact = await run_mcp_action(
        create_collection(
            name=name,
            description=description,
            agent_instructions=agent_instructions,
            pipe_ids=pipe_ids or [],
        )
    )
    return artifact_projection(artifact)
