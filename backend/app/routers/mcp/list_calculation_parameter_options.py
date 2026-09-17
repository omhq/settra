from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from app.calculations.service import calculation_parameter_options

from .common import mcp_server, run_mcp_action
from .management import AppSlug, CalculationSlug, calculation_context


@mcp_server.tool(
    name="list_calculation_parameter_options",
    title="List Calculation Parameter Options",
    description=(
        "Return bounded distinct Cube values for one string or boolean calculation "
        "parameter. Optional content resolves options for an unsaved replacement "
        "definition."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_calculation_parameter_options(
    collection: AppSlug,
    calculation: CalculationSlug,
    parameter: Annotated[
        str,
        Field(min_length=1, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$"),
    ],
    content: str | None = None,
    search: Annotated[str | None, Field(max_length=100)] = None,
) -> dict[str, Any]:
    _, item = await calculation_context(collection, calculation)

    return await run_mcp_action(
        calculation_parameter_options(
            int(item["id"]),
            parameter,
            content=content,
            search=search,
        )
    )
