from typing import Any

from mcp.types import ToolAnnotations

from app.cube.client import load_cube_meta

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="get_cube_meta",
    title="Get Cube Metadata",
    description=(
        "Fetch the raw Cube /v1/meta metadata payload. Use this only when the "
        "summarized list_cubes/get_cube tools do not expose enough compiled "
        "semantic detail. This does not reveal overlays that failed compilation."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def get_cube_meta() -> dict[str, Any]:
    """Fetch the raw Cube metadata payload."""

    return await run_mcp_action(load_cube_meta())
