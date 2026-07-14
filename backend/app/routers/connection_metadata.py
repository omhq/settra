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
CONNECTION_METADATA_COLLECTIONS = ("columns", "source_metadata")
DEFAULT_CONNECTION_METADATA_LIMIT = 5
MAX_CONNECTION_METADATA_LIMIT = 5
DEFAULT_CONNECTION_METADATA_COLUMN_LIMIT = 10
MAX_CONNECTION_METADATA_COLUMN_LIMIT = 10
CONNECTION_METADATA_TABLE_DESCRIPTION_LIMIT = 500
CONNECTION_METADATA_COLUMN_DESCRIPTION_LIMIT = 300
CONNECTION_METADATA_VALUE_LIMIT = 500
CONNECTION_METADATA_SOURCE_ITEM_LIMIT = 50
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


async def bounded_connection_metadata(
    connection_id: int,
    *,
    search: str | None = None,
    include: list[str] | None = None,
    cursor: int = 0,
    limit: int = DEFAULT_CONNECTION_METADATA_LIMIT,
    column_cursor: int = 0,
    column_limit: int = DEFAULT_CONNECTION_METADATA_COLUMN_LIMIT,
) -> dict[str, Any]:
    """Refresh metadata, then return a bounded table catalog projection."""

    metadata = await generate_connection_metadata(connection_id)

    return connection_metadata_catalog(
        metadata,
        search=search,
        include=include,
        cursor=cursor,
        limit=limit,
        column_cursor=column_cursor,
        column_limit=column_limit,
    )


def connection_metadata_catalog(
    metadata: dict[str, Any],
    *,
    search: str | None = None,
    include: list[str] | None = None,
    cursor: int = 0,
    limit: int = DEFAULT_CONNECTION_METADATA_LIMIT,
    column_cursor: int = 0,
    column_limit: int = DEFAULT_CONNECTION_METADATA_COLUMN_LIMIT,
) -> dict[str, Any]:
    """Project full cached metadata into a bounded, paginated response."""

    _validate_connection_metadata_page(
        cursor=cursor,
        limit=limit,
        column_cursor=column_cursor,
        column_limit=column_limit,
    )
    requested_collections = list(
        dict.fromkeys(["columns"] if include is None else include)
    )
    invalid_collections = [
        name
        for name in requested_collections
        if name not in CONNECTION_METADATA_COLLECTIONS
    ]

    if invalid_collections:
        raise HTTPException(
            422,
            "include contains unsupported collections: "
            f"{', '.join(invalid_collections)}",
        )

    raw_tables = metadata.get("tables")
    tables = [
        (str(name), table)
        for name, table in (raw_tables.items() if isinstance(raw_tables, dict) else [])
        if isinstance(table, dict)
    ]
    normalized_search = _normalize_metadata_search(search or "")

    if normalized_search:
        scored_tables = [
            (_metadata_table_search_score(normalized_search, name, table), name, table)
            for name, table in tables
        ]
        tables = [
            (name, table)
            for score, name, table in sorted(
                scored_tables,
                key=lambda item: (-item[0], item[1]),
            )
            if score > 0
        ]

    total = len(tables)
    table_page = tables[cursor : cursor + limit]
    next_cursor = cursor + len(table_page)

    return {
        "connection_id": metadata.get("connection_id"),
        "slug": metadata.get("slug"),
        "plugin": metadata.get("plugin"),
        "tables": [
            _connection_metadata_table_summary(
                name,
                table,
                requested_collections=requested_collections,
                column_cursor=column_cursor,
                column_limit=column_limit,
            )
            for name, table in table_page
        ],
        "page": {
            "total": total,
            "next_cursor": next_cursor if next_cursor < total else None,
        },
    }


