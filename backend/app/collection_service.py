from __future__ import annotations

from typing import Any

import asyncpg
import yaml

from fastapi import HTTPException

from app.cube.model import authored_definition_index
from app.db import db_connection
from app.routers.constants import CONNECTION_CONFIG_DIR, GOOGLE_SHEETS_KEY
from app.utils import slugify_name


async def list_collections() -> list[dict[str, Any]]:
    async with db_connection() as db:
        collection_rows = await db.fetch("""
            SELECT id, name, slug, description, agent_instructions,
                   created_at, updated_at
            FROM collections
            ORDER BY lower(name), id
            """)
        pipe_rows = await db.fetch(
            """
            SELECT cp.collection_id, c.id, c.name, c.slug, c.status,
                   c.last_synced_at
            FROM collection_pipes cp
            JOIN connections c ON c.id = cp.pipe_id
            WHERE c.plugin = $1
            ORDER BY lower(c.name), c.id
            """,
            GOOGLE_SHEETS_KEY,
        )

    pipes_by_collection: dict[int, list[dict[str, Any]]] = {}

    for row in pipe_rows:
        pipes_by_collection.setdefault(int(row["collection_id"]), []).append(
            _pipe_summary(dict(row))
        )

    return [
        _collection_summary(
            dict(row),
            pipes_by_collection.get(int(row["id"]), []),
        )
        for row in collection_rows
    ]


async def get_collection(
    identifier: int | str,
    *,
    include_assets: bool = True,
) -> dict[str, Any]:
    row, pipes = await _collection_and_pipes(identifier)
    summary = _collection_summary(row, pipes)

    if not include_assets:
        return summary

    tables: list[dict[str, Any]] = []

    for pipe in pipes:
        tables.extend(_pipe_assets(pipe))

    allowed_names = allowed_cube_names_for_pipe_ids({int(pipe["id"]) for pipe in pipes})
    base_names = {str(table["cube_name"]) for table in tables}

    return {
        **summary,
        "tables": tables,
        "cube_names": sorted(allowed_names or base_names),
        "mcp_path": f"/mcp/collections/{row['slug']}",
    }


