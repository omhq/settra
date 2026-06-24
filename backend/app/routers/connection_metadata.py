import re
import json

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import asyncpg
import aiofiles
import aiosqlite

from fastapi import HTTPException

from app.agent.consts import (
    GOOGLE_SHEETS_CELL_SAMPLE_MAX_CELLS,
    GOOGLE_SHEETS_CELL_SAMPLE_ROWS,
    STEAMPIPE_DB_PASSWORD,
    STEAMPIPE_HOST,
    STEAMPIPE_PORT,
    TABLE_SAMPLE_MAX_COLUMNS,
    TABLE_SAMPLE_ROWS,
    TABLE_SAMPLE_VALUE_MAX_CHARS,
)
from app.agent.metadata import get_schema_with_descriptions
from app.agent.metadata.utils import quote_ident
from app.db import DB_PATH
from app.routers.connection_config import read_connection_credentials
from app.routers.constants import (
    DATA_DIR,
)

MAX_SAMPLE_ROWS = 50
MAX_PROFILE_ROWS = 500
PROFILE_EXAMPLE_LIMIT = 5
SENSITIVE_COLUMN_PATTERN = re.compile(
    r"(^|_)(api[_-]?key|authorization|credential|password|private[_-]?key|"
    r"refresh[_-]?token|secret|token)($|_)",
    re.IGNORECASE,
)


async def generate_connection_metadata(connection_id: int) -> dict[str, Any]:
    connection = await _connection_record(connection_id)
    slug, plugin = connection["slug"], connection["plugin"]
    credentials = await read_connection_credentials(slug)

    try:
        live_schema = await get_schema_with_descriptions(
            slug,
            use_cache=False,
            refresh_steampipe_cache=True,
            connection_credentials=credentials,
        )
    except Exception as exc:
        raise HTTPException(503, f"metadata refresh failed: {exc}") from exc

    if not live_schema:
        raise HTTPException(
            404, f"No tables found for schema '{slug}' - is the plugin loaded?"
        )

    return await write_connection_metadata_cache(
        connection_id=connection_id,
        slug=slug,
        plugin=plugin,
        live_schema=live_schema,
    )


async def sample_connection_table(
    connection_id: int,
    table_name: str,
    *,
    limit: int = TABLE_SAMPLE_ROWS,
    columns: list[str] | None = None,
) -> dict[str, Any]:
    """Return bounded sample rows for one saved connection table."""

    return await _sample_connection_table(
        connection_id,
        table_name,
        limit=limit,
        columns=columns,
        max_limit=MAX_SAMPLE_ROWS,
    )


async def _sample_connection_table(
    connection_id: int,
    table_name: str,
    *,
    limit: int,
    columns: list[str] | None,
    max_limit: int,
) -> dict[str, Any]:
    connection, table = await _connection_table(connection_id, table_name)
    selected_columns = _selected_columns(table, columns)
    row_limit = _bounded_int(
        limit,
        default=TABLE_SAMPLE_ROWS,
        minimum=1,
        maximum=max_limit,
    )

    pg = await _steampipe_connection()

    try:
        rows = (
            await _sample_google_sheets_virtual_table(
                pg,
                connection["slug"],
                table,
                selected_columns,
                row_limit,
            )
            if _is_google_sheets_virtual_table(table)
            else await _sample_physical_table(
                pg,
                connection["slug"],
                table["name"],
                selected_columns,
                row_limit,
            )
        )
    finally:
        await pg.close()

    return {
        "connection": _connection_summary(connection),
        "table": _table_summary(table),
        "limit": row_limit,
        "columns": [_column_summary(column) for column in selected_columns],
        "rows": _json_rows(rows, selected_columns),
    }


