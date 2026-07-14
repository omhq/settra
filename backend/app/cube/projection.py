import re

from typing import Any
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CUBE_CATALOG_DESCRIPTION_MAX_CHARS = 160
CUBE_META_DESCRIPTION_MAX_CHARS = 300
PROFILE_DESCRIPTION_MAX_CHARS = 300
DATE_BUCKET_GRANULARITIES = {"day", "week", "month", "quarter", "year"}
DATE_ONLY_SEMANTIC_TYPES = {
    "business_date",
    "date",
    "date_only",
    "timezone_neutral_date",
    "timezone-neutral-date",
}
NUMERIC_MEMBER_TYPES = {
    "avg",
    "count",
    "count_distinct",
    "countDistinct",
    "count_distinct_approx",
    "countDistinctApprox",
    "max",
    "min",
    "number",
    "sum",
}
DATE_ONLY_MEMBER_NAME_RE = re.compile(
    r"(?:^|[._\s-])(?:date|day|week|month|quarter|year)s?(?:$|[._\s-])",
    re.IGNORECASE,
)
DECIMAL_TEXT_RE = re.compile(r"^[+-]?(?:\d+|\d+\.\d+|\.\d+)$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class CubeCatalogProjectionInput:
    cubes: list[dict[str, Any]]
    source_definitions: dict[str, Any]
    requested_collections: list[str]
    member_limit: int
    next_cursor: int | None
    total: int
    authored_definitions: dict[str, Any] | None = None


@dataclass(frozen=True)
class CubeProjectionInput:
    compiled: dict[str, Any]
    authored_source: dict[str, Any] | None = None


@dataclass(frozen=True)
class CubeMetaProjectionInput:
    cubes: list[dict[str, Any]]
    requested_collections: list[str]
    member_limit: int
    next_cursor: int | None
    total: int
    authored_definitions: dict[str, Any] | None = None
    source_definitions: dict[str, Any] | None = None


@dataclass(frozen=True)
class OverlayProjectionInput:
    path: str
    content: str
    model_names: list[str]
    manifest: dict[str, Any]
    compile_status: dict[str, Any]
    parse_error: str | None = None


@dataclass(frozen=True)
class OverlayListItemProjectionInput:
    path: str
    model_names: list[str]
    manifest: dict[str, Any]
    compile_status: dict[str, Any]
    parse_error: str | None = None


@dataclass(frozen=True)
class OverlayListProjectionInput:
    overlays: list[OverlayListItemProjectionInput]
    error: str | None = None


@dataclass(frozen=True)
class OverlayCreateProjectionInput:
    created: bool
    path: str
    model_names: list[str]
    manifest: dict[str, Any]
    compile_status: dict[str, Any]
    deprecated: bool = False


@dataclass(frozen=True)
class OverlayUpdateProjectionInput:
    updated: bool
    path: str
    models_added: list[str]
    models_changed: list[str]
    models_removed: list[str]
    compile_status: dict[str, Any]
    diff: str
    include_diff: bool = False
    removal_status: dict[str, Any] | None = None


@dataclass(frozen=True)
class OverlayValidationProjectionInput:
    result: dict[str, Any]


@dataclass(frozen=True)
class QueryResultProjectionInput:
    response: dict[str, Any]


@dataclass(frozen=True)
class TableSampleProjectionInput:
    response: dict[str, Any]


@dataclass(frozen=True)
class TableProfileProjectionInput:
    response: dict[str, Any]
    include_descriptions: bool = False


class SemanticResponseProjector:
    """Shape semantic MCP responses around one authoritative representation."""

    def cube_catalog(self, value: CubeCatalogProjectionInput) -> dict[str, Any]:
        return {
            "cubes": [
                _catalog_cube_summary(
                    cube,
                    value.source_definitions.get(str(cube.get("name"))),
                    (value.authored_definitions or {}).get(str(cube.get("name"))),
                    requested_collections=value.requested_collections,
                    member_limit=value.member_limit,
                )
                for cube in value.cubes
            ],
            "page": {
                "next_cursor": value.next_cursor,
                "total": value.total,
            },
        }

    def cube(self, value: CubeProjectionInput) -> dict[str, Any]:
        cube = value.compiled
        authored_source = value.authored_source
        name = str(cube.get("name") or "")
        definition = (
            authored_source.get("definition")
            if isinstance(authored_source, dict)
            and isinstance(authored_source.get("definition"), dict)
            else {}
        )
        result: dict[str, Any] = {"name": name}
        description = _summary_description(
            definition.get("description") or cube.get("description")
        )

        if description:
            result["description"] = description

        cube_type = cube.get("type")

        if isinstance(cube_type, str) and cube_type not in {"", "cube"}:
            result["type"] = cube_type

        if not description:
            title = _meaningful_title(
                definition.get("title") or cube.get("title"),
                context=name,
            )

            if title:
                result["title"] = title

        source = _compact_cube_source(authored_source, definition)

        if source:
            result["source"] = source

        _add_non_default_access(result, definition, cube)

        for collection in ("measures", "dimensions"):
            members = _compact_cube_members(
                name,
                collection,
                definition.get(collection),
                cube.get(collection),
            )

            if members:
                result[collection] = members

        segments = _compact_cube_segments(
            name,
            definition.get("segments"),
            cube.get("segments"),
        )

        if segments:
            result["segments"] = segments

        relationships = _compact_cube_relationships(
            name,
            definition.get("joins"),
            cube.get("joins"),
        )

        if relationships:
            result["relationships"] = relationships

        hierarchies = _compact_cube_hierarchies(
            name,
            definition.get("hierarchies"),
        )

        if hierarchies:
            result["hierarchies"] = hierarchies

        return result

    def cube_meta(self, value: CubeMetaProjectionInput) -> dict[str, Any]:
        return {
            "cubes": [
                _compact_meta_cube(
                    cube,
                    authored_source=(value.authored_definitions or {}).get(
                        str(cube.get("name"))
                    ),
                    source_definition=(value.source_definitions or {}).get(
                        str(cube.get("name"))
                    ),
                    requested_collections=value.requested_collections,
                    member_limit=value.member_limit,
                )
                for cube in value.cubes
            ],
            "page": {
                "next_cursor": value.next_cursor,
                "total": value.total,
            },
        }

    def overlay(self, value: OverlayProjectionInput) -> dict[str, Any]:
        compile_status = value.compile_status
        declared_models = list(dict.fromkeys(value.model_names))
        compiled_models = compile_status.get("compiled_names")
        missing_models = compile_status.get("missing_names")
        compile_result: dict[str, Any] = {
            "status": compile_status.get("status") or "unknown",
            "models": declared_models,
        }

        if (
            isinstance(compiled_models, list)
            and compiled_models
            and set(compiled_models) != set(declared_models)
        ):
            compile_result["compiled_models"] = compiled_models
        if isinstance(missing_models, list) and missing_models:
            compile_result["missing_models"] = missing_models

        compile_error = value.parse_error or compile_status.get("error")

        if compile_error:
            compile_result["error"] = compile_error

        missing_fields = sorted(
            {
                field
                for model in value.manifest.get("models", [])
                if isinstance(model, dict)
                for field in model.get("missing_manifest_fields", [])
                if isinstance(field, str)
            }
        )

        return {
            "path": value.path,
            "content": value.content,
            "compile": compile_result,
            "manifest": {
                "status": value.manifest.get("status") or "missing",
                "missing_fields": missing_fields,
            },
        }

    def overlay_list(self, value: OverlayListProjectionInput) -> dict[str, Any]:
        overlays: list[dict[str, Any]] = []

        for item in value.overlays:
            summary: dict[str, Any] = {
                "path": item.path,
                "models": list(dict.fromkeys(item.model_names)),
                "status": item.compile_status.get("status") or "unknown",
                "manifest_status": item.manifest.get("status") or "missing",
            }
            purpose = item.manifest.get("purpose")
            purpose_summary = _summary_description(purpose)

            if purpose_summary:
                summary["purpose"] = purpose_summary

            error = item.parse_error or item.compile_status.get("error")

            if error:
                summary["error"] = error

            overlays.append(summary)

        result: dict[str, Any] = {
            "overlays": overlays,
            "count": len(overlays),
        }

        if value.error:
            result["error"] = value.error

        return result

    def overlay_create(self, value: OverlayCreateProjectionInput) -> dict[str, Any]:
        compile_status = _compile_status_label(value.compile_status)
        result: dict[str, Any] = {
            "saved" if value.deprecated else "created": value.created,
            "path": value.path,
            "models": list(dict.fromkeys(value.model_names)),
            "manifest_status": value.manifest.get("status") or "missing",
            "compile_status": compile_status,
            "warnings": [],
        }

        if value.deprecated:
            result["deprecated"] = True

        if compile_status != "compiled":
            result["warnings"] = [
                {
                    "code": "COMPILE_INCOMPLETE",
                    "message": "Cube did not compile all saved overlay models.",
                }
            ]
            result["compiler"] = _compact_diagnostics(value.compile_status)

        return result

    def overlay_update(self, value: OverlayUpdateProjectionInput) -> dict[str, Any]:
        compile_status = _compile_status_label(value.compile_status)
        result: dict[str, Any] = {
            "updated": value.updated,
            "path": value.path,
            "models_added": sorted(set(value.models_added)),
            "models_changed": sorted(set(value.models_changed)),
            "models_removed": sorted(set(value.models_removed)),
            "compile_status": compile_status,
            "diff_summary": _diff_summary(value.diff),
        }

        if value.include_diff:
            result["diff"] = value.diff
        if compile_status != "compiled":
            result["compiler"] = _compact_diagnostics(value.compile_status)
        if value.removal_status and not value.removal_status.get("removed"):
            result["removal"] = _compact_diagnostics(value.removal_status)

        return result

    def overlay_validation(
        self,
        value: OverlayValidationProjectionInput,
    ) -> dict[str, Any]:
        raw = value.result
        manifest = raw.get("manifest") if isinstance(raw.get("manifest"), dict) else {}
        cube = raw.get("cube") if isinstance(raw.get("cube"), dict) else {}
        cleanup = raw.get("cleanup") if isinstance(raw.get("cleanup"), dict) else {}
        valid = bool(raw.get("valid"))
        ready_to_save = bool(raw.get("ready_to_save"))
        result: dict[str, Any] = {
            "valid": valid,
            "ready_to_save": ready_to_save,
            "models": [
                name for name in raw.get("declared_cubes", []) if isinstance(name, str)
            ],
            "compile_status": _validation_compile_status(raw, cube, cleanup),
            "manifest_status": manifest.get("status") or "missing",
            "test_results": [
                _compact_validation_test(test)
                for test in raw.get("test_queries", [])
                if isinstance(test, dict)
            ],
            "warnings": (
                raw.get("warnings") if isinstance(raw.get("warnings"), list) else []
            ),
        }
        missing_fields = _manifest_missing_fields(manifest)

        if missing_fields:
            result["missing_manifest_fields"] = missing_fields

        errors = raw.get("errors") if isinstance(raw.get("errors"), list) else []

        if errors:
            result["errors"] = errors

        if not valid:
            compiler = _compact_diagnostics(cube)

            if _meaningful_compiler_diagnostics(compiler):
                result["compiler"] = compiler

            compact_cleanup = _compact_diagnostics(cleanup)

            if _failed_cleanup(compact_cleanup):
                result["cleanup"] = compact_cleanup

            result["diagnostics"] = {
                key: raw[key]
                for key in (
                    "proposed_path",
                    "referenced_cubes",
                    "queried_cubes",
                    "grain",
                    "evidence",
                )
                if raw.get(key) not in (None, [], {})
            }

        return result

    def query_result(self, value: QueryResultProjectionInput) -> dict[str, Any]:
        response = value.response
        data = response.get("data")
        rows = data if isinstance(data, list) else []
        member_hints = _query_result_member_hints(response)
        projected_rows = [
            _compact_query_row(row, member_hints) if isinstance(row, dict) else row
            for row in rows
        ]
        result: dict[str, Any] = {
            "data": projected_rows,
            "row_count": len(projected_rows),
        }
        cube_response = response.get("cube")
        total = cube_response.get("total") if isinstance(cube_response, dict) else None

        if isinstance(total, (int, float)) and not isinstance(total, bool):
            result["total"] = total

        return result

    def table_sample(self, value: TableSampleProjectionInput) -> dict[str, Any]:
        response = value.response
        raw_columns = response.get("columns")
        columns = [
            column["name"]
            for column in (raw_columns if isinstance(raw_columns, list) else [])
            if isinstance(column, dict) and isinstance(column.get("name"), str)
        ]
        raw_rows = response.get("rows")
        object_rows = raw_rows if isinstance(raw_rows, list) else []
        rows = [
            [row.get(column) for column in columns]
            for row in object_rows
            if isinstance(row, dict)
        ]
        truncated_values = [
            column
            for column in response.get("truncated_values", [])
            if isinstance(column, str) and column in columns
        ]
        result: dict[str, Any] = {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }

        if truncated_values:
            result["truncated"] = True
            result["truncated_values"] = list(dict.fromkeys(truncated_values))

        return result

    def table_profile(self, value: TableProfileProjectionInput) -> dict[str, Any]:
        response = value.response
        sampled_rows = response.get("sampled_row_count")
        raw_columns = response.get("columns")
        columns = raw_columns if isinstance(raw_columns, list) else []

        return {
            "sampled_rows": (
                sampled_rows
                if isinstance(sampled_rows, int) and not isinstance(sampled_rows, bool)
                else 0
            ),
            "columns": {
                column["name"]: _compact_profile_column(
                    column,
                    include_description=value.include_descriptions,
                )
                for column in columns
                if isinstance(column, dict)
                and isinstance(column.get("name"), str)
                and column["name"]
            },
        }


semantic_response_projector = SemanticResponseProjector()


def _authored_definition(authored_source: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(authored_source, dict) and isinstance(
        authored_source.get("definition"), dict
    ):
        return authored_source["definition"]

    return {}


def _effective_authored_definition(
    authored_source: dict[str, Any] | None,
    source_definition: dict[str, Any] | None,
) -> dict[str, Any]:
    authored_definition = dict(_authored_definition(authored_source))
    source_projection = _source_definition_as_authored(source_definition)

    if not authored_definition:
        return source_projection

    if (
        not authored_definition.get("joins")
        and isinstance(source_projection.get("joins"), list)
        and source_projection["joins"]
    ):
        authored_definition["joins"] = source_projection["joins"]

    return authored_definition


def _source_definition_as_authored(
    source_definition: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(source_definition, dict):
        return {}

    joins = source_definition.get("joins")

    if not isinstance(joins, dict) or not joins:
        return {}

    return {
        "joins": [
            {"name": name, **detail}
            for name, detail in joins.items()
            if isinstance(name, str) and isinstance(detail, dict)
        ]
    }


def _projected_collection_items(
    cube_name: str,
    cube: dict[str, Any],
    authored_definition: dict[str, Any],
    collection: str,
) -> list[Any]:
    compiled = cube.get(collection)
    compiled_items = compiled if isinstance(compiled, list) else []

    if collection != "joins":
        return compiled_items

    relationships = _compact_cube_relationships(
        cube_name,
        authored_definition.get("joins"),
        compiled_items,
    )

    return [
        {"name": name, **relationship} for name, relationship in relationships.items()
    ]


def _compact_meta_cube(
    cube: dict[str, Any],
    *,
    authored_source: dict[str, Any] | None = None,
    source_definition: dict[str, Any] | None = None,
    requested_collections: list[str],
    member_limit: int,
) -> dict[str, Any]:
    cube_name = str(cube.get("name") or "")
    authored_definition = _effective_authored_definition(
        authored_source,
        source_definition,
    )
    result: dict[str, Any] = {"name": cube_name}

    for key in ("title", "description", "connectedComponent"):
        value = _compact_meta_value(cube.get(key), cube_name=cube_name, key=key)

        if value not in (None, "", [], {}):
            result[key] = value

    cube_type = cube.get("type")

    if isinstance(cube_type, str) and cube_type not in {"", "cube"}:
        result["type"] = cube_type
    if cube.get("public") is False:
        result["public"] = False
    if cube.get("isVisible") is False:
        result["isVisible"] = False

    collection_counts = {}

    for name in (
        "measures",
        "dimensions",
        "segments",
        "joins",
        "hierarchies",
        "folders",
        "nestedFolders",
    ):
        value = _projected_collection_items(cube_name, cube, authored_definition, name)

        if value:
            collection_counts[name] = len(value)

    if collection_counts:
        result["collection_counts"] = collection_counts

    collection_page: dict[str, dict[str, int]] = {}

    for name in requested_collections:
        value = _projected_collection_items(cube_name, cube, authored_definition, name)

        if isinstance(value, list):
            compact_items = [
                compact
                for item in value[:member_limit]
                if (
                    compact := _compact_meta_value(
                        item,
                        cube_name=cube_name,
                        key=name,
                    )
                )
                not in (None, "", [], {})
            ]

            if compact_items:
                result[name] = compact_items
            if len(value) > member_limit:
                collection_page[name] = {"total": len(value)}
        else:
            compact_value = _compact_meta_value(
                value,
                cube_name=cube_name,
                key=name,
            )

            if compact_value not in (None, "", [], {}):
                result[name] = compact_value

    if collection_page:
        result["collection_page"] = collection_page

    return result


def _compact_meta_value(value: Any, *, cube_name: str, key: str) -> Any:
    if value is None:
        return None
    if key in {"public", "isVisible", "suggestFilterValues"} and value is True:
        return None
    if (
        key
        in {
            "primaryKey",
            "cumulative",
            "cumulativeTotal",
        }
        and value is False
    ):
        return None
    if isinstance(value, str):
        if key in {
            "name",
            "drillMembers",
            "levels",
            "members",
            "measures",
            "dimensions",
            "segments",
        }:
            return _local_member_name(value, cube_name)
        if key in {"description", "title", "shortTitle"}:
            return _limit_text(_clean_text(value), CUBE_META_DESCRIPTION_MAX_CHARS)

        return value
    if isinstance(value, list):
        compact = [
            item
            for child in value
            if (
                item := _compact_meta_value(
                    child,
                    cube_name=cube_name,
                    key=key,
                )
            )
            not in (None, "", [], {})
        ]

        return compact or None
    if isinstance(value, dict):
        compact = {
            child_key: child_value
            for child_key, child in value.items()
            if (
                child_value := _compact_meta_value(
                    child,
                    cube_name=cube_name,
                    key=child_key,
                )
            )
            not in (None, "", [], {})
        }

        if compact.get("shortTitle") == compact.get("title"):
            compact.pop("shortTitle", None)

        return compact or None

    return value


def _catalog_cube_summary(
    cube: dict[str, Any],
    source_definition: dict[str, Any] | None,
    authored_source: dict[str, Any] | None,
    *,
    requested_collections: list[str],
    member_limit: int,
) -> dict[str, Any]:
    cube_name = str(cube.get("name") or "")
    authored_definition = _effective_authored_definition(
        authored_source,
        source_definition,
    )
    result: dict[str, Any] = {"name": cube_name}
    title = cube.get("title")

    if isinstance(title, str) and title.strip():
        result["title"] = title.strip()

    description = _summary_description(cube.get("description"))

    if description:
        result["description"] = _limit_text(
            description,
            CUBE_CATALOG_DESCRIPTION_MAX_CHARS,
        )

    cube_type = cube.get("type")

    if isinstance(cube_type, str) and cube_type not in {"", "cube"}:
        result["type"] = cube_type

    result["members"] = {
        collection: len(
            _projected_collection_items(
                cube_name,
                cube,
                authored_definition,
                collection,
            )
        )
        for collection in ("measures", "dimensions", "segments", "joins")
    }
    source = _catalog_source_label(source_definition)

    if source:
        result["source"] = source

    for collection in requested_collections:
        members = _projected_collection_items(
            cube_name,
            cube,
            authored_definition,
            collection,
        )
        result[collection] = [
            _catalog_member_summary(cube_name, collection, member)
            for member in members[:member_limit]
        ]

    return result


def _catalog_member_summary(
    cube_name: str,
    collection: str,
    member: Any,
) -> dict[str, Any]:
    if not isinstance(member, dict):
        return {"name": _local_member_name(member, cube_name)}

    result: dict[str, Any] = {"name": _local_member_name(member.get("name"), cube_name)}

    if collection == "joins":
        if member.get("relationship"):
            result["relationship"] = member["relationship"]

        join_type = member.get("joinType") or member.get("join_type")

        if join_type:
            result["join_type"] = join_type
        if isinstance(member.get("sql"), str) and member["sql"].strip():
            result["sql"] = _limit_text(
                member["sql"].strip(),
                CUBE_META_DESCRIPTION_MAX_CHARS,
            )

        return result

    member_type = member.get("aggType") or member.get("type")

    if member_type:
        result["type"] = member_type

    description = _summary_description(member.get("description"))

    if description:
        result["description"] = _limit_text(
            description,
            CUBE_CATALOG_DESCRIPTION_MAX_CHARS,
        )

    return result


def _catalog_source_label(source_definition: dict[str, Any] | None) -> str | None:
    if not isinstance(source_definition, dict):
        return None

    path = source_definition.get("path")

    if isinstance(path, str) and path.strip():
        filename = path.strip().rsplit("/", 1)[-1]

        return filename.rsplit(".", 1)[0]

    source_type = source_definition.get("source_type")

    return source_type if isinstance(source_type, str) and source_type else None


def _compact_cube_source(
    authored_source: dict[str, Any] | None,
    definition: dict[str, Any],
) -> dict[str, Any]:
    source: dict[str, Any] = {}

    if isinstance(authored_source, dict):
        if authored_source.get("source_type"):
            source["type"] = authored_source["source_type"]
        if authored_source.get("path"):
            source["path"] = authored_source["path"]

    meta = definition.get("meta")
    settra = meta.get("settra") if isinstance(meta, dict) else None

    if isinstance(settra, dict) and settra.get("connection_id") is not None:
        source["connection_id"] = settra["connection_id"]

    sql_table = definition.get("sql_table")

    if isinstance(sql_table, str) and sql_table.strip():
        source["table"] = _normalize_sql_table(sql_table)

    sql = definition.get("sql")

    if isinstance(sql, str) and sql.strip():
        source["sql"] = sql.strip()

    return source


def _compact_cube_members(
    cube_name: str,
    collection: str,
    authored_members: Any,
    compiled_members: Any,
) -> dict[str, Any]:
    authored = _member_index(authored_members, cube_name)
    compiled = _member_index(compiled_members, cube_name)
    names = [*authored, *(name for name in compiled if name not in authored)]

    return {
        name: _compact_cube_member(
            cube_name,
            name,
            collection,
            authored.get(name, {}),
            compiled.get(name, {}),
        )
        for name in names
    }


def _compact_cube_member(
    cube_name: str,
    name: str,
    collection: str,
    authored: dict[str, Any],
    compiled: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    member_type = authored.get("type")

    if not isinstance(member_type, str) or not member_type:
        member_type = (
            compiled.get("aggType")
            if collection == "measures"
            else compiled.get("type")
        )

    if isinstance(member_type, str) and member_type:
        result["type"] = member_type

    semantic_type = _semantic_type(authored)

    if semantic_type:
        result["semantic_type"] = semantic_type

    description = _clean_text(
        authored.get("description") or compiled.get("description")
    )

    if description:
        result["description"] = description
    else:
        title = _meaningful_title(
            authored.get("title") or compiled.get("title"),
            context=f"{cube_name} {name}",
        )

        if title:
            result["title"] = title

    sql = authored.get("sql")

    if (
        isinstance(sql, str)
        and sql.strip()
        and not _is_trivial_member_sql(
            cube_name,
            name,
            sql,
        )
    ):
        result["sql"] = sql.strip()

    filters = _semantic_filters(authored.get("filters"))

    if filters:
        result["filter"] = filters[0] if len(filters) == 1 else filters

    references = _member_references(authored, compiled)

    if references is not None:
        result["references"] = references

    if authored.get("primary_key") is True or compiled.get("primaryKey") is True:
        result["primary_key"] = True

    _add_non_default_access(result, authored, compiled)

    if authored.get("format") not in (None, "", {}, []):
        result["format"] = authored["format"]

    for source_key, output_key in (
        ("rolling_window", "rolling_window"),
        ("case", "case"),
        ("sub_query", "sub_query"),
        ("propagate_filters_to_sub_query", "propagate_filters_to_sub_query"),
        ("granularities", "granularities"),
    ):
        if authored.get(source_key) not in (None, False, "", [], {}):
            result[output_key] = authored[source_key]

    if compiled.get("cumulative") is True:
        result["cumulative"] = True
    if compiled.get("cumulativeTotal") is True:
        result["cumulative_total"] = True
    if compiled.get("suggestFilterValues") is False:
        result["suggest_filter_values"] = False

    drill_members = authored.get("drill_members") or compiled.get("drillMembers")

    if isinstance(drill_members, list) and drill_members:
        result["drill_members"] = [
            _local_member_name(member, cube_name) for member in drill_members
        ]

    return result


def _compact_cube_segments(
    cube_name: str,
    authored_segments: Any,
    compiled_segments: Any,
) -> dict[str, Any]:
    segments = _compact_cube_members(
        cube_name,
        "segments",
        authored_segments,
        compiled_segments,
    )
    result: dict[str, Any] = {}

    for name, segment in segments.items():
        segment.pop("type", None)

        if set(segment) == {"sql"}:
            result[name] = segment["sql"]
        else:
            result[name] = segment

    return result


def _compact_cube_relationships(
    cube_name: str,
    authored_joins: Any,
    compiled_joins: Any,
) -> dict[str, Any]:
    authored = _member_index(authored_joins, cube_name)
    compiled = _member_index(compiled_joins, cube_name)
    names = [*authored, *(name for name in compiled if name not in authored)]
    relationships: dict[str, Any] = {}

    for name in names:
        source = authored.get(name, {})
        fallback = compiled.get(name, {})
        relationship: dict[str, Any] = {}

        if source.get("relationship") or fallback.get("relationship"):
            relationship["relationship"] = source.get("relationship") or fallback.get(
                "relationship"
            )
        if source.get("sql"):
            relationship["sql"] = source["sql"]
        if fallback.get("joinType"):
            relationship["join_type"] = fallback["joinType"]

        description = _clean_text(
            source.get("description") or fallback.get("description")
        )

        if description:
            relationship["description"] = description

        _add_non_default_access(relationship, source, fallback)

        if relationship:
            relationships[name] = relationship

    return relationships


def _compact_cube_hierarchies(
    cube_name: str,
    authored_hierarchies: Any,
) -> dict[str, Any]:
    if not isinstance(authored_hierarchies, list):
        return {}

    result: dict[str, Any] = {}

    for hierarchy in authored_hierarchies:
        if not isinstance(hierarchy, dict) or not isinstance(
            hierarchy.get("name"), str
        ):
            continue

        levels = hierarchy.get("levels")
        detail: dict[str, Any] = {}

        if isinstance(levels, list) and levels:
            detail["levels"] = [
                _local_member_name(level, cube_name) for level in levels
            ]

        description = _clean_text(hierarchy.get("description"))

        if description:
            detail["description"] = description

        if detail:
            result[hierarchy["name"]] = detail

    return result


def _member_index(members: Any, cube_name: str) -> dict[str, dict[str, Any]]:
    if not isinstance(members, list):
        return {}

    return {
        _local_member_name(member["name"], cube_name): member
        for member in members
        if isinstance(member, dict) and isinstance(member.get("name"), str)
    }


def _local_member_name(value: Any, cube_name: str) -> str:
    name = str(value)
    prefix = f"{cube_name}."

    return (
        name.removeprefix(prefix)
        if name.startswith(prefix)
        else name.rsplit(".", 1)[-1]
    )


def _semantic_filters(filters: Any) -> list[str]:
    if not isinstance(filters, list):
        return []

    return [
        item["sql"].strip()
        for item in filters
        if isinstance(item, dict)
        and isinstance(item.get("sql"), str)
        and item["sql"].strip()
    ]


def _member_references(authored: dict[str, Any], compiled: dict[str, Any]) -> Any:
    if authored.get("references") is not None:
        return authored["references"]

    for member in (authored, compiled):
        meta = member.get("meta")

        if isinstance(meta, dict) and meta.get("references") is not None:
            return meta["references"]

    return None


def _add_non_default_access(
    result: dict[str, Any],
    authored: dict[str, Any],
    compiled: dict[str, Any],
) -> None:
    if authored.get("public") is False or compiled.get("public") is False:
        result["public"] = False
    if authored.get("shown") is False or compiled.get("isVisible") is False:
        result["visible"] = False


def _normalize_sql_table(value: str) -> str:
    normalized = value.strip()
    quoted = re.fullmatch(r'"([^"]+)"\."([^"]+)"', normalized)

    return f"{quoted.group(1)}.{quoted.group(2)}" if quoted else normalized


def _is_trivial_member_sql(cube_name: str, member_name: str, sql: str) -> bool:
    normalized = re.sub(r"\s+", " ", sql.strip())

    return normalized in {
        member_name,
        f"{{CUBE}}.{member_name}",
        f"{cube_name}.{member_name}",
    }


def _summary_description(value: Any) -> str | None:
    text = _clean_text(value, first_paragraph=True)

    return text or None


def _clean_text(value: Any, *, first_paragraph: bool = False) -> str:
    if not isinstance(value, str):
        return ""

    text = value.strip()

    if first_paragraph:
        text = re.split(r"\n\s*\n", text, maxsplit=1)[0]

    return re.sub(r"\s+", " ", text).strip()


def _limit_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value

    return f"{value[: max_chars - 1].rstrip()}…"


def _meaningful_title(title: Any, *, context: str) -> str | None:
    if not isinstance(title, str) or not title.strip():
        return None

    title_text = title.strip()
    context_tokens = _semantic_title_tokens(context)
    title_tokens = _semantic_title_tokens(title_text)

    if title_tokens and title_tokens.issubset(context_tokens):
        return None

    return title_text


def _semantic_title_tokens(value: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", value.lower())

    return {
        token[:-1] if token.endswith("s") and len(token) > 3 else token
        for token in tokens
    }


def _compile_status_label(status: dict[str, Any]) -> str:
    if status.get("compiled") is True:
        return "compiled"
    if status.get("connected") is False and status.get("error"):
        return "unavailable"

    return "not_compiled"


def _diff_summary(diff: str) -> dict[str, int]:
    lines = diff.splitlines()

    return {
        "lines_added": sum(
            1 for line in lines if line.startswith("+") and not line.startswith("+++")
        ),
        "lines_removed": sum(
            1 for line in lines if line.startswith("-") and not line.startswith("---")
        ),
    }


def _manifest_missing_fields(manifest: dict[str, Any]) -> list[str]:
    models = manifest.get("models")

    if not isinstance(models, list):
        return []

    return sorted(
        {
            field
            for model in models
            if isinstance(model, dict)
            for field in model.get("missing_manifest_fields", [])
            if isinstance(field, str)
        }
    )


def _compact_validation_test(test: dict[str, Any]) -> dict[str, Any]:
    success = bool(test.get("success"))
    row_count = test.get("row_count")
    result: dict[str, Any] = {
        "success": success,
        "row_count": (
            row_count
            if isinstance(row_count, int) and not isinstance(row_count, bool)
            else 0
        ),
    }

    if not success:
        if isinstance(test.get("description"), str) and test["description"]:
            result["description"] = test["description"]
        if isinstance(test.get("error"), str) and test["error"]:
            result["error"] = test["error"]

    return result


def _validation_compile_status(
    raw: dict[str, Any],
    cube: dict[str, Any],
    cleanup: dict[str, Any],
) -> str:
    if raw.get("compiles") is True or cube.get("compiled") is True:
        return "compiled"

    errors = raw.get("errors")

    if isinstance(errors, list) and any(
        isinstance(error, dict) and error.get("code") == "COMPILE_FAILED"
        for error in errors
    ):
        return "not_compiled"

    if cube.get("error"):
        return "unavailable" if cube.get("connected") is False else "not_compiled"

    if cleanup.get("attempted") or cube.get("missing_names"):
        return "not_compiled"

    return "not_run"


def _query_result_member_hints(response: dict[str, Any]) -> dict[str, dict[str, Any]]:
    query = response.get("query") if isinstance(response.get("query"), dict) else {}
    cube = response.get("cube") if isinstance(response.get("cube"), dict) else {}
    annotation = (
        cube.get("annotation") if isinstance(cube.get("annotation"), dict) else {}
    )
    timezone_name = (
        query.get("timezone") if isinstance(query.get("timezone"), str) else None
    )
    hints: dict[str, dict[str, Any]] = {}

    def hint_for(member: str) -> dict[str, Any]:
        hint = hints.setdefault(member, {})

        if timezone_name and "timezone" not in hint:
            hint["timezone"] = timezone_name

        return hint

    for collection in ("measures", "dimensions", "timeDimensions"):
        annotated_members = annotation.get(collection)

        if not isinstance(annotated_members, dict):
            continue

        for member, detail in annotated_members.items():
            if not isinstance(member, str) or not isinstance(detail, dict):
                continue

            hint = hint_for(member)
            hint["collection"] = collection
            member_type = detail.get("type") or detail.get("aggType")

            if isinstance(member_type, str) and member_type:
                hint["type"] = member_type

            semantic_type = _semantic_type(detail)

            if semantic_type:
                hint["semantic_type"] = semantic_type

            for text_key in ("title", "shortTitle", "description"):
                if isinstance(detail.get(text_key), str):
                    hint[text_key] = detail[text_key]

    for member in query.get("measures", []):
        if isinstance(member, str):
            hint = hint_for(member)
            hint.setdefault("collection", "measures")
            hint.setdefault("type", "number")

    for member in query.get("dimensions", []):
        if isinstance(member, str):
            hint_for(member).setdefault("collection", "dimensions")

    time_dimensions = query.get("timeDimensions")

    if isinstance(time_dimensions, list):
        for item in time_dimensions:
            if not isinstance(item, dict) or not isinstance(item.get("dimension"), str):
                continue

            member = item["dimension"]
            hint = hint_for(member)
            hint["collection"] = "timeDimensions"
            hint["type"] = "time"
            granularity = item.get("granularity")

            if isinstance(granularity, str) and granularity:
                hint["granularity"] = granularity
                bucket_hint = hint_for(f"{member}.{granularity}")
                bucket_hint.update(hint)
                bucket_hint["granularity"] = granularity

    return hints


def _compact_query_row(
    row: dict[str, Any],
    member_hints: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        str(key): _compact_query_value(str(key), value, member_hints)
        for key, value in row.items()
    }


def _compact_query_value(
    key: str,
    value: Any,
    member_hints: dict[str, dict[str, Any]],
) -> Any:
    hint = _query_member_hint(key, member_hints)

    if _is_numeric_query_member(hint):
        return _compact_numeric_value(value)

    if _is_date_only_query_member(key, hint):
        return _date_only_value(value, hint.get("timezone"))

    return value


def _query_member_hint(
    key: str,
    member_hints: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if key in member_hints:
        return member_hints[key]

    if "." in key:
        member, suffix = key.rsplit(".", 1)

        if suffix in DATE_BUCKET_GRANULARITIES and member in member_hints:
            return {**member_hints[member], "granularity": suffix}

    return {}


def _is_numeric_query_member(hint: dict[str, Any]) -> bool:
    member_type = hint.get("type")
    collection = hint.get("collection")

    if isinstance(member_type, str) and member_type in NUMERIC_MEMBER_TYPES:
        return True

    return collection == "measures"


def _compact_numeric_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value

    if isinstance(value, (int, float)):
        return value

    if not isinstance(value, str):
        return value

    text = value.strip()

    if not DECIMAL_TEXT_RE.fullmatch(text):
        return value

    try:
        decimal = Decimal(text)
    except (InvalidOperation, ValueError):
        return value

    if not decimal.is_finite():
        return value

    if decimal == decimal.to_integral_value():
        return int(decimal)

    compact = format(decimal.normalize(), "f")
    significant_digits = len(compact.replace(".", "").replace("-", "").lstrip("0"))

    if significant_digits <= 15:
        return float(compact)

    return compact.rstrip("0").rstrip(".")


def _is_date_only_query_member(key: str, hint: dict[str, Any]) -> bool:
    member_type = hint.get("type")

    if member_type != "time":
        return False

    semantic_type = hint.get("semantic_type")

    if isinstance(semantic_type, str) and semantic_type in DATE_ONLY_SEMANTIC_TYPES:
        return True

    granularity = hint.get("granularity")

    if isinstance(granularity, str) and granularity in DATE_BUCKET_GRANULARITIES:
        return True

    text = " ".join(
        str(hint.get(key_name) or "")
        for key_name in ("title", "shortTitle", "description")
    )

    return bool(DATE_ONLY_MEMBER_NAME_RE.search(f"{key} {text}"))


def _date_only_value(value: Any, timezone_name: Any) -> Any:
    if not isinstance(value, str):
        return value

    text = value.strip()

    if ISO_DATE_RE.fullmatch(text):
        return text

    parsed = _parse_iso_datetime(text)

    if parsed is None:
        return value

    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).date().isoformat()

    if isinstance(timezone_name, str) and timezone_name:
        try:
            local = parsed.replace(tzinfo=ZoneInfo(timezone_name))
            return local.astimezone(timezone.utc).date().isoformat()
        except (ZoneInfoNotFoundError, ValueError):
            pass

    return parsed.date().isoformat()


def _parse_iso_datetime(value: str) -> datetime | None:
    normalized = value.replace("Z", "+00:00")

    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _semantic_type(detail: dict[str, Any]) -> str | None:
    candidates: list[Any] = [
        detail.get("semantic_type"),
        detail.get("semanticType"),
    ]
    meta = detail.get("meta")

    if isinstance(meta, dict):
        candidates.extend([meta.get("semantic_type"), meta.get("semanticType")])
        settra = meta.get("settra")

        if isinstance(settra, dict):
            candidates.extend([settra.get("semantic_type"), settra.get("semanticType")])

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip().lower()

    return None


def _compact_profile_column(
    column: dict[str, Any],
    *,
    include_description: bool,
) -> dict[str, Any]:
    result = _compact_profile_types(column)
    null_count = column.get("null_count")
    distinct_count = column.get("distinct_sample_count")
    empty_string_count = column.get("empty_string_count")
    examples = column.get("example_values")
    result["nulls"] = (
        null_count
        if isinstance(null_count, int) and not isinstance(null_count, bool)
        else 0
    )
    result["distinct"] = (
        distinct_count
        if isinstance(distinct_count, int) and not isinstance(distinct_count, bool)
        else 0
    )

    if (
        isinstance(empty_string_count, int)
        and not isinstance(empty_string_count, bool)
        and empty_string_count > 0
    ):
        result["empty_strings"] = empty_string_count
    if isinstance(examples, list) and examples:
        result["examples"] = examples
    if include_description:
        description = _clean_text(column.get("description"))

        if description:
            result["description"] = _limit_text(
                description,
                PROFILE_DESCRIPTION_MAX_CHARS,
            )

    return result


def _compact_profile_types(column: dict[str, Any]) -> dict[str, Any]:
    source_type = _clean_text(column.get("type"))
    inferred_type = _clean_text(column.get("inferred_type"))
    canonical_source_type = _canonical_profile_type(source_type)

    if inferred_type in {"", "unknown"}:
        return {"type": canonical_source_type or source_type or "unknown"}
    if not source_type or canonical_source_type == inferred_type:
        return {"type": inferred_type}

    return {
        "source_type": source_type,
        "inferred_type": inferred_type,
    }


def _canonical_profile_type(value: str) -> str | None:
    normalized = value.lower()

    if not normalized:
        return None
    if any(token in normalized for token in ("bool",)):
        return "boolean"
    if any(token in normalized for token in ("date", "time", "interval")):
        return "time"
    if any(
        token in normalized
        for token in (
            "int",
            "serial",
            "numeric",
            "decimal",
            "double",
            "real",
            "float",
            "money",
        )
    ):
        return "number"
    if any(
        token in normalized
        for token in ("char", "text", "string", "uuid", "citext", "enum")
    ):
        return "string"

    return None


def _compact_diagnostics(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, list):
        compact = [_compact_diagnostics(item) for item in value]

        return [item for item in compact if item not in (None, "", [], {})]
    if isinstance(value, dict):
        compact: dict[str, Any] = {}

        for key, item in value.items():
            if key in {"compiler_id", "compilerId"} and item is None:
                continue
            if key in {"validation_token_seen"} and item is False:
                continue

            compact_item = _compact_diagnostics(item)

            if compact_item in (None, "", [], {}):
                continue

            compact[key] = compact_item

        return compact

    return value


def _meaningful_compiler_diagnostics(compiler: dict[str, Any]) -> bool:
    return bool(
        compiler.get("connected") is True
        or compiler.get("error")
        or compiler.get("missing_names")
        or compiler.get("compiler_id")
        or compiler.get("compilerId")
    )


def _failed_cleanup(cleanup: dict[str, Any]) -> bool:
    if cleanup.get("error"):
        return True
    if cleanup.get("attempted") is not True:
        return False

    return bool(
        cleanup.get("removed") is False
        or (cleanup.get("restored") is False and "restored" in cleanup)
    )