async def create_collection(
    *,
    name: str,
    description: str,
    agent_instructions: str,
    pipe_ids: list[int],
) -> dict[str, Any]:
    normalized_name = _required_name(name)
    slug = slugify_name(normalized_name)[:63].rstrip("_")

    if not slug:
        raise HTTPException(400, "Collection name must contain letters or numbers")

    normalized_pipe_ids = await _validated_pipe_ids(pipe_ids)

    try:
        async with db_connection() as db, db.transaction():
            collection_id = await db.fetchval(
                """
                INSERT INTO collections (
                    name, slug, description, agent_instructions
                ) VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                normalized_name,
                slug,
                description.strip(),
                agent_instructions.strip(),
            )
            collection_id = int(collection_id)
            await _replace_memberships(db, collection_id, normalized_pipe_ids)
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            409,
            "A collection with that name already exists",
        ) from exc

    return await get_collection(collection_id)


async def update_collection(
    collection_id: int,
    *,
    name: str,
    description: str,
    agent_instructions: str,
    pipe_ids: list[int],
) -> dict[str, Any]:
    await get_collection(collection_id, include_assets=False)
    normalized_pipe_ids = await _validated_pipe_ids(pipe_ids)
    normalized_name = _required_name(name)

    async with db_connection() as db, db.transaction():
        duplicate = await db.fetchval(
            """
            SELECT 1 FROM collections
            WHERE lower(name) = lower($1) AND id != $2
            """,
            normalized_name,
            collection_id,
        )
        if duplicate:
            raise HTTPException(409, "A collection with that name already exists")
        await db.execute(
            """
            UPDATE collections
            SET name = $1, description = $2, agent_instructions = $3,
                updated_at = now()
            WHERE id = $4
            """,
            normalized_name,
            description.strip(),
            agent_instructions.strip(),
            collection_id,
        )
        await _replace_memberships(db, collection_id, normalized_pipe_ids)

    return await get_collection(collection_id)


async def delete_collection(collection_id: int) -> dict[str, Any]:
    collection = await get_collection(collection_id, include_assets=False)

    async with db_connection() as db:
        await db.execute("DELETE FROM collections WHERE id = $1", collection_id)

    return {
        "ok": True,
        "deleted": {"id": collection["id"], "name": collection["name"]},
        "data_retained": True,
    }


async def require_collection(identifier: str | None) -> dict[str, Any]:
    normalized = str(identifier or "").strip()

    if not normalized:
        raise HTTPException(
            400,
            "Collection is required. Call list_collections, ask the user which "
            "collection to use, then pass its slug to collection-scoped tools.",
        )

    return await get_collection(normalized)


async def require_pipe_in_collection(collection: str, pipe_id: int) -> dict[str, Any]:
    context = await require_collection(collection)

    if pipe_id not in {int(value) for value in context["pipe_ids"]}:
        raise HTTPException(
            404,
            f"Pipe {pipe_id} is not in collection '{context['slug']}'",
        )

    return context


async def collection_cube_names(collection: str) -> set[str]:
    context = await require_collection(collection)
    return set(context["cube_names"])


async def validate_overlay_for_collection(
    collection: str,
    content: str,
) -> set[str]:
    """Ensure proposed semantic models only build on the selected collection."""

    context = await require_collection(collection)
    pipe_ids = {int(pipe_id) for pipe_id in context["pipe_ids"]}
    existing_names = set(context["cube_names"])

    try:
        parsed = yaml.safe_load(content) if content.strip() else {}
    except yaml.YAMLError as exc:
        raise HTTPException(400, f"Invalid overlay YAML: {exc}") from exc

    if not isinstance(parsed, dict):
        raise HTTPException(400, "Overlay YAML must contain a mapping")

    definitions: dict[str, dict[str, Any]] = {}
    for key in ("cubes", "views"):
        items = parsed.get(key)
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                definitions[item["name"]] = item

    declared_names = set(definitions)
    authorized_names = set(existing_names)
    pending = dict(definitions)
    changed = True

    while changed:
        changed = False
        for name, definition in list(pending.items()):
            dependencies = _definition_dependencies(definition)
            connection_ids = _definition_connection_ids(definition)
            uses_collection_connections = bool(
                connection_ids
            ) and connection_ids.issubset(pipe_ids)
            builds_on_collection_models = bool(dependencies) and dependencies.issubset(
                authorized_names
            )

            if (
                name in existing_names
                or uses_collection_connections
                or builds_on_collection_models
            ):
                authorized_names.add(name)
                pending.pop(name)
                changed = True

    unavailable: list[str] = list(pending)
    for definition in pending.values():
        unavailable.extend(
            sorted(
                _definition_dependencies(definition) - authorized_names - declared_names
            )
        )

    if unavailable:
        raise HTTPException(
            400,
            "Overlay references models or sources outside the selected collection: "
            + ", ".join(sorted(set(unavailable))),
        )

    return declared_names


async def validate_queries_for_collection(
    collection: str,
    queries: list[dict[str, Any]],
    *,
    additional_names: set[str] | None = None,
) -> None:
    allowed_names = await collection_cube_names(collection)
    allowed_names.update(additional_names or set())
    referenced: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, str) and "." in value:
            name = value.split(".", 1)[0].strip()
            if name:
                referenced.add(name)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(queries)
    unavailable = sorted(referenced - allowed_names)

    if unavailable:
        raise HTTPException(
            400,
            "Cube queries reference models outside the selected collection: "
            + ", ".join(unavailable),
        )


def allowed_cube_names_for_pipe_ids(pipe_ids: set[int]) -> set[str]:
    """Derive collection cubes from model provenance without storing cube membership."""

    if not pipe_ids:
        return set()

    definitions = authored_definition_index()
    allowed: set[str] = set()

    for name, source in definitions.items():
        definition = source.get("definition") if isinstance(source, dict) else None
        if not isinstance(definition, dict):
            continue

        connection_ids = _definition_connection_ids(definition)
        if connection_ids and connection_ids.issubset(pipe_ids):
            allowed.add(name)

    # Views and authored overlays can be derived from already-allowed collection
    # cubes. Iterate because one curated view may build on another.
    changed = True
    while changed:
        changed = False
        for name, source in definitions.items():
            if name in allowed or not isinstance(source, dict):
                continue

            definition = source.get("definition")
            if not isinstance(definition, dict):
                continue

            dependencies = _definition_dependencies(definition)
            if dependencies and dependencies.issubset(allowed):
                allowed.add(name)
                changed = True

    return allowed


async def _collection_and_pipes(
    identifier: int | str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    by_id = isinstance(identifier, int)
    where = "id = $1" if by_id else "slug = $1"
    value: int | str = int(identifier) if by_id else str(identifier).strip()

    async with db_connection() as db:
        row = await db.fetchrow(
            f"""
            SELECT id, name, slug, description, agent_instructions,
                   created_at, updated_at
            FROM collections
            WHERE {where}
            """,
            value,
        )

        if row is None:
            raise HTTPException(404, "Collection not found")

        pipe_rows = await db.fetch(
            """
            SELECT c.id, c.name, c.slug, c.status, c.last_synced_at
            FROM collection_pipes cp
            JOIN connections c ON c.id = cp.pipe_id
            WHERE cp.collection_id = $1 AND c.plugin = $2
            ORDER BY lower(c.name), c.id
            """,
            row["id"],
            GOOGLE_SHEETS_KEY,
        )

    return dict(row), [_pipe_summary(dict(pipe)) for pipe in pipe_rows]


async def _validated_pipe_ids(pipe_ids: list[int]) -> list[int]:
    normalized = sorted({int(pipe_id) for pipe_id in pipe_ids})

    if any(pipe_id <= 0 for pipe_id in normalized):
        raise HTTPException(400, "pipe_ids must contain positive connection IDs")
    if not normalized:
        return []

    async with db_connection() as db:
        rows = await db.fetch(
            """
            SELECT id
            FROM connections
            WHERE plugin = $1 AND id = ANY($2::bigint[])
            """,
            GOOGLE_SHEETS_KEY,
            normalized,
        )

    found = {int(row[0]) for row in rows}
    missing = sorted(set(normalized) - found)

    if missing:
        raise HTTPException(400, f"Unknown pipe IDs: {', '.join(map(str, missing))}")

    return normalized


async def _replace_memberships(
    db: asyncpg.Connection,
    collection_id: int,
    pipe_ids: list[int],
) -> None:
    await db.execute(
        "DELETE FROM collection_pipes WHERE collection_id = $1",
        collection_id,
    )

    if pipe_ids:
        await db.executemany(
            "INSERT INTO collection_pipes (collection_id, pipe_id) VALUES ($1, $2)",
            [(collection_id, pipe_id) for pipe_id in pipe_ids],
        )


def _collection_summary(
    row: dict[str, Any],
    pipes: list[dict[str, Any]],
) -> dict[str, Any]:
    table_count = sum(int(pipe.get("table_count") or 0) for pipe in pipes)
    cube_names = allowed_cube_names_for_pipe_ids({int(pipe["id"]) for pipe in pipes})

    return {
        **row,
        "pipe_ids": [int(pipe["id"]) for pipe in pipes],
        "pipes": pipes,
        "pipe_count": len(pipes),
        "table_count": table_count,
        "cube_count": len(cube_names) if cube_names else table_count,
        "mcp_path": f"/mcp/collections/{row['slug']}",
    }


def _pipe_summary(pipe: dict[str, Any]) -> dict[str, Any]:
    assets = _pipe_assets(pipe)
    return {
        "id": int(pipe["id"]),
        "name": pipe["name"],
        "slug": pipe["slug"],
        "status": pipe["status"],
        "last_synced_at": pipe.get("last_synced_at"),
        "destination_schema": pipe["slug"],
        "table_count": len(assets),
        "cube_count": len(assets),
    }


def _pipe_assets(pipe: dict[str, Any]) -> list[dict[str, Any]]:
    manifest_path = CONNECTION_CONFIG_DIR / f"{pipe['slug']}.manifest.yaml"

    if not manifest_path.is_file():
        return []

    try:
        parsed = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []

    raw_tables = parsed.get("tables") if isinstance(parsed, dict) else []
    assets: list[dict[str, Any]] = []

    for table in raw_tables if isinstance(raw_tables, list) else []:
        if not isinstance(table, dict) or not table.get("name"):
            continue

        table_name = str(table["name"])
        columns = table.get("columns")
        assets.append(
            {
                "pipe_id": int(pipe["id"]),
                "pipe_name": pipe["name"],
                "pipe_slug": pipe["slug"],
                "schema": pipe["slug"],
                "table": table_name,
                "column_count": len(columns) if isinstance(columns, list) else 0,
                "cube_name": f"{pipe['slug']}_{table_name}",
            }
        )

    return assets


def _definition_connection_ids(definition: dict[str, Any]) -> set[int]:
    meta = definition.get("meta")
    settra = meta.get("settra") if isinstance(meta, dict) else None

    if not isinstance(settra, dict):
        return set()

    metadata_sources = [settra]
    if isinstance(settra.get("overlay"), dict):
        metadata_sources.append(settra["overlay"])

    values: list[Any] = []
    for source in metadata_sources:
        if source.get("connection_id") is not None:
            values.append(source["connection_id"])
        if isinstance(source.get("connection_ids"), list):
            values.extend(source["connection_ids"])

    result: set[int] = set()
    for value in values:
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            continue

    return result


def _definition_dependencies(definition: dict[str, Any]) -> set[str]:
    dependencies: set[str] = set()

    cubes = definition.get("cubes")
    for item in cubes if isinstance(cubes, list) else []:
        if not isinstance(item, dict):
            continue
        join_path = item.get("join_path")
        if isinstance(join_path, str) and join_path.strip():
            dependencies.add(join_path.strip().split(".", 1)[0])

    joins = definition.get("joins")
    for item in joins if isinstance(joins, list) else []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            dependencies.add(item["name"].strip())

    extends = definition.get("extends")
    for value in extends if isinstance(extends, list) else [extends]:
        if isinstance(value, str) and value.strip():
            dependencies.add(value.strip().strip("{}").split(".", 1)[0])

    return {name for name in dependencies if name}


def _required_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise HTTPException(400, "Collection name is required")
    return normalized
