import re
import json

from typing import Any

import aiosqlite

from app.agent.semantic_search_text import semantic_search_text
from app.utils import parse_json_payload


async def table_candidates(
    db: aiosqlite.Connection,
    connection_ids: list[int],
) -> list[tuple[dict[str, Any], str]]:
    rows = await db.execute_fetchall(
        f"""
        SELECT
            t.*,
            c.name AS connection_name,
            c.plugin AS plugin,
            c.slug AS connection_schema
        FROM semantic_tables t
        JOIN connections c ON c.id = t.connection_id
        WHERE {_connection_filter("t.connection_id", connection_ids)}
          AND t.hidden = 0
          AND t.status NOT IN ('ignored', 'disabled', 'hidden')
        """,
        connection_ids,
    )
    candidates = []

    for row in rows:
        item = {
            "type": "table",
            "connection_id": row["connection_id"],
            "connection": row["connection_name"],
            "plugin": row["plugin"],
            "table": f'{row["schema_name"]}.{row["table_name"]}',
            "title": row["label"] or row["table_name"],
            "status": row["status"],
            "table_type": row["table_type"],
            "grain": row["grain"],
            "primary_time_column": row["primary_time_column"],
            "metadata": _metadata(row["metadata_json"]),
            "description": _compact(row["description"]),
        }
        candidates.append((item, semantic_search_text(item)))

    return candidates


async def column_candidates(
    db: aiosqlite.Connection,
    connection_ids: list[int],
) -> list[tuple[dict[str, Any], str]]:
    rows = await db.execute_fetchall(
        f"""
        SELECT
            col.*,
            t.connection_id,
            t.schema_name,
            t.table_name,
            t.label AS table_label,
            c.name AS connection_name,
            c.plugin AS plugin
        FROM semantic_columns col
        JOIN semantic_tables t ON t.id = col.semantic_table_id
        JOIN connections c ON c.id = t.connection_id
        WHERE {_connection_filter("t.connection_id", connection_ids)}
          AND t.hidden = 0
          AND col.hidden = 0
          AND t.status NOT IN ('ignored', 'disabled', 'hidden')
          AND col.status NOT IN ('ignored', 'disabled', 'hidden')
        """,
        connection_ids,
    )
    candidates = []

    for row in rows:
        item = {
            "type": "column",
            "connection_id": row["connection_id"],
            "connection": row["connection_name"],
            "plugin": row["plugin"],
            "table": f'{row["schema_name"]}.{row["table_name"]}',
            "column": row["column_name"],
            "title": f'{row["table_name"]}.{row["column_name"]}',
            "status": row["status"],
            "label": row["label"],
            "description": _compact(row["description"]),
            "data_type": row["data_type"],
            "semantic_type": row["semantic_type"],
            "expression": row["expression"],
            "unit": row["unit"],
            "roles": [
                role
                for field, role in (
                    ("is_dimension", "dimension"),
                    ("is_measure", "measure"),
                    ("is_time", "time"),
                    ("is_id", "id"),
                    ("is_foreign_key", "foreign_key"),
                )
                if row[field]
            ],
        }
        candidates.append((item, semantic_search_text(item)))

    return candidates


async def relationship_candidates(
    db: aiosqlite.Connection,
    connection_ids: list[int],
) -> list[tuple[dict[str, Any], str]]:
    rows = await db.execute_fetchall(
        f"""
        SELECT
            r.*,
            fc.name AS from_connection_name,
            tc.name AS to_connection_name,
            ft.schema_name AS from_schema,
            ft.table_name AS from_table,
            fcol.column_name AS from_column,
            fcol.expression AS from_expression,
            tt.schema_name AS to_schema,
            tt.table_name AS to_table,
            tcol.column_name AS to_column,
            tcol.expression AS to_expression
        FROM semantic_relationships r
        JOIN connections fc ON fc.id = r.from_connection_id
        JOIN connections tc ON tc.id = r.to_connection_id
        JOIN semantic_tables ft ON ft.id = r.from_table_id
        JOIN semantic_columns fcol ON fcol.id = r.from_column_id
        JOIN semantic_tables tt ON tt.id = r.to_table_id
        JOIN semantic_columns tcol ON tcol.id = r.to_column_id
        WHERE ({_connection_filter("r.from_connection_id", connection_ids)}
               OR {_connection_filter("r.to_connection_id", connection_ids)})
          AND r.status NOT IN ('ignored', 'disabled', 'hidden')
        """,
        [*connection_ids, *connection_ids],
    )
    candidates = []

    for row in rows:
        from_ref = f'{row["from_schema"]}.{row["from_table"]}.{row["from_column"]}'
        to_ref = f'{row["to_schema"]}.{row["to_table"]}.{row["to_column"]}'
        join_sql = _relationship_join_sql(row)
        item = {
            "type": "relationship",
            "from_connection_id": row["from_connection_id"],
            "to_connection_id": row["to_connection_id"],
            "from_connection": row["from_connection_name"],
            "to_connection": row["to_connection_name"],
            "from": from_ref,
            "to": to_ref,
            "join_sql": join_sql,
            "title": join_sql,
            "status": row["status"],
            "relationship_type": row["relationship_type"],
            "match_type": row["match_type"],
            "confidence": row["confidence"],
            "validation_status": row["validation_status"],
            "validation_note": _compact(row["validation_note"]),
            "evidence": _compact(row["evidence"]),
            "rationale": _compact(row["rationale"]),
        }
        candidates.append((item, semantic_search_text(item)))

    return candidates


