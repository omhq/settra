from typing import Any

from mcp.types import ToolAnnotations

from app.calculations.service import validate_calculation as validate_document

from .common import mcp_server, run_mcp_action
from .management import AppSlug, CalculationSlug, calculation_context


@mcp_server.tool(
    name="validate_calculation",
    title="Validate Calculation",
    description=(
        "Validate a saved calculation or optional unsaved replacement YAML without "
        "executing it. Resolves App-scoped cubes, aggregate sources, parameters and "
        "calculation_output dependencies, and returns the execution plan."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def validate_calculation(
    collection: AppSlug,
    calculation: CalculationSlug,
    content: str | None = None,
) -> dict[str, Any]:
    _, item = await calculation_context(collection, calculation)

    return await run_mcp_action(validate_document(int(item["id"]), content=content))
