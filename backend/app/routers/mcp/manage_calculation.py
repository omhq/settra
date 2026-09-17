from typing import Annotated, Any, Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from app.calculation_service import (
    create_calculation,
    delete_calculation,
    update_calculation,
)

from .common import mcp_server, run_mcp_action
from .management import (
    AppSlug,
    app_context,
    calculation_context,
    calculation_projection,
    required_text,
)


@mcp_server.tool(
    name="manage_calculation",
    title="Manage Calculation",
    description=(
        "Create, update or delete an App calculation. create requires name "
        "and content. update requires calculation, complete replacement content, "
        "and the exact previous content returned by get_calculation. "
        "delete requires calculation and explicit user approval. Calculations stay "
        "in the App where they were created, and dependencies are checked before deletion."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
async def manage_calculation(
    collection: AppSlug,
    operation: Literal["create", "update", "delete"],
    calculation: Annotated[
        str | None,
        Field(
            max_length=63,
            pattern=r"^[a-z][a-z0-9_]*$",
            description="Existing App-local calculation slug.",
        ),
    ] = None,
    name: Annotated[str | None, Field(max_length=120)] = None,
    content: Annotated[
        str | None,
        Field(description="Complete canonical calculation YAML."),
    ] = None,
    expected_content: Annotated[
        str | None,
        Field(description="Exact content returned by get_calculation."),
    ] = None,
) -> dict[str, Any]:
    if operation == "create":
        app = await app_context(collection, write=True)
        created = await run_mcp_action(
            create_calculation(
                collection_id=int(app["id"]),
                name=required_text(name, "name", operation),
                content=required_text(content, "content", operation),
            )
        )

        return calculation_projection(created, include_content=True)

    calculation_slug = required_text(calculation, "calculation", operation)
    _, current = await calculation_context(
        collection,
        calculation_slug,
        write=True,
    )

    if operation == "update":
        updated = await run_mcp_action(
            update_calculation(
                int(current["id"]),
                content=required_text(content, "content", operation),
                expected_content=required_text(
                    expected_content, "expected_content", operation
                ),
            )
        )

        return calculation_projection(updated, include_content=True)

    return await run_mcp_action(delete_calculation(int(current["id"])))
