from typing import Any

from mcp.types import ToolAnnotations

from app.collection_service import list_artifacts as load_artifacts

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="list_artifacts",
    title="List Data Artifacts",
    description=(
        "List the reusable data artifacts available in this workspace. Start here, "
        "ask the user which artifact to use, then pass its slug to artifact-scoped "
        "tools. Each result includes a compact description, source names, and counts."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_artifacts() -> list[dict[str, Any]]:
    collections = await run_mcp_action(load_artifacts())

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
