from mcp.types import ToolAnnotations
from pydantic import Field
from typing import Annotated

from app.collection_service import require_collection
from app.auth import current_organization_id
from app.db import db_connection
from app.destinations import connection_destination
from app.routers.constants import GOOGLE_DRIVE_KEY

from .common import mcp_server, run_mcp_action


@mcp_server.tool(
    name="list_connections",
    title="List Drive Data",
    description=(
        "List connected Google Drive tabular data without secrets, including source "
        "slugs and their separate destination schemas. Use this before inspecting "
        "source metadata or drafting source-specific semantic overlays."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_connections(
    collection: Annotated[
        str,
        Field(description="Selected collection slug from list_collections."),
    ],
) -> list[dict[str, object]]:
    """List connected Drive data within one collection without secrets."""

    context = await run_mcp_action(require_collection(collection))
    pipe_ids = [int(pipe_id) for pipe_id in context["pipe_ids"]]

    if not pipe_ids:
        return []

    async with db_connection() as db:
        rows = await db.fetch(
            """
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
            WHERE c.plugin = $1 AND c.id = ANY($2::bigint[])
              AND c.organization_id = $3
            ORDER BY c.created_at DESC
            """,
            GOOGLE_DRIVE_KEY,
            pipe_ids,
            current_organization_id(),
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
