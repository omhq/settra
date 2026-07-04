from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from app.agent.consts import TABLE_SAMPLE_MAX_COLUMNS
from app.cube.projection import (
    PROFILE_DESCRIPTION_MAX_CHARS,
    TableProfileProjectionInput,
    semantic_response_projector,
)
from app.routers.connection_metadata import MAX_PROFILE_ROWS, profile_connection_table

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="profile_connection_table",
    title="Profile Connection Table",
    description=(
        "Use this bounded profiler when evaluating candidate dimensions, measures, "
        "identifiers, or cross-application relationship keys. Do not infer a "
        "business relationship solely because fields have similar names; inspect "
        "uniqueness, null rates, example values, and overlap before proposing an "
        "overlay. Results use a map keyed by column name and omit repeated sample, "
        "nullability, and matching source/inferred type fields. Descriptions are "
        "omitted by default; set include_descriptions=true to include descriptions "
        f"capped at {PROFILE_DESCRIPTION_MAX_CHARS} characters, or use "
        "get_connection_metadata with include=['columns'] for paginated schema "
        "descriptions. This tool does not run arbitrary SQL or full-table scans. "
        "Google Sheets virtual worksheet tables are reconstructed from "
        "googlesheets_cell."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def profile_table(
    connection_id: int,
    table_name: str,
    limit: Annotated[
        int,
        Field(ge=1, le=MAX_PROFILE_ROWS, description="Rows to sample; capped at 500."),
    ] = MAX_PROFILE_ROWS,
    columns: (
        Annotated[
            list[str],
            Field(
                max_length=TABLE_SAMPLE_MAX_COLUMNS,
                description="Optional columns to profile; capped at 24.",
            ),
        ]
        | None
    ) = None,
    include_descriptions: Annotated[
        bool,
        Field(description="Include bounded column descriptions in the response."),
    ] = False,
) -> dict[str, Any]:
    """Fetch a bounded sample-based profile for a saved connection table."""

    response = await run_mcp_action(
        profile_connection_table(
            connection_id,
            table_name,
            limit=limit,
            columns=columns,
        )
    )

    return semantic_response_projector.table_profile(
        TableProfileProjectionInput(
            response=response,
            include_descriptions=include_descriptions,
        )
    )
