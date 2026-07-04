from typing import Annotated, Any, Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from app.cube.query import bounded_cube_meta

from .common import mcp_server, run_mcp_action

CubeMetaInclude = Literal[
    "measures",
    "dimensions",
    "segments",
    "joins",
    "hierarchies",
    "folders",
    "nestedFolders",
]


@mcp_server.tool(
    name="get_cube_meta",
    title="Search Cube Metadata",
    description=(
        "Search a bounded projection of compiled Cube /v1/meta metadata. Results "
        "are paginated by cube; include selects raw member collections, and each "
        "selected collection is capped by member_limit. Defaults return five cube "
        "identities without member collections. Use next_cursor to continue, and "
        "get_cube when one cube needs compact, complete semantics. Example: search='hubspot "
        "deal', include=['measures', 'dimensions']. This does not reveal overlays "
        "that failed compilation."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def get_cube_meta(
    search: Annotated[str, Field(max_length=200)] | None = None,
    include: Annotated[list[CubeMetaInclude], Field(max_length=7)] | None = None,
    cursor: Annotated[int, Field(ge=0)] = 0,
    limit: Annotated[int, Field(ge=1, le=10)] = 5,
    member_limit: Annotated[int, Field(ge=1, le=25)] = 10,
) -> dict[str, Any]:
    """Search a bounded page of detailed Cube metadata."""

    return await run_mcp_action(
        bounded_cube_meta(
            search=search,
            include=include,
            cursor=cursor,
            limit=limit,
            member_limit=member_limit,
        )
    )