def _connection_metadata_table_summary(
    name: str,
    table: dict[str, Any],
    *,
    requested_collections: list[str],
    column_cursor: int,
    column_limit: int,
) -> dict[str, Any]:
    description, description_truncated = _bounded_metadata_text(
        table.get("description"),
        CONNECTION_METADATA_TABLE_DESCRIPTION_LIMIT,
    )
    raw_columns = table.get("columns")
    columns = [
        column
        for column in (raw_columns if isinstance(raw_columns, list) else [])
        if isinstance(column, dict)
    ]
    source_metadata = table.get("metadata")
    result: dict[str, Any] = {
        "name": name,
        "column_count": len(columns),
    }

    if description:
        result["description"] = description
    if description_truncated:
        result["description_truncated"] = True
    if isinstance(source_metadata, dict) and source_metadata:
        result["source_metadata_available"] = True

    if "columns" in requested_collections:
        column_page = columns[column_cursor : column_cursor + column_limit]
        next_column_cursor = column_cursor + len(column_page)
        result["columns"] = [
            _connection_metadata_column_summary(column) for column in column_page
        ]
        result["column_page"] = {
            "total": len(columns),
            "next_column_cursor": (
                next_column_cursor if next_column_cursor < len(columns) else None
            ),
        }

    if "source_metadata" in requested_collections:
        if isinstance(source_metadata, dict) and source_metadata:
            result["source_metadata"] = _bounded_source_metadata(source_metadata)

    return result


def _connection_metadata_column_summary(column: dict[str, Any]) -> dict[str, Any]:
    description, description_truncated = _bounded_metadata_text(
        column.get("description"),
        CONNECTION_METADATA_COLUMN_DESCRIPTION_LIMIT,
    )
    result: dict[str, Any] = {
        "name": _bounded_metadata_text(column.get("name"), 200)[0],
        "type": _bounded_metadata_text(column.get("type"), 100)[0],
        "nullable": bool(column.get("nullable")),
    }

    if description:
        result["description"] = description
    if column.get("source_column"):
        result["source_column"] = _bounded_metadata_text(
            column.get("source_column"),
            100,
        )[0]

    if description_truncated:
        result["description_truncated"] = True

    return result


def _validate_connection_metadata_page(
    *,
    cursor: int,
    limit: int,
    column_cursor: int,
    column_limit: int,
) -> None:
    if cursor < 0:
        raise HTTPException(422, "cursor must be at least 0")
    if not 1 <= limit <= MAX_CONNECTION_METADATA_LIMIT:
        raise HTTPException(
            422,
            f"limit must be between 1 and {MAX_CONNECTION_METADATA_LIMIT}",
        )
    if column_cursor < 0:
        raise HTTPException(422, "column_cursor must be at least 0")
    if not 1 <= column_limit <= MAX_CONNECTION_METADATA_COLUMN_LIMIT:
        raise HTTPException(
            422,
            "column_limit must be between 1 and "
            f"{MAX_CONNECTION_METADATA_COLUMN_LIMIT}",
        )


