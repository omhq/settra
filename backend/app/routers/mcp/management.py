from typing import Annotated, Any

from pydantic import Field

from app.calculation_service import get_calculation_in_collection
from app.collection_service import require_collection
from app.utils import jsonable

from .common import require_mcp_write_access, run_mcp_action

AppSlug = Annotated[
    str,
    Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Selected App slug returned by list_collections.",
    ),
]
CalculationSlug = Annotated[
    str,
    Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="App-local calculation slug returned by list_calculations.",
    ),
]


async def app_context(collection: str, *, write: bool = False) -> dict[str, Any]:
    if write:
        require_mcp_write_access()

    return await run_mcp_action(require_collection(collection))


async def calculation_context(
    collection: str,
    calculation: str,
    *,
    write: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    app = await app_context(collection, write=write)
    item = await run_mcp_action(
        get_calculation_in_collection(int(app["id"]), calculation)
    )

    return app, item


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
            "calculation_count": int(app.get("calculation_count") or 0),
            "updated_at": app.get("updated_at"),
        }
    )


def calculation_projection(
    calculation: dict[str, Any],
    *,
    include_content: bool,
) -> dict[str, Any]:
    result = {
        "name": calculation["name"],
        "slug": calculation["slug"],
        "app": calculation.get("collection_slug"),
        "created_at": calculation.get("created_at"),
        "updated_at": calculation.get("updated_at"),
    }

    if include_content:
        result["content"] = calculation["content"]

    return jsonable(result)


def required_text(value: str | None, field: str, operation: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{field} is required when operation is '{operation}'")

    return value
