import re

from typing import Any

from app.cube.client import CubeAPIError, load_cube_meta
from app.cube.query import execute_cube_query_payload
from app.errors import ApplicationError
from app.semantic.catalog import (
    authored_definition_index,
    definition_connection_ids,
)

SUPPORTED_RELATIONSHIPS = {"one_to_one", "one_to_many", "many_to_one"}
_MEMBER_NAME = r"[A-Za-z][A-Za-z0-9_]*"
_SQL_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_$]*"


async def relationship_catalog(allowed_names: set[str]) -> dict[str, Any]:
    """Return collection-scoped joins from authored Cube definitions.

    Cube's metadata endpoint does not consistently expose joins. The authored
    model is therefore the canonical source for relationship discovery, while
    compiled metadata reports whether both participating models are active.
    """

    definitions = authored_definition_index(allowed_names=allowed_names)
    compiled_names: set[str] = set()
    compiler_id: str | None = None
    metadata_error: str | None = None

    try:
        meta = await load_cube_meta()
        cubes = meta.get("cubes") if isinstance(meta, dict) else []
        compiled_names = (
            {
                str(cube["name"])
                for cube in cubes
                if isinstance(cube, dict) and isinstance(cube.get("name"), str)
            }
            if isinstance(cubes, list)
            else set()
        )

        if isinstance(meta, dict) and isinstance(meta.get("compilerId"), str):
            compiler_id = meta["compilerId"]
    except CubeAPIError:
        metadata_error = "Cube metadata is currently unavailable"

    return build_relationship_catalog(
        allowed_names=allowed_names,
        definitions=definitions,
        compiled_names=compiled_names,
        compiler_id=compiler_id,
        metadata_error=metadata_error,
    )


def build_relationship_catalog(
    *,
    allowed_names: set[str],
    definitions: dict[str, dict[str, Any]],
    compiled_names: set[str],
    compiler_id: str | None = None,
    metadata_error: str | None = None,
) -> dict[str, Any]:
    relationships: list[dict[str, Any]] = []

    for source_name in sorted(allowed_names):
        authored = definitions.get(source_name)

        if not isinstance(authored, dict):
            continue

        definition = authored.get("definition")

        if not isinstance(definition, dict):
            continue

        joins = definition.get("joins")

        if not isinstance(joins, list):
            continue

        for join_index, join in enumerate(joins):
            if not isinstance(join, dict):
                continue

            target_name = join.get("name")

            if not isinstance(target_name, str) or not target_name.strip():
                continue

            target_name = target_name.strip()
            relationship = (
                join.get("relationship")
                if isinstance(join.get("relationship"), str)
                else ""
            )
            sql = join.get("sql") if isinstance(join.get("sql"), str) else ""
            source_member, target_member = relationship_members(sql, target_name)
            source_definition = _definition(definitions.get(source_name))
            target_definition = _definition(definitions.get(target_name))
            probe_source_member, probe_target_member = _probe_members(
                source_definition,
                target_definition,
                source_member=source_member,
                target_member=target_member,
            )
            source_table = _sql_table(definition)
            target_table = _sql_table(target_definition)
            source_connection_ids = sorted(definition_connection_ids(definition))
            target_connection_ids = sorted(definition_connection_ids(target_definition))
            issues = _relationship_issues(
                source_name=source_name,
                target_name=target_name,
                relationship=relationship,
                sql=sql,
                source_member=source_member,
                target_member=target_member,
                allowed_names=allowed_names,
                definitions=definitions,
            )
            models_compiled = {
                source_name,
                target_name,
            }.issubset(compiled_names)

            relationships.append(
                {
                    "id": f"{source_name}:{target_name}",
                    "source_cube": source_name,
                    "target_cube": target_name,
                    "relationship": relationship,
                    "sql": sql,
                    "source_member": source_member,
                    "target_member": target_member,
                    "probe_source_member": probe_source_member,
                    "probe_target_member": probe_target_member,
                    "source_connection_id": (
                        source_connection_ids[0]
                        if len(source_connection_ids) == 1
                        else None
                    ),
                    "target_connection_id": (
                        target_connection_ids[0]
                        if len(target_connection_ids) == 1
                        else None
                    ),
                    "source_schema": source_table[0] if source_table else None,
                    "source_table": source_table[1] if source_table else None,
                    "source_column": _member_column(definition, source_member),
                    "target_schema": target_table[0] if target_table else None,
                    "target_table": target_table[1] if target_table else None,
                    "target_column": _member_column(
                        target_definition,
                        target_member,
                    ),
                    "source_path": authored.get("path"),
                    "source_type": authored.get("source_type"),
                    "models_compiled": models_compiled,
                    "valid": not issues,
                    "issues": issues,
                    "position": join_index,
                }
            )

    relationships.sort(
        key=lambda item: (
            str(item["source_cube"]),
            int(item["position"]),
            str(item["target_cube"]),
        )
    )
    for item in relationships:
        item.pop("position", None)

    invalid_count = sum(not item["valid"] for item in relationships)
    uncompiled_count = sum(not item["models_compiled"] for item in relationships)

    return {
        "relationships": relationships,
        "relationship_count": len(relationships),
        "valid": invalid_count == 0
        and metadata_error is None
        and uncompiled_count == 0,
        "invalid_count": invalid_count,
        "uncompiled_count": uncompiled_count,
        "cube": {
            "connected": metadata_error is None,
            "compiler_id": compiler_id,
            "error": metadata_error,
        },
    }