def _relationship_join_sql(row: Any) -> str:
    from_ref = f'{row["from_schema"]}.{row["from_table"]}.{row["from_column"]}'
    to_ref = f'{row["to_schema"]}.{row["to_table"]}.{row["to_column"]}'
    from_sql = _relationship_side_sql(
        expression=row["from_expression"],
        ref=from_ref,
        column=row["from_column"],
    )
    to_sql = _relationship_side_sql(
        expression=row["to_expression"],
        ref=to_ref,
        column=row["to_column"],
    )

    return f"{from_sql} = {to_sql}"


def _relationship_side_sql(*, expression: str | None, ref: str, column: str) -> str:
    expression = str(expression or "").strip()
    if not expression:
        return ref

    return re.sub(rf"\b{re.escape(str(column))}\b", ref, expression)


async def metric_candidates(
    db: aiosqlite.Connection,
    connection_ids: list[int],
) -> list[tuple[dict[str, Any], str]]:
    rows = await db.execute_fetchall(
        f"""
        SELECT
            m.*,
            t.schema_name,
            t.table_name,
            c.name AS connection_name,
            c.plugin AS plugin
        FROM semantic_metrics m
        JOIN semantic_tables t ON t.id = m.semantic_table_id
        JOIN connections c ON c.id = m.connection_id
        WHERE {_connection_filter("m.connection_id", connection_ids)}
          AND m.status NOT IN ('ignored', 'disabled', 'hidden')
        """,
        connection_ids,
    )
    candidates = []

    for row in rows:
        filters = parse_json_payload(row["filters_json"])
        item = {
            "type": "metric",
            "connection_id": row["connection_id"],
            "connection": row["connection_name"],
            "plugin": row["plugin"],
            "table": f'{row["schema_name"]}.{row["table_name"]}',
            "name": row["name"],
            "title": row["label"] or row["name"],
            "status": row["status"],
            "expression": row["expression"],
            "filters": filters,
            "time_column": row["time_column"],
            "unit": row["unit"],
        }
        candidates.append((item, semantic_search_text(item)))

    return candidates


async def warning_candidates(
    db: aiosqlite.Connection,
    connection_ids: list[int],
) -> list[tuple[dict[str, Any], str]]:
    relationship_rows = await db.execute_fetchall(
        f"""
        SELECT
            r.id,
            r.validation_status,
            r.validation_note,
            r.evidence,
            r.rationale,
            ft.schema_name AS from_schema,
            ft.table_name AS from_table,
            tt.schema_name AS to_schema,
            tt.table_name AS to_table
        FROM semantic_relationships r
        JOIN semantic_tables ft ON ft.id = r.from_table_id
        JOIN semantic_tables tt ON tt.id = r.to_table_id
        WHERE ({_connection_filter("r.from_connection_id", connection_ids)}
               OR {_connection_filter("r.to_connection_id", connection_ids)})
          AND (
              r.validation_note IS NOT NULL
              OR r.validation_status NOT IN ('', 'valid')
          )
        """,
        [*connection_ids, *connection_ids],
    )
    candidates = []

    for row in relationship_rows:
        item = {
            "type": "warning",
            "warning_type": "relationship_validation",
            "title": (
                "Relationship warning: "
                f'{row["from_schema"]}.{row["from_table"]} -> '
                f'{row["to_schema"]}.{row["to_table"]}'
            ),
            "validation_status": row["validation_status"],
            "validation_note": _compact(row["validation_note"]),
            "evidence": _compact(row["evidence"]),
            "rationale": _compact(row["rationale"]),
        }
        candidates.append((item, semantic_search_text(item)))

    metadata_rows = await db.execute_fetchall(
        f"""
        SELECT
            sm.plugin,
            sm.table_name,
            sm.content,
            c.id AS connection_id,
            c.name AS connection_name,
            c.slug AS schema_name
        FROM semantic_metadata sm
        JOIN connections c ON c.plugin = sm.plugin
        WHERE {_connection_filter("c.id", connection_ids)}
        """,
        connection_ids,
    )

    for row in metadata_rows:
        content = parse_json_payload(row["content"]) or {}
        notes = content.get("notes")
        caveats = content.get("caveats")

        if not notes and not caveats:
            continue

        item = {
            "type": "warning",
            "warning_type": "table_note",
            "connection_id": row["connection_id"],
            "connection": row["connection_name"],
            "plugin": row["plugin"],
            "table": f'{row["schema_name"]}.{row["table_name"]}',
            "title": f'{row["table_name"]} notes and caveats',
            "notes": _compact(notes),
            "caveats": [_compact(caveat) for caveat in caveats or []],
        }
        candidates.append((item, semantic_search_text(item)))

    return candidates


def _connection_filter(column: str, connection_ids: list[int]) -> str:
    if not connection_ids:
        return "1 = 0"

    placeholders = ",".join("?" for _ in connection_ids)
    return f"{column} IN ({placeholders})"


def _compact(value: Any, max_chars: int = 500) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        text = json.dumps(value, default=str)
    else:
        text = str(value)

    text = re.sub(r"\s+", " ", text).strip()

    if len(text) <= max_chars:
        return text

    return f"{text[: max_chars - 3]}..."


def _metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value

    if not value:
        return {}

    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}

    return parsed if isinstance(parsed, dict) else {}
