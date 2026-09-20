from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from app.calculations.service import collection_graph_parameter_options
from app.collection_graph_service import get_collection_graph

from .common import mcp_server, run_mcp_action
from .management import AppSlug, app_context


@mcp_server.tool(
    name="list_app_graph_parameter_options",
    title="List App Graph Parameter Options",
    description=(
        "Return bounded distinct Cube values for one string or boolean App-graph "
        "parameter. Optional content resolves an unsaved graph draft."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_app_graph_parameter_options(
    app: AppSlug,
    parameter: Annotated[
        str,
        Field(min_length=1, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$"),
    ],
    content: str | None = None,
    search: Annotated[str | None, Field(max_length=100)] = None,
) -> dict[str, Any]:
    context = await app_context(app)
    graph = await run_mcp_action(get_collection_graph(int(context["id"])))

    return await run_mcp_action(
        collection_graph_parameter_options(
            int(context["id"]),
            parameter,
            content=content if content is not None else str(graph["content"]),
            search=search,
        )
    )