async def test_relationship_catalog(
    catalog: dict[str, Any],
    *,
    allowed_names: set[str],
) -> dict[str, Any]:
    """Run a bounded cross-cube query for every structurally valid join."""

    results: list[dict[str, Any]] = []

    for relationship in catalog.get("relationships", []):
        result = {
            "id": relationship["id"],
            "source_cube": relationship["source_cube"],
            "target_cube": relationship["target_cube"],
            "valid": False,
            "row_count": 0,
            "error": None,
        }
        source_member = relationship.get("probe_source_member") or relationship.get(
            "source_member"
        )
        target_member = relationship.get("probe_target_member") or relationship.get(
            "target_member"
        )

        if not relationship.get("valid"):
            result["error"] = "Relationship definition is invalid"
        elif not relationship.get("models_compiled"):
            result["error"] = "Relationship models are not compiled"
        elif not isinstance(source_member, str) or not isinstance(target_member, str):
            result["error"] = "Relationship keys could not be resolved"
        else:
            query = {
                "dimensions": [
                    f"{relationship['source_cube']}.{source_member}",
                    f"{relationship['target_cube']}.{target_member}",
                ],
                "limit": 1,
            }
            try:
                response = await execute_cube_query_payload(
                    {"query": query},
                    allowed_names=allowed_names,
                )
                rows = response.get("data")

                if not isinstance(rows, list):
                    result["error"] = "Cube returned an unsupported result shape"
                else:
                    result["valid"] = True
                    result["row_count"] = len(rows)
            except (ApplicationError, CubeAPIError, ValueError) as exc:
                result["error"] = str(exc)

        results.append(result)

    tested_count = sum(item["valid"] for item in results)

    return {
        "valid": bool(catalog.get("valid")) and tested_count == len(results),
        "relationship_count": len(results),
        "tested_count": tested_count,
        "relationships": results,
    }


def relationship_members(sql: str, target_name: str) -> tuple[str | None, str | None]:
    if not sql.strip():
        return None, None

    cube_to_target = re.fullmatch(
        rf"\s*\{{CUBE\}}\.({_MEMBER_NAME})\s*=\s*"
        rf"\{{{re.escape(target_name)}\}}\.({_MEMBER_NAME})\s*",
        sql,
    )

    if cube_to_target:
        return cube_to_target.group(1), cube_to_target.group(2)

    target_to_cube = re.fullmatch(
        rf"\s*\{{{re.escape(target_name)}\}}\.({_MEMBER_NAME})\s*=\s*"
        rf"\{{CUBE\}}\.({_MEMBER_NAME})\s*",
        sql,
    )

    if target_to_cube:
        return target_to_cube.group(2), target_to_cube.group(1)

    return None, None


