from typing import Any

from mcp.types import ToolAnnotations

from app.collection_graph_service import get_collection_graph as load_app_graph
from app.utils import jsonable

from .common import mcp_server, run_mcp_action
from .management import AppSlug, app_context


@mcp_server.tool(
    name="get_app_graph",
    title="Get App Graph",
    description=(
        "Read an App's complete canonical execution-graph YAML, saved layout, "
        "revision and legacy-import status. Use the returned revision when saving."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def get_app_graph(collection: AppSlug) -> dict[str, Any]:
    app = await app_context(collection)
    graph = await run_mcp_action(load_app_graph(int(app["id"])))

    return jsonable(graph)
