from typing import Any

from mcp.types import ToolAnnotations

from app.calculations.service import validate_collection_graph
from app.collection_graph_service import get_collection_graph

from .common import mcp_server, run_mcp_action
from .management import ArtifactSlug, artifact_context


@mcp_server.tool(
    name="validate_artifact_graph",
    title="Validate Artifact Graph",
    description=(
        "Validate an artifact's saved graph or an optional unsaved replacement YAML "
        "without executing it. Returns the complete dependency plan."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def validate_artifact_graph(
    artifact: ArtifactSlug,
    content: str | None = None,
) -> dict[str, Any]:
    context = await artifact_context(artifact)
    graph = await run_mcp_action(get_collection_graph(int(context["id"])))

    return await run_mcp_action(
        validate_collection_graph(
            int(context["id"]),
            content=content if content is not None else str(graph["content"]),
        )
    )
