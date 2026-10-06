import json
import math

from typing import Any

import asyncpg
import yaml

from app.auth import current_organization_id, require_organization_write_access
from app.calculations.parser import validate_calculation_yaml_draft
from app.change_events import publish_workspace_change
from app.collection_service import get_collection
from app.db import db_connection
from app.errors import InvalidInputError, ResourceConflictError

MAX_GRAPH_LAYOUT_BYTES = 256 * 1024


async def get_collection_graph(collection_id: int) -> dict[str, Any]:
    collection = await get_collection(collection_id, include_assets=False)
    organization_id = current_organization_id()

    async with db_connection() as db:
        row = await db.fetchrow(
            """
            SELECT collection_id, content, layout, revision, created_at, updated_at
            FROM collection_graphs
            WHERE collection_id = $1 AND organization_id = $2
            """,
            collection_id,
            organization_id,
        )

    if row is not None:
        return _project_graph(dict(row), persisted=True)

    return {
        "artifact_id": collection_id,
        "content": _initial_graph_content(collection),
        "layout": _empty_layout(),
        "revision": 0,
        "persisted": False,
        "created_at": None,
        "updated_at": None,
    }


async def list_effective_graph_documents(
    collection_id: int,
) -> list[dict[str, Any]]:
    """Return the artifact's canonical graph when it has been saved."""
    async with db_connection() as db:
        row = await db.fetchrow(
            """
            SELECT content
            FROM collection_graphs
            WHERE collection_id = $1 AND organization_id = $2
            """,
            collection_id,
            current_organization_id(),
        )

    if row is None:
        return []

    return [
        {
            "id": -int(collection_id),
            "name": "Artifact graph",
            "slug": "artifact_graph",
            "content": str(row["content"]),
        }
    ]


async def save_collection_graph(
    collection_id: int,
    *,
    content: str,
    layout: dict[str, Any],
    expected_revision: int,
) -> dict[str, Any]:
    identity = require_organization_write_access()
    await get_collection(collection_id, include_assets=False)
    normalized_content = validate_calculation_yaml_draft(content)
    normalized_layout = _validated_layout(layout)

    if expected_revision < 0:
        raise InvalidInputError("expected_revision must not be negative")

    async with db_connection() as db:
        if expected_revision == 0:
            try:
                row = await db.fetchrow(
                    """
                    INSERT INTO collection_graphs (
                        collection_id, organization_id, created_by_user_id,
                        content, layout
                    ) VALUES ($1, $2, $3, $4, $5)
                    RETURNING collection_id, content, layout, revision,
                              created_at, updated_at
                    """,
                    collection_id,
                    identity.organization_id,
                    identity.user_id,
                    normalized_content,
                    normalized_layout,
                )
            except asyncpg.UniqueViolationError as exc:
                raise ResourceConflictError(
                    "This artifact graph was created elsewhere. Reload before saving."
                ) from exc
        else:
            row = await db.fetchrow(
                """
                UPDATE collection_graphs
                SET content = $1,
                    layout = $2,
                    revision = revision + 1,
                    updated_at = now()
                WHERE collection_id = $3
                  AND organization_id = $4
                  AND revision = $5
                RETURNING collection_id, content, layout, revision,
                          created_at, updated_at
                """,
                normalized_content,
                normalized_layout,
                collection_id,
                identity.organization_id,
                expected_revision,
            )

    if row is None:
        raise ResourceConflictError(
            "This artifact graph was changed elsewhere. Reload before saving."
        )

    graph = _project_graph(dict(row), persisted=True)

    publish_workspace_change(
        organization_id=identity.organization_id,
        resources=("artifact_graphs",),
        action="updated",
        entity_id=collection_id,
        artifact_id=collection_id,
        revision=int(graph["revision"]),
    )

    return graph


def _project_graph(row: dict[str, Any], *, persisted: bool) -> dict[str, Any]:
    try:
        layout = json.loads(str(row.get("layout") or "{}"))
    except (TypeError, ValueError):
        layout = _empty_layout()

    return {
        **{key: value for key, value in row.items() if key != "collection_id"},
        "artifact_id": int(row["collection_id"]),
        "layout": layout,
        "persisted": persisted,
    }


def _empty_layout() -> dict[str, Any]:
    return {"version": 1, "nodes": {}}


def _validated_layout(layout: dict[str, Any]) -> str:
    if not isinstance(layout, dict):
        raise InvalidInputError("Graph layout must be an object")
    if set(layout) - {"version", "nodes", "viewport"}:
        raise InvalidInputError("Graph layout contains unsupported fields")
    if layout.get("version", 1) != 1:
        raise InvalidInputError("Graph layout version must be 1")

    nodes = layout.get("nodes", {})
    if not isinstance(nodes, dict):
        raise InvalidInputError("Graph layout nodes must be an object")
    if len(nodes) > 500:
        raise InvalidInputError("Graph layout may contain at most 500 nodes")

    normalized_nodes: dict[str, dict[str, float]] = {}

    for node_id, position in nodes.items():
        if not isinstance(node_id, str) or not node_id:
            raise InvalidInputError("Graph layout node IDs must be non-empty strings")
        if not isinstance(position, dict) or set(position) != {"x", "y"}:
            raise InvalidInputError(
                f"Graph layout position for '{node_id}' must contain x and y"
            )

        coordinates: dict[str, float] = {}
        for axis in ("x", "y"):
            value = position[axis]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise InvalidInputError(
                    f"Graph layout {axis} for '{node_id}' must be numeric"
                )
            if not math.isfinite(value) or abs(value) > 1_000_000:
                raise InvalidInputError(
                    f"Graph layout {axis} for '{node_id}' is out of range"
                )
            coordinates[axis] = round(float(value), 2)

        normalized_nodes[node_id] = coordinates

    normalized_layout: dict[str, Any] = {
        "version": 1,
        "nodes": normalized_nodes,
    }
    viewport = layout.get("viewport")
    if viewport is not None:
        if not isinstance(viewport, dict) or set(viewport) != {"x", "y", "zoom"}:
            raise InvalidInputError("Graph layout viewport must contain x, y and zoom")

        normalized_viewport: dict[str, float] = {}
        for field in ("x", "y", "zoom"):
            value = viewport[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise InvalidInputError(
                    f"Graph layout viewport {field} must be numeric"
                )
            if not math.isfinite(value):
                raise InvalidInputError(
                    f"Graph layout viewport {field} is out of range"
                )
            if field in {"x", "y"} and abs(value) > 1_000_000:
                raise InvalidInputError(
                    f"Graph layout viewport {field} is out of range"
                )
            if field == "zoom" and not 0.01 <= value <= 100:
                raise InvalidInputError("Graph layout viewport zoom is out of range")
            normalized_viewport[field] = round(
                float(value),
                4 if field == "zoom" else 2,
            )

        normalized_layout["viewport"] = normalized_viewport

    normalized = json.dumps(
        normalized_layout,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(normalized.encode("utf-8")) > MAX_GRAPH_LAYOUT_BYTES:
        raise InvalidInputError("Graph layout must be 256 KB or smaller")
    return normalized


def _initial_graph_content(collection: dict[str, Any]) -> str:
    return yaml.safe_dump(
        {
            "version": 1,
            "name": str(collection["slug"]),
            "description": str(collection.get("description") or ""),
            "parameters": [],
            "nodes": [],
            "outputs": {},
        },
        sort_keys=False,
        allow_unicode=True,
    )
