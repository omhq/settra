from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from app.collection_service import require_collection

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="get_collection_context",
    title="Get Collection Context",
    description=(
        "Load one selected collection's agent instructions, member pipes, durable "
        "PostgreSQL destination tables, and available Cube names in one response. "
        "Call this once after the user selects a collection. Continue passing the "
        "same collection slug to discovery and query tools for the conversation."
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
        Field(description="Collection slug returned by list_collections."),
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
