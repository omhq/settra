from mcp.types import ToolAnnotations
from pydantic import Field
from typing import Annotated

from app.collection_service import require_collection
from app.auth import current_organization_id
from app.db import db_connection
from app.destinations import connection_destination
from app.common.config import GOOGLE_DRIVE_KEY

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="list_connections",
    title="List Sources",
    description=(
        "List existing Google Drive tabular sources without secrets, including source "
        "IDs, slugs and separate destination schemas. Source creation and configuration "
        "are user-only actions in the signed-in browser under Data > Sources. Omit "
        "artifact to discover every workspace source, or pass an artifact slug to restrict "
        "the result to its sources."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_connections(
    artifact: Annotated[
        str | None,
        Field(
            description=(
                "Optional artifact slug. Omit on the global MCP URL to list all workspace "
                "pipes."
            )
        ),
    ] = None,
) -> list[dict[str, object]]:
    """List connected Drive data in one artifact or across the active workspace."""

    pipe_ids: list[int] | None = None

    if artifact is not None:
        context = await run_mcp_action(require_collection(artifact))
        pipe_ids = [int(pipe_id) for pipe_id in context["pipe_ids"]]

        if not pipe_ids:
            return []

    pipe_filter = "" if pipe_ids is None else "AND c.id = ANY($2::bigint[])"
    parameters = (
        (GOOGLE_DRIVE_KEY, current_organization_id())
        if pipe_ids is None
        else (GOOGLE_DRIVE_KEY, pipe_ids, current_organization_id())
    )
    organization_parameter = 2 if pipe_ids is None else 3

    async with db_connection() as db:
        rows = await db.fetch(
            f"""
            SELECT c.id, c.name, c.slug, c.plugin, c.status, c.created_at,
                   c.destination_id, c.destination_schema,
                   d.name AS destination_name,
                   d.slug AS destination_slug,
                   d.type AS destination_type,
                   d.configuration AS destination_configuration,
                   d.is_builtin AS destination_is_builtin,
                   d.is_default AS destination_is_default
            FROM connections c
            JOIN destinations d ON d.id = c.destination_id
            WHERE c.plugin = $1 {pipe_filter}
              AND c.organization_id = ${organization_parameter}
            ORDER BY c.created_at DESC
            """,
            *parameters,
        )

    connections = []

    for row in rows:
        connection = dict(row)
        connection["destination"] = connection_destination(connection)

        for key in (
            "destination_name",
            "destination_slug",
            "destination_type",
            "destination_configuration",
            "destination_is_builtin",
            "destination_is_default",
        ):
            connection.pop(key, None)

        connections.append(connection)

    return connections
