from typing import Any

from mcp.types import ToolAnnotations

from app.collection_service import delete_collection

from .common import mcp_server, run_mcp_action
from .management import ArtifactSlug, artifact_context


@mcp_server.tool(
    name="delete_artifact",
    title="Delete Data Artifact",
    description=(
        "Delete an empty artifact after explicit user approval. Its source snapshots are "
        "retained. Authored semantic models must be removed or "
        "moved first, and the backend rejects deletion while they remain."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
async def delete_artifact(artifact: ArtifactSlug) -> dict[str, Any]:
    context = await artifact_context(artifact, write=True)

    return await run_mcp_action(delete_collection(int(context["id"])))
