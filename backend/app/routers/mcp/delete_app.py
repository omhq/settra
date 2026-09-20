from typing import Any

from mcp.types import ToolAnnotations

from app.collection_service import delete_collection

from .common import mcp_server, run_mcp_action
from .management import AppSlug, app_context


@mcp_server.tool(
    name="delete_app",
    title="Delete App",
    description=(
        "Delete an empty App after explicit user approval. Its source snapshots are "
        "retained. Authored semantic models must be removed or "
        "moved first, and the backend rejects deletion while they remain."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
async def delete_app(app: AppSlug) -> dict[str, Any]:
    context = await app_context(app, write=True)

    return await run_mcp_action(delete_collection(int(context["id"])))
