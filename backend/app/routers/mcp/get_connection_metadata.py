from typing import Annotated, Any, Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from app.routers.connection_metadata import bounded_connection_metadata
from app.collection_service import require_pipe_in_collection

from .common import mcp_server, run_mcp_action

ConnectionMetadataInclude = Literal["columns", "source_metadata"]


@mcp_server.tool(
    name="get_connection_metadata",
    title="Describe Source",
    description=(
        "Describe one existing Google Drive source by refreshing PostgreSQL metadata and "
        "returning a bounded, paginated source-table catalog. Source creation and "
        "configuration are user-only actions in the signed-in browser under Data > "
        "Sources. Omit app to inspect any source returned by list_connections, or pass "
        "an artifact slug to restrict inspection to that artifact. The default returns five "
        "tables with the first ten "
        "columns of each table; generated DDL and source metadata are omitted. Pass "
        "include=[] for table summaries only, or include=['columns', "
        "'source_metadata'] for both bounded details. Use search to narrow to one "
        "table and column_cursor to continue through wide tables. source_metadata "
        "is opt-in and bounded. source_metadata_available is emitted only when true; "
        "its absence means no source metadata was reported. The top-level table "
        "page returns page.next_cursor for the cursor input; each nested column "
        "page returns column_page.next_column_cursor for the column_cursor input. "
        "Page objects otherwise omit values that repeat request arguments or "
        "returned arrays. Use this before profiling, sampling, or "
        "drafting an overlay. The catalog reflects the latest successful dlt sync."
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
    app: Annotated[
        str | None,
        Field(
            description=(
                "Optional artifact slug. Omit on the global MCP URL to describe any "
                "workspace source, or pass an artifact slug to enforce artifact membership."
            )
        ),
    ] = None,
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
                description=(
                    "Optional bounded details. Omit for column pages; pass an empty "
                    "list for table summaries only."
                ),
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
            description=(
                "Column cursor applied to each returned table; continue with "
                "column_page.next_column_cursor."
            ),
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

    if app is not None:
        await run_mcp_action(require_pipe_in_collection(app, connection_id))

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
