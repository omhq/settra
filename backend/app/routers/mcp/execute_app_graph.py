from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from app.calculations.service import execute_collection_graph
from app.collection_graph_service import get_collection_graph
from app.utils import jsonable

from .common import mcp_server, run_mcp_action
from .management import AppSlug, app_context


@mcp_server.tool(
    name="execute_app_graph",
    title="Execute App Graph",
    description=(
        "Execute every published output in an App graph, or one selected node and "
        "its dependency closure. Optional content tests an unsaved graph draft."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def execute_app_graph(
    collection: AppSlug,
    content: str | None = None,
    target_node_id: Annotated[
        str | None,
        Field(max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$"),
    ] = None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    app = await app_context(collection)
    graph = await run_mcp_action(get_collection_graph(int(app["id"])))
    result = await run_mcp_action(
        execute_collection_graph(
            int(app["id"]),
            content=content if content is not None else str(graph["content"]),
            target_node_id=target_node_id,
            parameters=parameters or {},
        )
    )

    return jsonable(result)
