from typing import Any

from mcp.types import ToolAnnotations

from app.collection_graph_service import get_collection_graph as load_artifact_graph
from app.utils import jsonable

from .common import mcp_server, run_mcp_action
from .management import ArtifactSlug, artifact_context


@mcp_server.tool(
    name="get_artifact_graph",
    title="Get Artifact Graph",
    description=(
        "Read an artifact's complete canonical execution-graph YAML, saved layout, "
        "revision. Use the returned revision when saving."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def get_artifact_graph(artifact: ArtifactSlug) -> dict[str, Any]:
    context = await artifact_context(artifact)
    graph = await run_mcp_action(load_artifact_graph(int(context["id"])))

    return jsonable(graph)
