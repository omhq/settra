from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

import asyncpg

from app.calculations.constants import (
    AGGREGATE_QUERY_TIMEOUT_SECONDS,
    DEFAULT_CALCULATION_ROW_LIMIT,
    MAX_CALCULATION_ROW_LIMIT,
)
from app.calculations.models import AggregateFilter, AggregateQueryNode
from app.common.config import (
    APP_DB_DATABASE,
    APP_DB_HOST,
    APP_DB_PASSWORD,
    APP_DB_PORT,
    APP_DB_USER,
    GOOGLE_DRIVE_KEY,
)
from app.db import db_connection
from app.destinations import runtime_from_connection
from app.errors import InvalidInputError, InvalidOperationError, ResourceNotFoundError

NUMERIC_POSTGRES_TYPES = {
    "bigint",
    "decimal",
    "double precision",
    "integer",
    "numeric",
    "real",
    "smallint",
}
AGGREGATE_SQL_FUNCTIONS = {
    "average": "AVG",
    "min": "MIN",
    "max": "MAX",
}
FILTER_SQL_OPERATORS = {
    "equals": "=",
    "not_equals": "<>",
    "greater_than": ">",
    "greater_than_or_equal": ">=",
    "less_than": "<",
    "less_than_or_equal": "<=",
}


@dataclass(frozen=True)
class AggregateSource:
    schema: str
    table: str
    column_types: dict[str, str]


@dataclass(frozen=True)
class AggregateExecution:
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    has_more: bool
    limit: int | None


async def validate_aggregate_query(
    node: AggregateQueryNode,
    *,
    organization_id: int,
    allowed_connection_ids: set[int],
) -> None:
    async with _source_session(
        node,
        organization_id=organization_id,
        allowed_connection_ids=allowed_connection_ids,
    ) as session:
        _pg, source = session
        compile_aggregate_query(node, source)


async def execute_aggregate_query(
    node: AggregateQueryNode,
    *,
    organization_id: int,
    allowed_connection_ids: set[int],
) -> AggregateExecution:
    async with _source_session(
        node,
        organization_id=organization_id,
        allowed_connection_ids=allowed_connection_ids,
    ) as session:
        pg, source = session

        try:
            sql, parameters, requested_limit = compile_aggregate_query(node, source)
            records = await pg.fetch(sql, *parameters)
        except asyncpg.PostgresError as exc:
            raise InvalidOperationError("Aggregate query could not run") from exc

    raw_rows = [dict(record) for record in records]
    has_more = requested_limit is not None and len(raw_rows) > requested_limit
    rows = raw_rows[:requested_limit] if requested_limit is not None else raw_rows

    return AggregateExecution(
        columns=[*node.group_by, *(measure.name for measure in node.measures)],
        rows=rows,
        row_count=len(rows),
        has_more=has_more,
        limit=requested_limit,
    )


def compile_aggregate_query(
    node: AggregateQueryNode,
    source: AggregateSource,
) -> tuple[str, list[Any], int | None]:
    _validate_source_members(node, source.column_types)
    selections = [
        f"{_quote_identifier(column)} AS {_quote_identifier(column)}"
        for column in node.group_by
    ]
    selections.extend(_measure_sql(measure) for measure in node.measures)
    parameters: list[Any] = []
    predicates = [_filter_sql(item, parameters) for item in node.filters]
    lines = [
        "SELECT " + ", ".join(selections),
        "FROM "
        + _quote_identifier(source.schema)
        + "."
        + _quote_identifier(source.table),
    ]

    if predicates:
        lines.append("WHERE " + " AND ".join(predicates))
    if node.group_by:
        quoted_groups = ", ".join(_quote_identifier(name) for name in node.group_by)
        lines.append("GROUP BY " + quoted_groups)
        lines.append("ORDER BY " + quoted_groups)

    requested_limit = _requested_limit(node)

    if requested_limit is not None:
        parameters.append(requested_limit + 1)
        lines.append(f"LIMIT ${len(parameters)}")

    return "\n".join(lines), parameters, requested_limit


