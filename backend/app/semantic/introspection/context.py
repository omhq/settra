import json
import logging
from typing import Any

import aiosqlite
import asyncpg

from app.agent.consts import (
    GOOGLE_SHEETS_CELL_SAMPLE_MAX_CELLS,
    GOOGLE_SHEETS_CELL_SAMPLE_ROWS,
    GOOGLE_SHEETS_SYSTEM_COLUMNS,
    STEAMPIPE_DB_PASSWORD,
    STEAMPIPE_HOST,
    STEAMPIPE_PORT,
    TABLE_SAMPLE_MAX_COLUMNS,
    TABLE_SAMPLE_ROWS,
    TABLE_SAMPLE_VALUE_MAX_CHARS,
)
from app.connector_prompts import connector_prompt_snippets
from app.utils import jsonable

logger = logging.getLogger(__name__)


async def load_ai_context(
    db: aiosqlite.Connection,
    connection_ids: list[int],
    semantic_table_ids: list[int],
) -> dict[str, Any]:
    db.row_factory = aiosqlite.Row
    placeholders = ",".join("?" for _ in connection_ids)
    table_where = [
        f"connection_id IN ({placeholders})",
        "hidden = 0",
        "status IN ('confirmed', 'published')",
    ]
    table_params: list[Any] = list(connection_ids)

    selected_table_ids = sorted(set(semantic_table_ids))
    if selected_table_ids:
        table_placeholders = ",".join("?" for _ in selected_table_ids)
        table_where.append(f"id IN ({table_placeholders})")
        table_params.extend(selected_table_ids)

    async with db.execute(
        f"""
        SELECT id, name, slug, plugin, status
        FROM connections
        WHERE id IN ({placeholders})
        ORDER BY id
        """,
        connection_ids,
    ) as cur:
        connections = [dict(row) for row in await cur.fetchall()]

    connection_by_id = {int(connection["id"]): connection for connection in connections}

    async with db.execute(
        f"""
        SELECT *
        FROM semantic_tables
        WHERE {" AND ".join(table_where)}
        ORDER BY connection_id, table_name
        """,
        table_params,
    ) as cur:
        tables = [dict(row) for row in await cur.fetchall()]

    for table in tables:
        connection = connection_by_id.get(int(table["connection_id"]))
        if connection:
            table["connection_slug"] = connection.get("slug")

    table_ids = [int(table["id"]) for table in tables]
    columns: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []

    if table_ids:
        table_placeholders = ",".join("?" for _ in table_ids)
        async with db.execute(
            f"""
            SELECT *
            FROM semantic_columns
            WHERE semantic_table_id IN ({table_placeholders})
              AND hidden = 0
              AND status IN ('confirmed', 'published')
            ORDER BY semantic_table_id, column_name
            """,
            table_ids,
        ) as cur:
            columns = [dict(row) for row in await cur.fetchall()]

        async with db.execute(
            f"""
            SELECT
                r.*,
                ft.table_name AS from_table,
                fc.column_name AS from_column,
                tt.table_name AS to_table,
                tc.column_name AS to_column
            FROM semantic_relationships r
            JOIN semantic_tables ft ON ft.id = r.from_table_id
            JOIN semantic_columns fc ON fc.id = r.from_column_id
            JOIN semantic_tables tt ON tt.id = r.to_table_id
            JOIN semantic_columns tc ON tc.id = r.to_column_id
            WHERE r.from_table_id IN ({table_placeholders})
               OR r.to_table_id IN ({table_placeholders})
            ORDER BY r.status, r.confidence DESC
            """,
            (*table_ids, *table_ids),
        ) as cur:
            relationships = [dict(row) for row in await cur.fetchall()]

        async with db.execute(
            f"""
            SELECT
                m.*,
                t.table_name AS table_name
            FROM semantic_metrics m
            JOIN semantic_tables t ON t.id = m.semantic_table_id
            WHERE m.semantic_table_id IN ({table_placeholders})
            ORDER BY m.status, m.name
            """,
            table_ids,
        ) as cur:
            metrics = [dict(row) for row in await cur.fetchall()]

    columns_by_table_id: dict[int, list[dict[str, Any]]] = {}

    for column in columns:
        columns_by_table_id.setdefault(int(column["semantic_table_id"]), []).append(
            column
        )

    samples_by_table = await _load_table_samples(tables, columns_by_table_id)
    table_context = []
    sheet_structures_by_table_id: dict[int, dict[str, Any]] = {}
    relationship_blocked_tables: dict[int, str] = {}
    metric_blocked_tables: dict[int, str] = {}

    for table in tables:
        table_id = int(table["id"])
        data_samples = samples_by_table.get(table_id, [])
        sheet_structure = _build_google_sheet_structure(
            table,
            columns_by_table_id.get(table_id, []),
            data_samples,
        )
        relationship_block_reason = None
        metric_block_reason = None

        if sheet_structure:
            sheet_structures_by_table_id[table_id] = sheet_structure

            if sheet_structure.get("relationship_use") == "blocked":
                relationship_block_reason = str(
                    sheet_structure["relationship_block_reason"]
                )
                relationship_blocked_tables[table_id] = relationship_block_reason

            if sheet_structure.get("header_status") in (
                "needs_header_row",
                "semantic_columns_out_of_sync",
            ):
                metric_block_reason = str(
                    sheet_structure.get("relationship_block_reason")
                    or _connector_introspection_context_text(
                        str(table["source_name"]),
                        "metric_fields_not_ready",
                    )
                    or "Worksheet fields are not ready for metric suggestions."
                )
                metric_blocked_tables[table_id] = metric_block_reason

        table_item = without_empty_values(
            {
                "connection_id": table["connection_id"],
                "connection_plugin": table["source_name"],
                "schema": table["schema_name"],
                "table": table["table_name"],
                "label": table["label"],
                "description": table["description"],
                "type": table["table_type"],
                "grain": table["grain"],
                "primary_time_column": table["primary_time_column"],
                "metadata": table_metadata(table),
                "columns": [
                    column_context(
                        column,
                        relationship_block_reason=(
                            relationship_block_reason
                            if _is_google_sheets_relationship_column(column)
                            else None
                        ),
                    )
                    for column in columns_by_table_id.get(table_id, [])
                ],
            }
        )
        if sheet_structure:
            table_item["sheet_structure"] = sheet_structure

        if metric_block_reason:
            table_item["metric_use"] = "blocked"
            table_item["metric_block_reason"] = metric_block_reason

        table_item["data_samples"] = data_samples
        table_context.append(table_item)

    return {
        "connections": connections,
        "tables": tables,
        "columns": columns,
        "metrics": metrics,
        "table_context": table_context,
        "sampled_table_count": sum(
            1 for samples in samples_by_table.values() if samples
        ),
        "existing_relationship_keys": {
            relationship_key(relationship) for relationship in relationships
        },
        "existing_relationships": [
            without_empty_values(
                {
                    "from_connection_id": relationship["from_connection_id"],
                    "from_table": relationship["from_table"],
                    "from_column": relationship["from_column"],
                    "to_connection_id": relationship["to_connection_id"],
                    "to_table": relationship["to_table"],
                    "to_column": relationship["to_column"],
                    "relationship_type": relationship["relationship_type"],
                    "match_type": relationship["match_type"],
                    "confidence": relationship["confidence"],
                    "status": relationship["status"],
                    "source": relationship["source"],
                }
            )
            for relationship in relationships
        ],
        "existing_metrics": [
            without_empty_values(
                {
                    "connection_id": metric["connection_id"],
                    "table": metric["table_name"],
                    "name": metric["name"],
                    "label": metric["label"],
                    "expression": metric["expression"],
                    "filters": _metric_filters(metric.get("filters_json")),
                    "time_column": metric["time_column"],
                    "unit": metric["unit"],
                    "status": metric["status"],
                }
            )
            for metric in metrics
        ],
        "existing_metric_keys": {
            (int(metric["connection_id"]), str(metric["name"]).strip().lower())
            for metric in metrics
        },
        "sheet_structures_by_table_id": sheet_structures_by_table_id,
        "relationship_blocked_tables": relationship_blocked_tables,
        "metric_blocked_tables": metric_blocked_tables,
        "has_googlesheets": any(
            connection["plugin"] == "googlesheets" for connection in connections
        ),
    }