def _relationship_issues(
    *,
    source_name: str,
    target_name: str,
    relationship: str,
    sql: str,
    source_member: str | None,
    target_member: str | None,
    allowed_names: set[str],
    definitions: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []

    if target_name not in allowed_names:
        issues.append(
            {
                "code": "TARGET_OUTSIDE_COLLECTION",
                "message": f"Target cube '{target_name}' is outside this collection.",
            }
        )
    if source_name == target_name:
        issues.append(
            {
                "code": "SELF_RELATIONSHIP",
                "message": "A relationship must connect two different cubes.",
            }
        )
    if relationship not in SUPPORTED_RELATIONSHIPS:
        issues.append(
            {
                "code": "INVALID_CARDINALITY",
                "message": "Relationship must be one_to_one, one_to_many, or many_to_one.",
            }
        )
    if not sql.strip():
        issues.append(
            {
                "code": "MISSING_JOIN_SQL",
                "message": "Relationship join SQL is required.",
            }
        )
    elif source_member is None or target_member is None:
        issues.append(
            {
                "code": "UNSUPPORTED_JOIN_EXPRESSION",
                "message": (
                    "Relationship joins must compare one source member with one "
                    "target member using equality."
                ),
            }
        )

    source_definition = _definition(definitions.get(source_name))
    target_definition = _definition(definitions.get(target_name))
    source_dimensions = _dimension_names(source_definition)
    target_dimensions = _dimension_names(target_definition)

    if (
        source_definition
        and source_member is not None
        and source_member not in source_dimensions
    ):
        issues.append(
            {
                "code": "UNKNOWN_SOURCE_MEMBER",
                "message": f"Source dimension '{source_name}.{source_member}' was not found.",
            }
        )
    if (
        target_definition
        and target_member is not None
        and target_member not in target_dimensions
    ):
        issues.append(
            {
                "code": "UNKNOWN_TARGET_MEMBER",
                "message": f"Target dimension '{target_name}.{target_member}' was not found.",
            }
        )

    if relationship in {"many_to_one", "one_to_one"} and target_definition:
        if target_member not in _primary_key_names(target_definition):
            issues.append(
                {
                    "code": "TARGET_KEY_NOT_PRIMARY",
                    "message": (
                        f"Target dimension '{target_name}.{target_member}' must be "
                        "declared as a primary key for this cardinality."
                    ),
                }
            )
    if relationship in {"one_to_many", "one_to_one"} and source_definition:
        if source_member not in _primary_key_names(source_definition):
            issues.append(
                {
                    "code": "SOURCE_KEY_NOT_PRIMARY",
                    "message": (
                        f"Source dimension '{source_name}.{source_member}' must be "
                        "declared as a primary key for this cardinality."
                    ),
                }
            )

    return issues


def _definition(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}

    definition = source.get("definition")

    return definition if isinstance(definition, dict) else {}


def _dimension_names(definition: dict[str, Any]) -> set[str]:
    dimensions = definition.get("dimensions")

    if not isinstance(dimensions, list):
        return set()

    return {
        str(item["name"])
        for item in dimensions
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }


def _primary_key_names(definition: dict[str, Any]) -> set[str]:
    dimensions = definition.get("dimensions")

    if not isinstance(dimensions, list):
        return set()

    return {
        str(item["name"])
        for item in dimensions
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and item.get("primary_key") is True
    }


def _probe_members(
    source_definition: dict[str, Any],
    target_definition: dict[str, Any],
    *,
    source_member: str | None,
    target_member: str | None,
) -> tuple[str | None, str | None]:
    source_names = _ordered_dimension_names(source_definition)
    target_names = _ordered_dimension_names(target_definition)
    source_set = set(source_names)
    target_set = set(target_names)

    for source_name in source_names:
        if source_name in target_set:
            continue
        for target_name in target_names:
            if target_name not in source_set:
                return source_name, target_name

    for source_name in source_names:
        for target_name in target_names:
            if source_name != target_name:
                return source_name, target_name

    return source_member, target_member


def _ordered_dimension_names(definition: dict[str, Any]) -> list[str]:
    dimensions = definition.get("dimensions")

    if not isinstance(dimensions, list):
        return []

    return [
        str(item["name"])
        for item in dimensions
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    ]


def _sql_table(definition: dict[str, Any]) -> tuple[str, str] | None:
    sql_table = definition.get("sql_table")

    if not isinstance(sql_table, str):
        return None

    match = re.fullmatch(
        rf'\s*(?:"([^"]+)"|({_SQL_IDENTIFIER}))\s*\.\s*'
        rf'(?:"([^"]+)"|({_SQL_IDENTIFIER}))\s*',
        sql_table,
    )

    if not match:
        return None

    return match.group(1) or match.group(2), match.group(3) or match.group(4)


def _member_column(
    definition: dict[str, Any],
    member_name: str | None,
) -> str | None:
    if member_name is None:
        return None

    dimensions = definition.get("dimensions")

    if not isinstance(dimensions, list):
        return None

    dimension = next(
        (
            item
            for item in dimensions
            if isinstance(item, dict) and item.get("name") == member_name
        ),
        None,
    )
    sql = dimension.get("sql") if isinstance(dimension, dict) else None

    if not isinstance(sql, str):
        return None

    match = re.fullmatch(
        rf'\s*(?:\{{CUBE\}}\.)?(?:"([^"]+)"|({_SQL_IDENTIFIER}))\s*',
        sql,
    )

    return (match.group(1) or match.group(2)) if match else None