async def profile_connection_table(
    connection_id: int,
    table_name: str,
    *,
    limit: int = MAX_PROFILE_ROWS,
    columns: list[str] | None = None,
) -> dict[str, Any]:
    """Return a bounded sample-based column profile for one connection table."""

    sample = await _sample_connection_table(
        connection_id,
        table_name,
        limit=_bounded_int(
            limit,
            default=MAX_PROFILE_ROWS,
            minimum=1,
            maximum=MAX_PROFILE_ROWS,
        ),
        columns=columns,
        max_limit=MAX_PROFILE_ROWS,
    )
    rows = sample["rows"]

    return {
        "connection": sample["connection"],
        "table": sample["table"],
        "profile_scope": "sampled_rows",
        "sampled_row_count": len(rows),
        "sample_limit": sample["limit"],
        "columns": [
            _profile_column(column, rows)
            for column in sample["columns"]
        ],
    }


async def write_connection_metadata_cache(
    *,
    connection_id: int,
    slug: str,
    plugin: str,
    live_schema: list[dict[str, Any]],
) -> dict[str, Any]:
    metadata = {
        "connection_id": connection_id,
        "slug": slug,
        "plugin": plugin,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tables": {
            table_name: {
                **(
                    {"description": str(table.get("description") or "")}
                    if table.get("description")
                    else {}
                ),
                **(
                    {"metadata": table.get("metadata")}
                    if isinstance(table.get("metadata"), dict)
                    else {}
                ),
                "columns": columns,
                "ddl": _ddl(slug, table_name, columns),
            }
            for table_name, table, columns in _metadata_tables(live_schema)
        },
    }
    metadata_dir = DATA_DIR / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    out_path = metadata_dir / f"{slug}.json"

    async with aiofiles.open(out_path, "w") as f:
        await f.write(json.dumps(metadata, indent=2))

    return metadata


def _metadata_tables(
    live_schema: list[dict[str, Any]],
) -> list[tuple[str, dict[str, Any], list[dict[str, Any]]]]:
    tables = []

    for table in live_schema:
        table_name = str(table.get("name") or "")

        if not table_name:
            continue

        raw_columns = table.get("columns", [])
        columns = raw_columns if isinstance(raw_columns, list) else []

        tables.append((table_name, table, columns))

    return sorted(tables, key=lambda item: item[0])


def _ddl(schema: str, table_name: str, columns: list) -> str:
    lines = []

    for column in columns:
        line = f"  {column['name']} {column['type'].upper()}"

        if not column["nullable"]:
            line += " NOT NULL"
        if column.get("description"):
            line += f"  -- {column['description']}"

        lines.append(line)

    return f"CREATE TABLE {schema}.{table_name} (\n" + ",\n".join(lines) + "\n);"


async def _connection_record(connection_id: int) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            """
            SELECT id, name, slug, plugin, status, created_at
            FROM connections
            WHERE id = ?
            """,
            (connection_id,),
        ) as cur:
            row = await cur.fetchone()

    if not row:
        raise HTTPException(404, "Connection not found")

    return dict(row)


