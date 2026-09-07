from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from app.collection_service import require_pipe_in_collection
from app.sync.loader import run_connection_sync

from .common import mcp_server, require_mcp_write_access, run_mcp_action


@mcp_server.tool(
    name="sync_connection",
    title="Refresh Pipe",
    description=(
        "Run a complete refresh of one pipe in the selected collection from its "
        "Google Drive file into its fixed PostgreSQL destination, then regenerate "
        "the source Cube model. This replaces the durable snapshot, may take time, "
        "and requires settra:write access. Use only when the user explicitly asks "
        "for or approves a refresh. The tool fails if that pipe is already syncing "
        "and returns a compact completion summary after the refresh finishes."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True,
    ),
)
async def sync_connection(
    collection: Annotated[
        str,
        Field(description="Selected collection slug from list_collections."),
    ],
    connection_id: Annotated[
        int,
        Field(
            ge=1,
            description="Pipe connection ID from the selected collection context.",
        ),
    ],
) -> dict[str, Any]:
    """Refresh one collection pipe and wait for its Cube model to be ready."""

    require_mcp_write_access()
    await run_mcp_action(require_pipe_in_collection(collection, connection_id))
    result = await run_mcp_action(run_connection_sync(connection_id, trigger="mcp"))

    return {
        "ok": bool(result["ok"]),
        "run_id": int(result["run_id"]),
        "destination": {
            "id": int(result["destination_id"]),
            "schema": str(result["schema"]),
        },
        "source_format": str(result["source_format"]),
        "table_count": int(result["table_count"]),
        "row_count": int(result["row_count"]),
        "completed_at": str(result["completed_at"]),
    }
