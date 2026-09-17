from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from app.calculations.service import execute_calculation as execute_document
from app.utils import jsonable

from .common import mcp_server, run_mcp_action
from .management import AppSlug, CalculationSlug, calculation_context


@mcp_server.tool(
    name="execute_calculation",
    title="Execute Calculation",
    description=(
        "Execute all named outputs of a saved calculation, or one target node and "
        "its dependency closure. Optional content tests an unsaved replacement. "
        "Runtime parameters are type-checked and remain separate from YAML."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def execute_calculation(
    collection: AppSlug,
    calculation: CalculationSlug,
    content: str | None = None,
    target_node_id: Annotated[
        str | None,
        Field(max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$"),
    ] = None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _, item = await calculation_context(collection, calculation)
    result = await run_mcp_action(
        execute_document(
            int(item["id"]),
            content=content,
            target_node_id=target_node_id,
            parameters=parameters or {},
        )
    )

    return jsonable(result)