async def _connection_table(
    connection_id: int,
    table_name: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    connection = await _connection_record(connection_id)
    credentials = await read_connection_credentials(connection["slug"])
    schema = await get_schema_with_descriptions(
        connection["slug"],
        use_cache=True,
        connection_credentials=credentials,
    )
    table = next(
        (
            table
            for table in schema
            if isinstance(table, dict) and table.get("name") == table_name
        ),
        None,
    )

    if not table:
        raise HTTPException(
            404,
            f"Table '{table_name}' was not found for connection {connection_id}",
        )

    return connection, table


async def _steampipe_connection() -> asyncpg.Connection:
    return await asyncpg.connect(
        host=STEAMPIPE_HOST,
        port=STEAMPIPE_PORT,
        database="steampipe",
        user="steampipe",
        password=STEAMPIPE_DB_PASSWORD,
        timeout=10,
        command_timeout=15,
    )


def _selected_columns(
    table: dict[str, Any],
    requested: list[str] | None,
) -> list[dict[str, Any]]:
    table_columns = [
        column
        for column in table.get("columns", [])
        if isinstance(column, dict) and isinstance(column.get("name"), str)
    ]
    by_name = {column["name"]: column for column in table_columns}

    if requested:
        unknown = [name for name in requested if name not in by_name]

        if unknown:
            raise HTTPException(400, f"Unknown columns: {', '.join(unknown)}")

        selected = [by_name[name] for name in requested]
    else:
        selected = table_columns[:TABLE_SAMPLE_MAX_COLUMNS]

    if len(selected) > TABLE_SAMPLE_MAX_COLUMNS:
        raise HTTPException(
            400,
            f"At most {TABLE_SAMPLE_MAX_COLUMNS} columns can be sampled at once",
        )

    if not selected:
        raise HTTPException(400, "No columns available to sample")

    return selected


async def _sample_physical_table(
    pg: asyncpg.Connection,
    schema: str,
    table_name: str,
    columns: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    select_list = ", ".join(quote_ident(column["name"]) for column in columns)
    rows = await pg.fetch(
        f"""
        SELECT {select_list}
        FROM {quote_ident(schema)}.{quote_ident(table_name)}
        LIMIT $1
        """,
        limit,
    )

    return [dict(row) for row in rows]


async def _sample_google_sheets_virtual_table(
    pg: asyncpg.Connection,
    schema: str,
    table: dict[str, Any],
    columns: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    metadata = table.get("metadata") if isinstance(table.get("metadata"), dict) else {}
    sheet_name = str(metadata.get("sheet_name") or table["name"])
    header_row = int(metadata.get("header_row") or 1)
    source_columns = {
        str(column["name"]): str(column.get("source_column") or "")
        for column in columns
        if column.get("source_column")
    }

    if not source_columns:
        return []

    max_rows_by_cell_cap = max(
        1,
        GOOGLE_SHEETS_CELL_SAMPLE_MAX_CELLS // max(1, len(source_columns)),
    )
    row_limit = min(
        limit,
        max(GOOGLE_SHEETS_CELL_SAMPLE_ROWS, max_rows_by_cell_cap),
    )
    row_numbers = await pg.fetch(
        f"""
        SELECT row
        FROM {quote_ident(schema)}.googlesheets_cell
        WHERE sheet_name = $1
          AND row > $2
          AND value IS NOT NULL
          AND value <> ''
        GROUP BY row
        ORDER BY row
        LIMIT $3
        """,
        sheet_name,
        header_row,
        row_limit,
    )
    rows = [int(row["row"]) for row in row_numbers]

    if not rows:
        return []

    cells = await pg.fetch(
        f"""
        SELECT row, col, value
        FROM {quote_ident(schema)}.googlesheets_cell
        WHERE sheet_name = $1
          AND row = ANY($2::bigint[])
          AND col = ANY($3::text[])
        ORDER BY row, col
        LIMIT $4
        """,
        sheet_name,
        rows,
        list(source_columns.values()),
        min(
            len(rows) * len(source_columns),
            GOOGLE_SHEETS_CELL_SAMPLE_MAX_CELLS,
        ),
    )
    column_by_letter = {letter: name for name, letter in source_columns.items()}
    row_map = {
        row: {column["name"]: None for column in columns}
        for row in rows
    }

    for cell in cells:
        column_name = column_by_letter.get(str(cell["col"]))

        if column_name:
            row_map[int(cell["row"])][column_name] = cell["value"]

    return [row_map[row] for row in rows]


def _is_google_sheets_virtual_table(table: dict[str, Any]) -> bool:
    metadata = table.get("metadata") if isinstance(table.get("metadata"), dict) else {}

    return bool(metadata.get("virtual") and metadata.get("source") == "googlesheets_cell")


def _connection_summary(connection: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": connection["id"],
        "name": connection["name"],
        "slug": connection["slug"],
        "plugin": connection["plugin"],
        "status": connection["status"],
    }


def _table_summary(table: dict[str, Any]) -> dict[str, Any]:
    metadata = table.get("metadata") if isinstance(table.get("metadata"), dict) else {}

    return {
        "name": table["name"],
        "description": table.get("description") or "",
        "metadata": metadata,
    }


def _column_summary(column: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": column["name"],
        "type": column.get("type"),
        "nullable": bool(column.get("nullable")),
        "description": column.get("description") or "",
        **(
            {"source_column": column.get("source_column")}
            if column.get("source_column")
            else {}
        ),
    }


def _profile_column(
    column: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    name = column["name"]
    values = [row.get(name) for row in rows]
    normalized_values = [_normalize_profile_value(value) for value in values]
    non_empty_values = [
        value for value in normalized_values if value is not None and value != ""
    ]
    examples: list[Any] = []

    for value in non_empty_values:
        if value not in examples:
            examples.append(value)

        if len(examples) >= PROFILE_EXAMPLE_LIMIT:
            break

    return {
        **_column_summary(column),
        "sampled_count": len(values),
        "null_count": sum(value is None for value in values),
        "empty_string_count": sum(value == "" for value in normalized_values),
        "distinct_sample_count": len(set(non_empty_values)),
        "inferred_type": _infer_type(non_empty_values, str(column.get("type") or "")),
        "example_values": examples,
    }


def _infer_type(values: list[Any], declared_type: str) -> str:
    if not values:
        return "unknown"

    declared = declared_type.lower()

    if any(token in declared for token in ("integer", "numeric", "double", "real")):
        return "number"

    if "bool" in declared:
        return "boolean"

    if "date" in declared or "time" in declared:
        return "time"

    text_values = [str(value).strip() for value in values]

    if all(_looks_boolean(value) for value in text_values):
        return "boolean"

    if all(_looks_number(value) for value in text_values):
        return "number"

    if all(_looks_date(value) for value in text_values):
        return "time"

    if all("@" in value and "." in value.split("@")[-1] for value in text_values):
        return "email"

    return "string"


def _looks_boolean(value: str) -> bool:
    return value.lower() in {"true", "false", "yes", "no", "0", "1"}


def _looks_number(value: str) -> bool:
    if not re.fullmatch(r"\s*[-+]?[$€£¥₹]?\s*\d[\d,]*(\.\d+)?\s*%?\s*", value):
        return False

    cleaned = re.sub(r"[^0-9.\-]", "", value)

    if cleaned in {"", ".", "-", "-."}:
        return False

    try:
        Decimal(cleaned)
        return True
    except Exception:
        return False


def _looks_date(value: str) -> bool:
    if not re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", value):
        return False

    try:
        datetime.fromisoformat(value.replace("/", "-"))
        return True
    except ValueError:
        return False


def _json_rows(
    rows: list[dict[str, Any]],
    columns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            column["name"]: _json_value(row.get(column["name"]), column["name"])
            for column in columns
        }
        for row in rows
    ]


def _json_value(value: Any, column_name: str) -> Any:
    if value is None:
        return None

    if SENSITIVE_COLUMN_PATTERN.search(column_name):
        return "[redacted]"

    if isinstance(value, (str, int, float, bool)):
        return _truncate_value(value)

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, (datetime,)):
        return value.isoformat()

    return _truncate_value(str(value))


def _normalize_profile_value(value: Any) -> Any:
    if isinstance(value, str):
        return _truncate_value(value.strip())

    return _json_value(value, "")


def _truncate_value(value: Any) -> Any:
    if not isinstance(value, str) or len(value) <= TABLE_SAMPLE_VALUE_MAX_CHARS:
        return value

    return value[: TABLE_SAMPLE_VALUE_MAX_CHARS - 1] + "…"


def _bounded_int(
    value: int,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default

    return max(minimum, min(maximum, parsed))
