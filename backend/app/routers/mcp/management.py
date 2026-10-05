from typing import Annotated, Any

from pydantic import Field

from app.collection_service import require_collection
from app.utils import jsonable

from .common import require_mcp_write_access, run_mcp_action

ArtifactSlug = Annotated[
    str,
    Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Selected artifact slug returned by list_artifacts.",
    ),
]


async def artifact_context(artifact: str, *, write: bool = False) -> dict[str, Any]:
    if write:
        require_mcp_write_access()

    return await run_mcp_action(require_collection(artifact))


def artifact_projection(artifact: dict[str, Any]) -> dict[str, Any]:
    return jsonable(
        {
            "name": artifact["name"],
            "slug": artifact["slug"],
            "description": artifact.get("description") or "",
            "agent_instructions": artifact.get("agent_instructions") or "",
            "pipe_ids": [int(pipe_id) for pipe_id in artifact.get("pipe_ids", [])],
            "pipe_count": int(artifact.get("pipe_count") or 0),
            "cube_count": int(artifact.get("cube_count") or 0),
            "updated_at": artifact.get("updated_at"),
        }
    )


def required_text(value: str | None, field: str, operation: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{field} is required when operation is '{operation}'")

    return value
