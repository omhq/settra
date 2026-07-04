from typing import Annotated, Any, Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from app.routers.connection_metadata import bounded_connection_metadata

from .common import mcp_server, run_mcp_action

ConnectionMetadataInclude = Literal["columns", "source_metadata"]


@mcp_server.tool(
    name="get_connection_metadata",
    title="Get Connection Metadata",
    description=(
        "Refresh live metadata and return a bounded, paginated table catalog for "
        "one saved connection. The default returns five table summaries without "
        "column arrays, source metadata, or generated DDL. Use search to narrow by "
        "table or column, include=['columns'] for capped column pages, and "
        "column_cursor to continue through wide tables. source_metadata is also "
        "opt-in and bounded. source_metadata_available is emitted only when true; "
        "its absence means no source metadata was reported. Page objects contain "
        "only total and next_cursor because the other values repeat request "
        "arguments or returned arrays. Use this before profiling, sampling, or "
        "drafting an overlay. Google Sheets worksheet tables synthesized from "
        "header rows are included in the catalog."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def get_connection_metadata(
    connection_id: int,
    search: (
        Annotated[
            str,
            Field(
                max_length=200,
                description="Table-name, column-name, or description filter.",
            ),
        ]
        | None
    ) = None,
    include: (
        Annotated[
            list[ConnectionMetadataInclude],
            Field(
                max_length=2,
                description=("Optional bounded detail; omit for table summaries only."),
            ),
        ]
        | None
    ) = None,
    cursor: Annotated[
        int,
        Field(ge=0, description="Table cursor returned as page.next_cursor."),
    ] = 0,
    limit: Annotated[
        int,
        Field(ge=1, le=5, description="Tables per page; capped at five."),
    ] = 5,
    column_cursor: Annotated[
        int,
        Field(
            ge=0,
            description="Column cursor applied to each returned table.",
        ),
    ] = 0,
    column_limit: Annotated[
        int,
        Field(
            ge=1,
            le=10,
            description="Columns per returned table; capped at ten.",
        ),
    ] = 10,
) -> dict[str, Any]:
    """Fetch a bounded page of refreshed non-secret schema metadata."""

    return await run_mcp_action(
        bounded_connection_metadata(
            connection_id,
            search=search,
            include=include,
            cursor=cursor,
            limit=limit,
            column_cursor=column_cursor,
            column_limit=column_limit,
        )
    )
