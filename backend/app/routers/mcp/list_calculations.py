from typing import Any

from mcp.types import ToolAnnotations

from app.calculation_service import list_calculations as load_calculations

from .common import mcp_server, run_mcp_action
from .management import AppSlug, app_context, calculation_projection


@mcp_server.tool(
    name="list_calculations",
    title="List App Calculations",
    description=(
        "List calculation drafts in one App. Returns stable App-local slugs and "
        "timestamps without repeating YAML content. Use get_calculation for the "
        "complete definition."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_calculations(collection: AppSlug) -> dict[str, Any]:
    app = await app_context(collection)
    calculations = await run_mcp_action(load_calculations(collection_id=int(app["id"])))

    return {
        "app": app["slug"],
        "calculations": [
            calculation_projection(item, include_content=False) for item in calculations
        ],
        "count": len(calculations),
    }
