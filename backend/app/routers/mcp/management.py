from typing import Annotated, Any

from pydantic import Field

from app.collection_service import require_collection
from app.utils import jsonable

from .common import require_mcp_write_access, run_mcp_action

AppSlug = Annotated[
    str,
    Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Selected App slug returned by list_apps.",
    ),
]


async def app_context(collection: str, *, write: bool = False) -> dict[str, Any]:
    if write:
        require_mcp_write_access()

    return await run_mcp_action(require_collection(collection))


def app_projection(app: dict[str, Any]) -> dict[str, Any]:
    return jsonable(
        {
            "name": app["name"],
            "slug": app["slug"],
            "description": app.get("description") or "",
            "agent_instructions": app.get("agent_instructions") or "",
            "pipe_ids": [int(pipe_id) for pipe_id in app.get("pipe_ids", [])],
            "pipe_count": int(app.get("pipe_count") or 0),
            "cube_count": int(app.get("cube_count") or 0),
            "updated_at": app.get("updated_at"),
        }
    )


def required_text(value: str | None, field: str, operation: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{field} is required when operation is '{operation}'")

    return value
