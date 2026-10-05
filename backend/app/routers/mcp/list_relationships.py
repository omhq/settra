from typing import Any

from mcp.types import ToolAnnotations

from app.relationship_service import get_collection_relationships

from .common import mcp_server, run_mcp_action
from .management import ArtifactSlug, artifact_context


@mcp_server.tool(
    name="list_relationships",
    title="List Artifact Relationships",
    description=(
        "List authored Cube joins visible in one artifact with structural validity, "
        "declared cardinality, semantic members, physical-key resolution and repair "
        "issues. This does not run snapshot integrity checks."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_relationships(artifact: ArtifactSlug) -> dict[str, Any]:
    context = await artifact_context(artifact)

    return await run_mcp_action(get_collection_relationships(int(context["id"])))
