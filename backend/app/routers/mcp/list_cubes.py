from typing import Annotated, Any, Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from app.cube.query import semantic_catalog

from .common import mcp_server, run_mcp_action

CubeCatalogInclude = Literal["measures", "dimensions", "segments", "joins"]


@mcp_server.tool(
    name="list_cubes",
    title="List Cubes",
    description=(
        "Discover compiled Cube cubes and views through a bounded catalog. By "
        "default this returns five high-level cube identities, source labels, and "
        "member counts with descriptions capped at 160 characters. Request and "
        "compiler echoes are omitted. Use search whenever the request names an app, "
        "entity, or metric; start without include. Request bounded member previews "
        "only when needed and use next_cursor to continue. Use get_cube for compact, "
        "complete semantics for one selected cube. Use list_semantic_overlays for "
        "authored overlay provenance or models that failed to compile."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_cubes(
    search: (
        Annotated[
            str,
            Field(
                max_length=200,
                description="Natural-language app, entity, metric, or cube-name filter.",
            ),
        ]
        | None
    ) = None,
    include: (
        Annotated[
            list[CubeCatalogInclude],
            Field(
                max_length=4,
                description="Optional member previews; omit for high-level discovery.",
            ),
        ]
        | None
    ) = None,
    cursor: Annotated[
        int,
        Field(ge=0, description="Cursor returned as page.next_cursor."),
    ] = 0,
    limit: Annotated[
        int,
        Field(ge=1, le=5, description="Cubes per page; capped at five."),
    ] = 5,
    member_limit: Annotated[
        int,
        Field(
            ge=1,
            le=10,
            description="Members per requested collection and cube; capped at ten.",
        ),
    ] = 10,
) -> dict[str, Any]:
    """List a bounded page of compiled Cube semantic metadata."""

    return await run_mcp_action(
        semantic_catalog(
            search=search,
            include=include,
            cursor=cursor,
            limit=limit,
            member_limit=member_limit,
        )
    )
