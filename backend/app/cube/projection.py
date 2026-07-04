import re

from typing import Any
from dataclasses import dataclass


@dataclass(frozen=True)
class CubeProjectionInput:
    compiled: dict[str, Any]
    authored_source: dict[str, Any] | None = None


@dataclass(frozen=True)
class OverlayProjectionInput:
    path: str
    content: str
    model_names: list[str]
    manifest: dict[str, Any]
    compile_status: dict[str, Any]
    parse_error: str | None = None


@dataclass(frozen=True)
class QueryResultProjectionInput:
    response: dict[str, Any]


@dataclass(frozen=True)
class TableSampleProjectionInput:
    response: dict[str, Any]


class SemanticResponseProjector:
    """Shape semantic MCP responses around one authoritative representation."""

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

    def query_result(self, value: QueryResultProjectionInput) -> dict[str, Any]:
        response = value.response
        data = response.get("data")
        rows = data if isinstance(data, list) else []
        result: dict[str, Any] = {
            "data": rows,
            "row_count": len(rows),
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
            "truncated": bool(truncated_values),
        }

        if truncated_values:
            result["truncated_values"] = list(dict.fromkeys(truncated_values))

        return result


semantic_response_projector = SemanticResponseProjector()


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