def column_context(
    column: dict[str, Any],
    *,
    relationship_block_reason: str | None = None,
) -> dict[str, Any]:
    flags = [
        name
        for name, enabled in {
            "dimension": column["is_dimension"],
            "measure": column["is_measure"],
            "time": column["is_time"],
            "id": column["is_id"],
            "foreign_key": column["is_foreign_key"],
        }.items()
        if bool(enabled)
    ]

    payload = without_empty_values(
        {
            "name": column["column_name"],
            "label": column["label"],
            "description": column["description"],
            "data_type": column["data_type"],
            "semantic_type": column["semantic_type"],
            "unit": column["unit"],
            "expression": column["expression"],
            "flags": flags,
        }
    )

    if relationship_block_reason:
        payload["relationship_use"] = "blocked"
        payload["relationship_block_reason"] = relationship_block_reason

    return payload


async def _load_table_samples(
    tables: list[dict[str, Any]],
    columns_by_table: dict[int, list[dict[str, Any]]],
) -> dict[int, list[dict[str, Any]]]:
    if not tables:
        return {}

    samples: dict[int, list[dict[str, Any]]] = {
        int(table["id"]): [] for table in tables
    }

    try:
        pg = await asyncpg.connect(
            host=STEAMPIPE_HOST,
            port=STEAMPIPE_PORT,
            database="steampipe",
            user="steampipe",
            password=STEAMPIPE_DB_PASSWORD,
            timeout=5,
        )
    except Exception as exc:
        logger.info(f"Could not connect to Steampipe for AI table samples: {exc}")
        return samples

    try:
        for table in tables:
            table_id = int(table["id"])
            samples[table_id] = await _sample_table(
                pg,
                table,
                columns_by_table.get(table_id, []),
            )
    finally:
        await pg.close()

    return samples


