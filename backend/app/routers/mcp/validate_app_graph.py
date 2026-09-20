from typing import Any

from mcp.types import ToolAnnotations

from app.calculations.service import validate_collection_graph
from app.collection_graph_service import get_collection_graph

from .common import mcp_server, run_mcp_action
from .management import AppSlug, app_context


@mcp_server.tool(
    name="validate_app_graph",
    title="Validate App Graph",
    description=(
        "Validate an App's saved graph or an optional unsaved replacement YAML "
        "without executing it. Returns the complete dependency plan."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def validate_app_graph(
    collection: AppSlug,
    content: str | None = None,
) -> dict[str, Any]:
    app = await app_context(collection)
    graph = await run_mcp_action(get_collection_graph(int(app["id"])))

    return await run_mcp_action(
        validate_collection_graph(
            int(app["id"]),
            content=content if content is not None else str(graph["content"]),
        )
    )
