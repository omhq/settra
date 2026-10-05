from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from app.calculations.service import collection_graph_parameter_options
from app.collection_graph_service import get_collection_graph

from .common import mcp_server, run_mcp_action
from .management import ArtifactSlug, artifact_context


@mcp_server.tool(
    name="list_artifact_graph_parameter_options",
    title="List Artifact Graph Parameter Options",
    description=(
        "Return bounded distinct Cube values for one string or boolean artifact-graph "
        "parameter. Optional content resolves an unsaved graph draft."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_artifact_graph_parameter_options(
    artifact: ArtifactSlug,
    parameter: Annotated[
        str,
        Field(min_length=1, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$"),
    ],
    content: str | None = None,
    search: Annotated[str | None, Field(max_length=100)] = None,
) -> dict[str, Any]:
    context = await artifact_context(artifact)
    graph = await run_mcp_action(get_collection_graph(int(context["id"])))

    return await run_mcp_action(
        collection_graph_parameter_options(
            int(context["id"]),
            parameter,
            content=content if content is not None else str(graph["content"]),
            search=search,
        )
    )
