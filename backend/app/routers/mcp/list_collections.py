from typing import Any

from mcp.types import ToolAnnotations

from app.collection_service import list_collections as load_collections

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="list_collections",
    title="List Data Collections",
    description=(
        "List the available logical collections of durable data pipes. Start here "
        "when the MCP URL is not pinned to one collection. Ask the user which "
        "collection to use, then pass its slug to collection-scoped tools. The "
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
async def list_collections() -> list[dict[str, Any]]:
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