def _normalize_metadata_search(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def _metadata_table_search_score(
    normalized_query: str,
    name: str,
    table: dict[str, Any],
) -> int:
    normalized_name = _normalize_metadata_search(name)
    raw_columns = table.get("columns")
    columns = raw_columns if isinstance(raw_columns, list) else []
    search_text = _normalize_metadata_search(
        " ".join(
            [
                name,
                str(table.get("description") or ""),
                *[
                    " ".join(
                        [
                            str(column.get("name") or ""),
                            str(column.get("description") or ""),
                        ]
                    )
                    for column in columns
                    if isinstance(column, dict)
                ],
            ]
        )
    )

    if normalized_query == normalized_name:
        return 1000
    if normalized_query in normalized_name:
        return 900
    if normalized_query in search_text:
        return 800

    query_tokens = normalized_query.split()
    text_tokens = set(search_text.split())

    return 100 if all(token in text_tokens for token in query_tokens) else 0


def _bounded_source_metadata(value: dict[str, Any]) -> dict[str, Any]:
    budget = [CONNECTION_METADATA_SOURCE_ITEM_LIMIT]
    bounded = _bounded_source_metadata_value(value, depth=0, budget=budget)

    return bounded if isinstance(bounded, dict) else {}


def _bounded_source_metadata_value(
    value: Any,
    *,
    depth: int,
    budget: list[int],
) -> Any:
    if budget[0] <= 0:
        return "[truncated]"

    if isinstance(value, dict):
        if depth >= 3:
            budget[0] -= 1
            return "[truncated]"

        result: dict[str, Any] = {}

        for raw_key, item in value.items():
            if budget[0] <= 0:
                result["_truncated"] = True
                break

            budget[0] -= 1
            key = str(_bounded_metadata_text(str(raw_key), 100)[0])
            result[key] = _bounded_source_metadata_value(
                item,
                depth=depth + 1,
                budget=budget,
            )

        return result

    if isinstance(value, list):
        if depth >= 3:
            budget[0] -= 1
            return "[truncated]"

        result = []

        for item in value:
            if budget[0] <= 0:
                result.append("[truncated]")
                break

            budget[0] -= 1
            result.append(
                _bounded_source_metadata_value(
                    item,
                    depth=depth + 1,
                    budget=budget,
                )
            )

        return result

    budget[0] -= 1

    if value is None or isinstance(value, (bool, int, float)):
        return value

    return _bounded_metadata_text(str(value), CONNECTION_METADATA_VALUE_LIMIT)[0]


def _bounded_metadata_text(value: Any, max_chars: int) -> tuple[Any, bool]:
    if not isinstance(value, str) or len(value) <= max_chars:
        return value, False

    return f"{value[: max_chars - 1].rstrip()}…", True


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

    json_rows, truncated_values = _json_rows(rows, selected_columns)

    return {
        "connection": _connection_summary(connection),
        "table": _table_summary(table),
        "limit": row_limit,
        "columns": [_column_summary(column) for column in selected_columns],
        "rows": json_rows,
        "truncated_values": truncated_values,
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
        "columns": [_profile_column(column, rows) for column in sample["columns"]],
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
    row_map = {row: {column["name"]: None for column in columns} for row in rows}

    for cell in cells:
        column_name = column_by_letter.get(str(cell["col"]))

        if column_name:
            row_map[int(cell["row"])][column_name] = cell["value"]

    return [row_map[row] for row in rows]


def _is_google_sheets_virtual_table(table: dict[str, Any]) -> bool:
    metadata = table.get("metadata") if isinstance(table.get("metadata"), dict) else {}

    return bool(
        metadata.get("virtual") and metadata.get("source") == "googlesheets_cell"
    )


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
) -> tuple[list[dict[str, Any]], list[str]]:
    json_rows: list[dict[str, Any]] = []
    truncated_columns: set[str] = set()

    for row in rows:
        json_row: dict[str, Any] = {}

        for column in columns:
            name = column["name"]
            value, truncated = _json_value_with_truncation(row.get(name), name)
            json_row[name] = value

            if truncated:
                truncated_columns.add(name)

        json_rows.append(json_row)

    return json_rows, [
        column["name"] for column in columns if column["name"] in truncated_columns
    ]


def _json_value(value: Any, column_name: str) -> Any:
    return _json_value_with_truncation(value, column_name)[0]


def _json_value_with_truncation(
    value: Any,
    column_name: str,
) -> tuple[Any, bool]:
    if value is None:
        return None, False

    if SENSITIVE_COLUMN_PATTERN.search(column_name):
        return "[redacted]", False

    if isinstance(value, (str, int, float, bool)):
        return _truncate_value_with_status(value)

    if isinstance(value, Decimal):
        return _truncate_value_with_status(str(value))

    if isinstance(value, (datetime,)):
        return _truncate_value_with_status(value.isoformat())

    return _truncate_value_with_status(str(value))


def _normalize_profile_value(value: Any) -> Any:
    if isinstance(value, str):
        return _truncate_value(value.strip())

    return _json_value(value, "")


def _truncate_value(value: Any) -> Any:
    return _truncate_value_with_status(value)[0]


def _truncate_value_with_status(value: Any) -> tuple[Any, bool]:
    if not isinstance(value, str) or len(value) <= TABLE_SAMPLE_VALUE_MAX_CHARS:
        return value, False

    return value[: TABLE_SAMPLE_VALUE_MAX_CHARS - 1] + "…", True


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