@asynccontextmanager
async def _source_session(
    node: AggregateQueryNode,
    *,
    organization_id: int,
    allowed_connection_ids: set[int],
) -> AsyncIterator[tuple[asyncpg.Connection, AggregateSource]]:
    connection = await _connection_record(
        node.source.connection,
        organization_id=organization_id,
    )

    if int(connection["id"]) not in allowed_connection_ids:
        raise ResourceNotFoundError(
            f"Aggregate source connection '{node.source.connection}' is not in "
            "this calculation's collection"
        )

    try:
        runtime = runtime_from_connection(connection)
        runtime.require_built_in_postgres()
    except ValueError as exc:
        raise InvalidOperationError(
            "Aggregate queries require the built-in PostgreSQL destination"
        ) from exc

    async with _destination_connection(runtime) as pg:
        try:
            rows = await pg.fetch(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = $1 AND table_name = $2
                ORDER BY ordinal_position
                """,
                runtime.schema,
                node.source.table,
            )
        except asyncpg.PostgresError as exc:
            raise InvalidOperationError(
                "Aggregate source metadata could not be loaded"
            ) from exc

        column_types = {
            str(row["column_name"]): str(row["data_type"]).lower() for row in rows
        }

        if not column_types:
            raise ResourceNotFoundError(
                f"Aggregate source table '{node.source.table}' was not found"
            )

        source = AggregateSource(
            schema=runtime.schema,
            table=node.source.table,
            column_types=column_types,
        )

        _validate_source_members(node, source.column_types)
        yield pg, source


@asynccontextmanager
async def _destination_connection(runtime) -> AsyncIterator[asyncpg.Connection]:
    if _uses_app_database(runtime):
        async with db_connection() as pg:
            yield pg
        return

    try:
        pg = await asyncpg.connect(
            **runtime.asyncpg_connect_kwargs(),
            timeout=10,
            command_timeout=AGGREGATE_QUERY_TIMEOUT_SECONDS,
        )
    except (OSError, asyncpg.PostgresError) as exc:
        raise InvalidOperationError("Aggregate source is unavailable") from exc

    try:
        yield pg
    finally:
        await pg.close()


def _uses_app_database(runtime) -> bool:
    return runtime.asyncpg_connect_kwargs() == {
        "host": APP_DB_HOST,
        "port": APP_DB_PORT,
        "database": APP_DB_DATABASE,
        "user": APP_DB_USER,
        "password": APP_DB_PASSWORD,
    }


async def _connection_record(
    slug: str,
    *,
    organization_id: int,
) -> dict[str, Any]:
    async with db_connection() as db:
        row = await db.fetchrow(
            """
            SELECT c.id, c.name, c.slug, c.storage_key, c.organization_id,
                   c.destination_id, c.destination_schema,
                   d.name AS destination_name,
                   d.slug AS destination_slug,
                   d.type AS destination_type,
                   d.configuration AS destination_configuration,
                   d.is_builtin AS destination_is_builtin,
                   d.is_default AS destination_is_default
            FROM connections c
            JOIN destinations d ON d.id = c.destination_id
            WHERE c.slug = $1 AND c.plugin = $2 AND c.organization_id = $3
            """,
            slug,
            GOOGLE_DRIVE_KEY,
            organization_id,
        )

    if row is None:
        raise ResourceNotFoundError(
            f"Aggregate source connection '{slug}' was not found"
        )

    return dict(row)


def _validate_source_members(
    node: AggregateQueryNode,
    column_types: dict[str, str],
) -> None:
    referenced_columns = [
        *node.group_by,
        *(item.column for item in node.filters),
        *(measure.column for measure in node.measures if measure.column is not None),
    ]
    unknown = sorted(set(referenced_columns) - column_types.keys())

    if unknown:
        raise InvalidInputError(
            "Aggregate query references unknown columns: " + ", ".join(unknown)
        )

    non_numeric = sorted(
        measure.column
        for measure in node.measures
        if measure.column is not None
        and (
            measure.function in {"sum", "average"}
            or (
                node.result.kind == "scalar"
                and node.result.member == measure.name
                and measure.function in {"min", "max"}
            )
        )
        and column_types[measure.column] not in NUMERIC_POSTGRES_TYPES
    )
    if non_numeric:
        raise InvalidInputError(
            "Aggregate scalar arithmetic requires numeric columns: "
            + ", ".join(non_numeric)
        )


def _measure_sql(measure) -> str:
    alias = _quote_identifier(measure.name)

    if measure.function == "sum":
        return f"COALESCE(SUM({_quote_identifier(measure.column)}), 0) AS {alias}"
    if measure.function == "count":
        argument = "*" if measure.column is None else _quote_identifier(measure.column)
        return f"COUNT({argument}) AS {alias}"
    if measure.function == "count_distinct":
        return f"COUNT(DISTINCT {_quote_identifier(measure.column)}) AS {alias}"

    function = AGGREGATE_SQL_FUNCTIONS[measure.function]

    return f"{function}({_quote_identifier(measure.column)}) AS {alias}"


def _filter_sql(item: AggregateFilter, parameters: list[Any]) -> str:
    column = _quote_identifier(item.column)

    if item.operator == "is_null":
        return f"{column} IS NULL"
    if item.operator == "not_null":
        return f"{column} IS NOT NULL"
    if item.operator in {"in", "not_in"}:
        placeholders = []

        for value in item.values or []:
            parameters.append(value)
            placeholders.append(f"${len(parameters)}")

        keyword = "IN" if item.operator == "in" else "NOT IN"

        return f"{column} {keyword} ({', '.join(placeholders)})"

    parameters.append(item.value)
    return f"{column} {FILTER_SQL_OPERATORS[item.operator]} ${len(parameters)}"


def _requested_limit(node: AggregateQueryNode) -> int | None:
    if node.result.kind == "scalar":
        return None

    limit = node.limit if node.limit is not None else DEFAULT_CALCULATION_ROW_LIMIT

    if isinstance(limit, bool) or not 1 <= limit <= MAX_CALCULATION_ROW_LIMIT:
        raise InvalidInputError(
            f"Aggregate query limit must be between 1 and {MAX_CALCULATION_ROW_LIMIT}"
        )

    return limit


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'
