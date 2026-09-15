import copy
import hashlib

from typing import Any

import yaml

from app.collection_service import (
    get_collection,
    require_model_file_in_collection,
    validate_overlay_for_collection,
)
from app.cube.model import (
    create_model_file,
    delete_generated_model_file,
    list_model_files,
    read_model_file,
    update_model_file,
)
from app.errors import (
    InvalidOperationError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from app.semantic.catalog import authored_definition_index
from app.semantic.overlays import (
    generated_overlay_path,
    require_complete_overlay_manifest,
    semantic_overlay_write_lock,
    wait_for_compiled_model_names,
    wait_for_removed_model_names,
)
from app.semantic.relationships import (
    SUPPORTED_RELATIONSHIPS,
    build_relationship_catalog,
)
from app.cube.query import (
    execute_cube_query_payload,
    normalize_cube_query_payload,
    sentinel_mcp_cube_query,
)
from app.cube.projection import QueryResultProjectionInput, semantic_response_projector
from app.semantic.query import referenced_cube_names


def collection_overlay_path(path: str) -> str:
    try:
        return generated_overlay_path(path)
    except ValueError as exc:
        raise InvalidOperationError(str(exc)) from exc


async def execute_collection_query(
    collection_id: int, data: dict[str, Any]
) -> dict[str, Any]:
    collection = await get_collection(collection_id)
    query = normalize_cube_query_payload(data)

    if not isinstance(query, dict) or not referenced_cube_names(query):
        raise InvalidOperationError(
            "Query must reference at least one collection cube member"
        )

    executable, limit, offset = sentinel_mcp_cube_query(query)
    response = await execute_cube_query_payload(
        executable, allowed_names=set(collection["cube_names"])
    )

    return semantic_response_projector.query_result(
        QueryResultProjectionInput(response=response, limit=limit, offset=offset),
    )


async def collection_models(collection_id: int) -> dict[str, Any]:
    collection = await get_collection(collection_id)
    names = set(collection["cube_names"])
    definitions = authored_definition_index(allowed_names=names)

    return {
        "files": list_model_files(allowed_names=names),
        "cubes": [
            {
                "name": name,
                "title": source["definition"].get("title") or name,
                "source_type": source["source_type"],
                "dimensions": source["definition"].get("dimensions") or [],
            }
            for name, source in sorted(definitions.items())
            if source["definition"].get("sql_table")
        ],
    }


async def collection_model_file(collection_id: int, path: str) -> dict[str, Any]:
    collection = await get_collection(collection_id)
    file = read_model_file(path)
    require_model_file_in_collection(collection, file)

    return file


async def write_collection_overlay(
    collection_id: int,
    *,
    path: str,
    content: str,
    create: bool,
    expected_content: str | None = None,
) -> dict[str, Any]:
    collection = await get_collection(collection_id)

    async with semantic_overlay_write_lock:
        normalized = collection_overlay_path(path)
        previous_names: set[str] = set()

        if not create:
            previous = await collection_model_file(collection_id, normalized)
            previous_names = set(previous["cube_names"]) | set(previous["view_names"])

            if expected_content is not None and previous["content"] != expected_content:
                raise ResourceConflictError(
                    "This model was changed elsewhere. Reload before saving."
                )

        await validate_overlay_for_collection(collection["slug"], content)

        try:
            require_complete_overlay_manifest(content)
        except ValueError as exc:
            raise InvalidOperationError(str(exc)) from exc

        result = (
            create_model_file(normalized, content)
            if create
            else update_model_file(normalized, content)
        )
        result.pop("previous_content", None)
        file = result["file"]
        names = [*file["cube_names"], *file["view_names"]]
        result["cube"] = await wait_for_compiled_model_names(names)
        removed = previous_names - set(names)

        if removed:
            result["removal"] = await wait_for_removed_model_names(sorted(removed))

        return result


async def remove_collection_overlay(collection_id: int, path: str) -> dict[str, Any]:
    async with semantic_overlay_write_lock:
        normalized = collection_overlay_path(path)
        file = await collection_model_file(collection_id, normalized)
        result = delete_generated_model_file(normalized)
        result["cube"] = await wait_for_removed_model_names(
            [*file["cube_names"], *file["view_names"]],
        )

        return result


async def relationship_draft(
    collection_id: int,
    *,
    source_cube: str,
    target_cube: str,
    source_member: str,
    target_member: str,
    relationship: str,
    source_primary_key: str,
    target_primary_key: str,
    existing_id: str | None = None,
    remove: bool = False,
) -> dict[str, Any]:
    """Prepare a complete overlay replacement; never persist a join separately.

    Synchronized models remain generator-owned. Their first authored relationship
    creates collection-specific copies, reused by subsequent joins. Existing
    authored overlays retain their model names, metrics, views, and other joins.
    """
    collection = await get_collection(collection_id)
    allowed = set(collection["cube_names"])
    definitions = authored_definition_index(allowed_names=allowed)

    if source_cube == target_cube and not remove:
        raise InvalidOperationError("Choose two different tables for a relationship")
    if source_cube not in definitions or (
        target_cube not in definitions and not remove
    ):
        raise ResourceNotFoundError("Relationship table is outside this collection")

    source = definitions[source_cube]

    if source["source_type"] == "generated_connection" and not existing_id:
        path = collection_overlay_path(
            f"collections/{collection_id}/relationships.yaml"
        )

        try:
            file = await collection_model_file(collection_id, path)
        except ResourceNotFoundError:
            file = None
    elif source["source_type"] == "generated_overlay":
        path = collection_overlay_path(source["path"])
        file = await collection_model_file(collection_id, path)
    else:
        raise InvalidOperationError("This relationship is in a read-only model")

    parsed = yaml.safe_load(file["content"]) if file else {"cubes": []}
    cubes = parsed.setdefault("cubes", [])

    def editable_cube(name: str, primary_key: str) -> dict[str, Any]:
        original = definitions[name]

        if original["source_type"] == "generated_connection":
            digest = hashlib.sha256(f"{path}:{name}".encode()).hexdigest()[:16]
            authored_name = f"collection_{collection_id}_{digest}"
            current = next(
                (cube for cube in cubes if cube.get("name") == authored_name), None
            )

            if current is None:
                current = copy.deepcopy(original["definition"])
                current["name"] = authored_name
                current.pop("sql_alias", None)
                # Keep PostgreSQL aliases bounded even for long source members.
                current["sql_alias"] = f"c_{digest}"
                meta = current.setdefault("meta", {}).setdefault("settra", {})
                meta.update(
                    {
                        "source_type": "generated_overlay",
                        "source_cube": name,
                        "purpose": f"Relationships for {collection['name']}",
                        "requirement": "User-authored collection relationships",
                        "grain": "One row per selected unique row key",
                        "assumptions": [],
                        "evidence": [
                            {"source_cube": name, "source_path": original["path"]}
                        ],
                    }
                )
                cubes.append(current)
        else:
            current = next((cube for cube in cubes if cube.get("name") == name), None)

            if current is None:
                # Models in another overlay can be referenced, but not changed.
                current = original["definition"]
                declared_keys = {
                    dimension["name"]
                    for dimension in current.get("dimensions", [])
                    if dimension.get("primary_key")
                }

                if primary_key not in declared_keys:
                    raise InvalidOperationError(
                        "Edit the target model to declare its unique row key first"
                    )

                return current

        dimensions = current.get("dimensions") or []

        if primary_key not in {dimension.get("name") for dimension in dimensions}:
            raise InvalidOperationError(
                "Choose an existing dimension as the unique row key"
            )

        old_keys = {
            dimension["name"]
            for dimension in dimensions
            if dimension.get("primary_key")
        }

        if old_keys and old_keys != {primary_key}:
            raise InvalidOperationError(
                "Changing an existing primary key requires editing the complete model"
            )

        for dimension in dimensions:
            if dimension.get("name") == primary_key:
                dimension["primary_key"] = True

        return current

    if remove:
        source_model = next(
            (cube for cube in cubes if cube.get("name") == source_cube), None
        )

        if source_model is None:
            raise ResourceNotFoundError("Relationship source not found")
    else:
        if relationship not in SUPPORTED_RELATIONSHIPS:
            raise InvalidOperationError("Unsupported relationship cardinality")

        source_model = editable_cube(source_cube, source_primary_key)
        target_model = editable_cube(target_cube, target_primary_key)

        if source_model not in cubes:
            raise InvalidOperationError("The source model is read-only")

    joins = source_model.setdefault("joins", [])

    if existing_id:
        matches = [
            join for join in joins if f"{source_cube}:{join.get('name')}" == existing_id
        ]

        if len(matches) != 1:
            raise ResourceNotFoundError(
                "Relationship changed or could not be identified uniquely"
            )

        joins.remove(matches[0])
    if not remove:
        if any(join.get("name") == target_model["name"] for join in joins):
            raise ResourceConflictError("These tables already have a relationship")

        joins.append(
            {
                "name": target_model["name"],
                "relationship": relationship,
                "sql": f"{{CUBE}}.{source_member} = {{{target_model['name']}}}.{target_member}",
            }
        )

        candidate_definitions = {
            **definitions,
            **{
                cube["name"]: {
                    "path": path,
                    "source_type": "generated_overlay",
                    "definition": cube,
                }
                for cube in cubes
            },
        }
        candidate_names = allowed | set(candidate_definitions)
        catalog = build_relationship_catalog(
            allowed_names=candidate_names,
            definitions=candidate_definitions,
            compiled_names=candidate_names,
        )
        candidate = next(
            item
            for item in catalog["relationships"]
            if item["id"] == f"{source_model['name']}:{target_model['name']}"
        )

        if not candidate["valid"]:
            raise InvalidOperationError(
                " ".join(issue["message"] for issue in candidate["issues"])
            )

    meta = source_model.setdefault("meta", {}).setdefault("settra", {})
    manifest = meta.get("overlay") if isinstance(meta.get("overlay"), dict) else meta
    manifest["relationships"] = copy.deepcopy(joins)
    content = yaml.safe_dump(parsed, sort_keys=False, allow_unicode=True)

    await validate_overlay_for_collection(collection["slug"], content)
    return {
        "path": path,
        "content": content,
        "create": file is None,
        "expected_content": file["content"] if file else None,
    }