async def _sample_table(
    pg: asyncpg.Connection,
    table: dict[str, Any],
    columns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if _is_google_sheets_data_table(table):
        cell_samples = await _sample_google_sheet_cells(pg, table)
        if cell_samples:
            return cell_samples

    selected_columns = [column["column_name"] for column in columns][
        :TABLE_SAMPLE_MAX_COLUMNS
    ]
    if not selected_columns:
        return []

    column_sql = ", ".join(_quote_ident(column) for column in selected_columns)

    for schema_name in _candidate_schema_names(table):
        qualified_table = (
            f"{_quote_ident(schema_name)}.{_quote_ident(table['table_name'])}"
        )

        try:
            rows = await pg.fetch(
                f"SELECT {column_sql} FROM {qualified_table} LIMIT {TABLE_SAMPLE_ROWS}",
                timeout=5,
            )
        except Exception as exc:
            logger.debug(
                f"Could not sample semantic table "
                f"{schema_name}.{table['table_name']}: {exc}"
            )
            continue

        return [
            {
                "_sample_schema": schema_name,
                **{
                    key: sample_value(value)
                    for key, value in jsonable(dict(row)).items()
                },
            }
            for row in rows
        ]

    return []


async def _sample_google_sheet_cells(
    pg: asyncpg.Connection,
    table: dict[str, Any],
) -> list[dict[str, Any]]:
    header_row = semantic_table_header_row(table)
    sample_row_limit = GOOGLE_SHEETS_CELL_SAMPLE_ROWS
    max_distinct_rows = sample_row_limit + (
        1 if header_row and header_row > sample_row_limit else 0
    )

    cells = []
    sample_schema = None
    for schema_name in _candidate_schema_names(table):
        qualified_cell_table = (
            f"{_quote_ident(schema_name)}.{_quote_ident('googlesheets_cell')}"
        )
        try:
            cells = await pg.fetch(
                f"""
                SELECT "row", col, cell, value
                FROM {qualified_cell_table}
                WHERE sheet_name = $1
                  AND ("row" <= $2 OR "row" = $3)
                ORDER BY CASE WHEN "row" = $3 THEN 0 ELSE 1 END, "row", col
                LIMIT {GOOGLE_SHEETS_CELL_SAMPLE_MAX_CELLS}
                """,
                table["table_name"],
                sample_row_limit,
                header_row or 1,
                timeout=5,
            )
        except Exception as exc:
            logger.debug(
                f"Could not sample Google Sheets cells for "
                f"{schema_name}.{table['table_name']}: {exc}"
            )
            continue

        if cells:
            sample_schema = schema_name
            break

    if not cells:
        return []

    rows_by_number: dict[int, dict[str, Any]] = {}
    for cell in cells:
        row_number = int(cell["row"])
        if row_number not in rows_by_number:
            if len(rows_by_number) >= max_distinct_rows:
                break
            rows_by_number[row_number] = {
                "_sample_source": "googlesheets_cell",
                "_sample_schema": sample_schema,
                "_row_number": row_number,
            }

        column_key = cell["col"] or cell["cell"]
        rows_by_number[row_number][column_key] = sample_value(cell["value"])

    return list(rows_by_number.values())


def _candidate_schema_names(table: dict[str, Any]) -> list[str]:
    schema_name = str(table.get("schema_name") or "")
    connection_slug = str(table.get("connection_slug") or "")
    preferred = (
        [connection_slug, schema_name]
        if _is_google_sheets_data_table(table)
        else [schema_name, connection_slug]
    )

    names: list[str] = []
    for name in preferred:
        if name and name not in names:
            names.append(name)
    return names


def _build_google_sheet_structure(
    table: dict[str, Any],
    columns: list[dict[str, Any]],
    data_samples: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not _is_google_sheets_data_table(table):
        return None

    exposed_columns = [
        str(column.get("column_name") or "")
        for column in columns
        if _is_google_sheets_relationship_column(column)
    ]
    header_row = semantic_table_header_row(table)
    first_cell_row = _google_sheet_cell_row(data_samples, 1)
    configured_header_cells = _google_sheet_cell_row(data_samples, header_row)
    first_row_values = _google_sheet_cell_row_values(first_cell_row)
    configured_header_values = _google_sheet_cell_row_values(configured_header_cells)
    configured_header_columns = _google_sheet_header_columns(configured_header_cells)

    header_status = "configured"
    relationship_use = "allowed"
    reason = None
    unexpected_exposed_columns: list[str] = []

    if not header_row:
        header_status = "needs_header_row"
        reason = (
            _connector_introspection_context_text(
                str(table.get("source_name") or ""),
                "header_row_missing",
            )
            or "No header_row is configured for this worksheet table."
        )
        relationship_use = "blocked"
    elif not configured_header_values:
        header_status = "configured_unverified"
        reason = _connector_introspection_context_text(
            str(table.get("source_name") or ""),
            "header_row_unverified",
        ) or (
            "Could not inspect the configured header row, so worksheet field "
            "names are unverified."
        )
        relationship_use = "blocked"
    else:
        header_identifiers = {
            identifier
            for identifier in (
                _normalize_sheet_header_identifier(value)
                for value in configured_header_values
            )
            if identifier
        }
        unexpected_exposed_columns = [
            column
            for column in exposed_columns
            if _normalize_sheet_header_identifier(column) not in header_identifiers
        ]
        if unexpected_exposed_columns:
            header_status = "semantic_columns_out_of_sync"
            reason = _connector_introspection_context_text(
                str(table.get("source_name") or ""),
                "semantic_columns_out_of_sync",
            ) or (
                "Semantic columns do not match the configured header row. "
                "Re-introspect this connection so worksheet fields are rebuilt "
                "from the selected header row."
            )
            relationship_use = "blocked"

    payload = {
        "kind": "google_sheets_dynamic_worksheet",
        "header_status": header_status,
        "relationship_use": relationship_use,
        "relationship_block_reason": reason,
        "sample_source": (
            data_samples[0].get("_sample_source", "dynamic_table")
            if data_samples
            else "unavailable"
        ),
        "sample_schema": (
            data_samples[0].get("_sample_schema") if data_samples else None
        ),
        "exposed_columns": exposed_columns[:TABLE_SAMPLE_MAX_COLUMNS],
        "configured_header_row": header_row,
        "configured_header_values": configured_header_values[:TABLE_SAMPLE_MAX_COLUMNS],
        "configured_header_columns": configured_header_columns[
            :TABLE_SAMPLE_MAX_COLUMNS
        ],
        "unexpected_semantic_columns": unexpected_exposed_columns[
            :TABLE_SAMPLE_MAX_COLUMNS
        ],
        "observed_first_row_values": first_row_values[:TABLE_SAMPLE_MAX_COLUMNS],
        "recommended_raw_table": "googlesheets_cell",
        "recommended_raw_filter": (
            f"sheet_name = {_sql_string_literal(str(table['table_name']))}"
        ),
    }

    return without_empty_values(payload)


def _is_google_sheets_relationship_column(column: dict[str, Any]) -> bool:
    column_name = str(column.get("column_name") or "")
    return (
        column_name not in GOOGLE_SHEETS_SYSTEM_COLUMNS
        and not column_name.startswith("sp_")
    )


def _connector_introspection_context_text(plugin: str, name: str) -> str:
    return "\n".join(
        connector_prompt_snippets(
            [plugin],
            "introspection_context",
            name,
            include_common=False,
            include_headers=False,
        )
    ).strip()


def _positive_header_row(value: Any) -> int | None:
    try:
        header_row = int(value)
    except (TypeError, ValueError):
        return None

    return header_row if header_row > 0 else None


def semantic_table_header_row(table: dict[str, Any]) -> int | None:
    metadata = table_metadata(table)
    header_row = _positive_header_row(metadata.get("header_row"))

    if header_row:
        return header_row

    return _positive_header_row(table.get("header_row"))


def table_metadata(table: dict[str, Any]) -> dict[str, Any]:
    metadata = table.get("metadata")
    if isinstance(metadata, dict):
        return metadata

    raw = table.get("metadata_json")
    if not raw:
        return {}

    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def _google_sheet_cell_row(
    data_samples: list[dict[str, Any]],
    row_number: int | None,
) -> dict[str, Any] | None:
    if not row_number:
        return None

    for row in data_samples:
        if (
            row.get("_sample_source") == "googlesheets_cell"
            and row.get("_row_number") == row_number
        ):
            return row

    return None


def _google_sheet_cell_row_values(row: dict[str, Any] | None) -> list[str]:
    if not row:
        return []

    return [
        str(value)
        for key, value in row.items()
        if not str(key).startswith("_") and value not in (None, "")
    ]


def _google_sheet_header_columns(row: dict[str, Any] | None) -> list[dict[str, str]]:
    if not row:
        return []

    columns = []
    for key, value in row.items():
        if str(key).startswith("_") or value in (None, ""):
            continue

        columns.append(
            {
                "cell_column": str(key),
                "header": str(value),
                "semantic_column": _normalize_sheet_header_identifier(value),
            }
        )

    return columns


def _normalize_sheet_header_identifier(value: Any) -> str:
    return "_".join(
        token
        for token in "".join(
            char.lower() if char.isalnum() else " " for char in str(value)
        ).split()
        if token
    )


def _is_google_sheets_data_table(table: dict[str, Any]) -> bool:
    return table.get("source_name") == "googlesheets" and not str(
        table.get("table_name", "")
    ).startswith("googlesheets_")


async def prune_blocked_relationship_suggestions(
    db: aiosqlite.Connection,
    context: dict[str, Any],
) -> int:
    blocked_tables = [
        int(table_id)
        for table_id in (context.get("relationship_blocked_tables") or {}).keys()
    ]
    if not blocked_tables:
        return 0

    placeholders = ",".join("?" for _ in blocked_tables)
    cursor = await db.execute(
        f"""
        DELETE FROM semantic_relationships
        WHERE status = 'suggested'
          AND (
            from_table_id IN ({placeholders})
            OR to_table_id IN ({placeholders})
          )
        """,
        (*blocked_tables, *blocked_tables),
    )
    await db.commit()

    return max(int(cursor.rowcount or 0), 0)


def sample_value(value: Any) -> Any:
    if isinstance(value, str) and len(value) > TABLE_SAMPLE_VALUE_MAX_CHARS:
        return f"{value[:TABLE_SAMPLE_VALUE_MAX_CHARS]}..."

    if isinstance(value, dict):
        return {key: sample_value(nested) for key, nested in value.items()}

    if isinstance(value, list):
        return [sample_value(item) for item in value[:10]]

    return value


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sql_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def columns_by_table(
    columns: list[dict[str, Any]],
) -> dict[int, dict[str, dict[str, Any]]]:
    grouped: dict[int, dict[str, dict[str, Any]]] = {}
    for column in columns:
        grouped.setdefault(int(column["semantic_table_id"]), {})[
            column["column_name"]
        ] = column
    return grouped


def relationship_key(relationship: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        int(relationship["from_table_id"]),
        int(relationship["from_column_id"]),
        int(relationship["to_table_id"]),
        int(relationship["to_column_id"]),
    )


def connection_for_id(context: dict[str, Any], connection_id: int) -> dict[str, Any]:
    for connection in context["connections"]:
        if int(connection["id"]) == connection_id:
            return connection

    return context["connections"][0]


def label_from_identifier(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").title()


def without_empty_values(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in (None, "", []) and value is not False
    }


def _metric_filters(value: Any) -> list[Any]:
    if not value:
        return []

    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []

    return parsed if isinstance(parsed, list) else []
