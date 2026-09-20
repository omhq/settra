from typing import Any

from mcp.types import ToolAnnotations

from app.collection_service import list_collections as load_collections

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="list_apps",
    title="List Apps",
    description=(
        "List the available Apps containing durable data pipes, semantics and "
        "App graphs. Start here, ask the user which App to use, then pass its "
        "slug to App-scoped tools. The "
        "response contains compact descriptions, member pipe names, and counts; "
        "it does not expose unrelated Cube metadata."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_apps() -> list[dict[str, Any]]:
    collections = await run_mcp_action(load_collections())

    return [
        {
            "name": item["name"],
            "slug": item["slug"],
            "description": item["description"],
            "pipe_count": item["pipe_count"],
            "table_count": item["table_count"],
            "cube_count": item["cube_count"],
            "pipes": [pipe["name"] for pipe in item["pipes"]],
        }
        for item in collections
    ]
