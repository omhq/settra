from typing import Any

from mcp.types import ToolAnnotations

from app.relationship_service import validate_collection_relationships

from .common import mcp_server, run_mcp_action
from .management import ArtifactSlug, artifact_context


@mcp_server.tool(
    name="validate_relationships",
    title="Validate Artifact Relationships",
    description=(
        "Run bounded Cube execution probes and complete synchronized-snapshot key "
        "checks for every authored relationship in one artifact. Reports unresolved keys, "
        "orphans, nulls, duplicates and declared-cardinality failures."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def validate_relationships(artifact: ArtifactSlug) -> dict[str, Any]:
    context = await artifact_context(artifact)

    return await run_mcp_action(validate_collection_relationships(int(context["id"])))
