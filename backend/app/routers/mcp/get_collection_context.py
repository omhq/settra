from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from app.collection_service import require_collection

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="get_collection_context",
    title="Get App Context",
    description=(
        "Load one selected App's agent instructions, member pipes, durable "
        "PostgreSQL destination tables, and available Cube names in one response. "
        "Call this once after the user selects an App. Continue passing the same "
        "App slug to discovery and query tools for the conversation."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def get_collection_context(
    collection: Annotated[
        str,
        Field(description="App slug returned by list_collections."),
    ],
) -> dict[str, Any]:
    context = await run_mcp_action(require_collection(collection))

    return {
        "name": context["name"],
        "slug": context["slug"],
        "description": context["description"],
        "agent_instructions": context["agent_instructions"],
        "pipes": context["pipes"],
        "tables": context["tables"],
        "cube_names": context["cube_names"],
    }
