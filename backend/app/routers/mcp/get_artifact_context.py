from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from app.collection_service import require_collection

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="get_artifact_context",
    title="Get Data Artifact Context",
    description=(
        "Load one selected artifact's instructions, sources, available tables, and "
        "semantic model names in one response. "
        "Call this once after the user selects an artifact. Continue passing the same "
        "artifact slug to discovery and query tools for the conversation."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def get_artifact_context(
    artifact: Annotated[
        str,
        Field(description="Artifact slug returned by list_artifacts."),
    ],
) -> dict[str, Any]:
    context = await run_mcp_action(require_collection(artifact))

    return {
        "name": context["name"],
        "slug": context["slug"],
        "description": context["description"],
        "agent_instructions": context["agent_instructions"],
        "pipes": context["pipes"],
        "tables": context["tables"],
        "cube_names": context["cube_names"],
    }
