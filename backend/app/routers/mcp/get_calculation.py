from typing import Any

from mcp.types import ToolAnnotations

from .common import mcp_server
from .management import (
    AppSlug,
    CalculationSlug,
    calculation_context,
    calculation_projection,
)


@mcp_server.tool(
    name="get_calculation",
    title="Get Calculation",
    description=(
        "Read one App calculation's exact canonical YAML. Use this before editing, "
        "moving, validating, executing or referencing one of its named outputs."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def get_calculation(
    collection: AppSlug,
    calculation: CalculationSlug,
) -> dict[str, Any]:
    _, item = await calculation_context(collection, calculation)

    return calculation_projection(item, include_content=True)
