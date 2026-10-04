from typing import Any

from mcp.types import ToolAnnotations

from app.collection_graph_service import save_collection_graph
from app.utils import jsonable

from .common import mcp_server, run_mcp_action
from .management import AppSlug, app_context


@mcp_server.tool(
    name="manage_app_graph",
    title="Manage Artifact Graph",
    description=(
        "Replace an artifact's complete canonical graph YAML and visual layout. "
        "Pass the exact revision returned by get_app_graph; stale writes are rejected."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
async def manage_app_graph(
    app: AppSlug,
    content: str,
    layout: dict[str, Any],
    expected_revision: int,
) -> dict[str, Any]:
    context = await app_context(app, write=True)
    graph = await run_mcp_action(
        save_collection_graph(
            int(context["id"]),
            content=content,
            layout=layout,
            expected_revision=expected_revision,
        )
    )

    return jsonable(graph)
