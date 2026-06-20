import json
import time
import logging

from typing import Any

import aiosqlite

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from app.agent.llm import AgentLLM, AgentLLMError
from app.agent.metadata import get_schema_with_descriptions
from app.db import DB_PATH
from app.routers.connection_config import read_connection_credentials
from app.model_configs import ModelConfigError, build_llm, get_model_config
from app.routers.connection_metadata import write_connection_metadata_cache
from app.routers.chat_diagnostics import (
    connection_diagnostics,
    model_diagnostics,
    token_usage_summary,
    utc_now,
)
from app.semantic.introspection import run_ai_semantic_introspection
from app.semantic.schemas import (
    AiIntrospectRequest,
    CreateMetricRequest,
    CreateRelationshipRequest,
    UpdateMetricRequest,
    UpdateRelationshipRequest,
    UpdateSemanticColumnRequest,
    UpdateSemanticTableRequest,
)
from app.semantic.loader import (
    build_semantic_contract,
    delete_connection_semantics,
    discover_relationships,
    introspect_connection_semantics,
)
from app.utils import jsonable

logger = logging.getLogger(__name__)

SEMANTIC_OBJECT_KINDS = {"tables", "columns", "metrics", "relationships"}
SEMANTIC_OBJECT_FILTERS = {"all", "review", "approved", "ignored", "hidden"}

SEMANTIC_TABLE_FIELDS = [
    "id",
    "connection_id",
    "source_name",
    "schema_name",
    "table_name",
    "label",
    "description",
    "table_type",
    "grain",
    "primary_time_column",
    "metadata_json",
    "hidden",
    "status",
    "created_at",
    "updated_at",
]

SEMANTIC_COLUMN_FIELDS = [
    "id",
    "semantic_table_id",
    "column_name",
    "label",
    "description",
    "data_type",
    "semantic_type",
    "expression",
    "unit",
    "is_dimension",
    "is_measure",
    "is_time",
    "is_id",
    "is_foreign_key",
    "hidden",
    "status",
    "created_at",
    "updated_at",
]

SEMANTIC_METRIC_FIELDS = [
    "id",
    "connection_id",
    "semantic_table_id",
    "name",
    "label",
    "expression",
    "filters_json",
    "time_column",
    "unit",
    "status",
    "created_at",
    "updated_at",
]


async def fetch_one_dict(
    db: aiosqlite.Connection,
    sql: str,
    params: tuple[Any, ...] = (),
) -> dict[str, Any] | None:
    db.row_factory = aiosqlite.Row
    async with db.execute(sql, params) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def fetch_all_dicts(
    db: aiosqlite.Connection,
    sql: str,
    params: tuple[Any, ...] | list[Any] = (),
) -> list[dict[str, Any]]:
    db.row_factory = aiosqlite.Row
    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [dict(row) for row in rows]


def parse_connection_ids(value: str) -> list[int]:
    try:
        ids = [int(x.strip()) for x in value.split(",") if x.strip()]
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="connection_ids must be comma-separated integers",
        ) from exc

    if not ids:
        raise HTTPException(
            status_code=400,
            detail="At least one connection id is required",
        )

    return ids


def parse_optional_connection_ids(value: str | None) -> list[int]:
    if not value:
        return []

    return parse_connection_ids(value)


def parse_semantic_object_kind(value: str) -> str:
    if value not in SEMANTIC_OBJECT_KINDS:
        raise HTTPException(
            status_code=400,
            detail="kind must be one of tables, columns, metrics, relationships",
        )

    return value


def parse_semantic_object_filter(value: str) -> str:
    if value not in SEMANTIC_OBJECT_FILTERS:
        raise HTTPException(
            status_code=400,
            detail="filter must be one of all, review, approved, ignored, hidden",
        )

    return value


def semantic_status_filter_condition(
    semantic_filter: str,
    status_expr: str,
    hidden_expr: str,
) -> str | None:
    if semantic_filter == "all":
        return None

    if semantic_filter == "hidden":
        return hidden_expr

    visible_expr = f"NOT {hidden_expr}"

    if semantic_filter == "review":
        return f"{visible_expr} AND {status_expr} IN ('draft', 'suggested')"

    if semantic_filter == "approved":
        return f"{visible_expr} AND {status_expr} IN ('confirmed', 'published')"

    if semantic_filter == "ignored":
        return f"{visible_expr} AND {status_expr} IN ('ignored', 'disabled')"

    return None


def semantic_count_select(status_expr: str, hidden_expr: str) -> str:
    visible_expr = f"NOT {hidden_expr}"

    return f"""
        COUNT(*) AS count_all,
        COALESCE(SUM(CASE WHEN {hidden_expr} THEN 1 ELSE 0 END), 0)
            AS count_hidden,
        COALESCE(SUM(CASE
            WHEN {visible_expr}
             AND {status_expr} IN ('draft', 'suggested')
            THEN 1 ELSE 0 END), 0) AS count_review,
        COALESCE(SUM(CASE
            WHEN {visible_expr}
             AND {status_expr} IN ('confirmed', 'published')
            THEN 1 ELSE 0 END), 0) AS count_approved,
        COALESCE(SUM(CASE
            WHEN {visible_expr}
             AND {status_expr} IN ('ignored', 'disabled')
            THEN 1 ELSE 0 END), 0) AS count_ignored
    """


def where_clause(conditions: list[str]) -> str:
    if not conditions:
        return ""

    return "WHERE " + " AND ".join(f"({condition})" for condition in conditions)


def add_search_condition(
    conditions: list[str],
    params: list[Any],
    query: str | None,
    columns: list[str],
) -> None:
    normalized_query = (query or "").strip().lower()

    if not normalized_query:
        return

    conditions.append(
        "("
        + " OR ".join(f"LOWER(COALESCE({column}, '')) LIKE ?" for column in columns)
        + ")"
    )
    params.extend([f"%{normalized_query}%"] * len(columns))


def add_connection_filter(
    conditions: list[str],
    params: list[Any],
    connection_ids: list[int],
    column_expr: str,
) -> None:
    if not connection_ids:
        return

    placeholders = ",".join("?" for _ in connection_ids)

    conditions.append(f"{column_expr} IN ({placeholders})")
    params.extend(connection_ids)


def add_relationship_connection_filter(
    conditions: list[str],
    params: list[Any],
    connection_ids: list[int],
) -> None:
    if not connection_ids:
        return

    placeholders = ",".join("?" for _ in connection_ids)

    conditions.append(f"""
        (
            r.from_connection_id IN ({placeholders})
            OR r.to_connection_id IN ({placeholders})
        )
        """)
    params.extend(connection_ids)
    params.extend(connection_ids)


def prefixed_table_select(alias: str, prefix: str = "table") -> str:
    return ", ".join(
        f"{alias}.{field} AS {prefix}_{field}" for field in SEMANTIC_TABLE_FIELDS
    )


def semantic_table_from_prefixed(
    row: dict[str, Any],
    prefix: str = "table",
) -> dict[str, Any]:
    table = normalize_semantic_table(
        {
            field: row[f"{prefix}_{field}"]
            for field in SEMANTIC_TABLE_FIELDS
            if f"{prefix}_{field}" in row
        }
    )
    table["columns"] = []

    return table


def semantic_columns_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "column": {
            field: row[field] for field in SEMANTIC_COLUMN_FIELDS if field in row
        },
        "table": semantic_table_from_prefixed(row),
    }


def semantic_metrics_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "metric": {
            field: row[field] for field in SEMANTIC_METRIC_FIELDS if field in row
        },
        "table": semantic_table_from_prefixed(row),
    }


def semantic_page_payload(
    kind: str,
    items: list[Any],
    counts: dict[str, int],
    semantic_filter: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    total = counts.get(semantic_filter, 0)

    return {
        "kind": kind,
        "items": items,
        "total": total,
        "counts": counts,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
    }


async def semantic_counts(
    db: aiosqlite.Connection,
    from_sql: str,
    conditions: list[str],
    params: list[Any],
    status_expr: str,
    hidden_expr: str,
) -> dict[str, int]:
    row = await fetch_one_dict(
        db,
        f"""
        SELECT {semantic_count_select(status_expr, hidden_expr)}
        {from_sql}
        {where_clause(conditions)}
        """,
        tuple(params),
    )
    row = row or {}

    return {
        "all": int(row.get("count_all") or 0),
        "review": int(row.get("count_review") or 0),
        "approved": int(row.get("count_approved") or 0),
        "ignored": int(row.get("count_ignored") or 0),
        "hidden": int(row.get("count_hidden") or 0),
    }


def update_fields(payload: BaseModel, allowed: set[str]) -> tuple[str, list[Any]]:
    data = payload.model_dump(exclude_unset=True)
    sets: list[str] = []
    values: list[Any] = []

    for key, value in data.items():
        if key not in allowed:
            continue

        if isinstance(value, bool):
            value = int(value)

        if key == "filters":
            key = "filters_json"
            value = json.dumps(value)
        elif key == "metadata":
            key = "metadata_json"
            value = json.dumps(value or {})

        sets.append(f"{key} = ?")
        values.append(value)

    if sets:
        sets.append("updated_at = CURRENT_TIMESTAMP")

    return ", ".join(sets), values


def decode_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value

    if not value:
        return {}

    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def normalize_semantic_table(table: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(table)
    metadata = decode_metadata(normalized.pop("metadata_json", None))
    legacy_header_row = normalized.pop("header_row", None)

    if legacy_header_row is not None and metadata.get("header_row") is None:
        try:
            metadata["header_row"] = int(legacy_header_row)
        except (TypeError, ValueError):
            pass

    normalized["metadata"] = metadata

    return normalized


def ai_introspection_error_detail(
    message: str,
    *,
    operation: str | None = None,
    error: str | None = None,
    retryable: bool | None = None,
) -> dict[str, Any]:
    return {
        "message": message,
        "operation": operation,
        "error": error,
        "retryable": retryable,
    }


def semantic_sync_error_detail(
    message: str,
    *,
    operation: str | None = None,
    error: str | None = None,
    retryable: bool | None = None,
) -> dict[str, Any]:
    return {
        "message": message,
        "operation": operation,
        "error": error,
        "retryable": retryable,
    }


async def semantic_connection_ids(db: aiosqlite.Connection) -> list[int]:
    rows = await fetch_all_dicts(
        db,
        """
        SELECT DISTINCT connection_id
        FROM semantic_tables
        ORDER BY connection_id
        """,
    )

    return [int(row["connection_id"]) for row in rows]


async def introspect_connection(connection_id: int) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        connection = await fetch_one_dict(
            db,
            """
            SELECT id, name, slug, plugin
            FROM connections
            WHERE id = ?
            """,
            (connection_id,),
        )

    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")

    schema_name = str(connection["slug"])
    connection_credentials = (
        await read_connection_credentials(schema_name)
        if str(connection["plugin"]) == "googlesheets"
        else None
    )

    try:
        live_schema = await get_schema_with_descriptions(
            schema_name,
            use_cache=False,
            refresh_steampipe_cache=True,
            connection_credentials=connection_credentials,
        )
    except Exception as exc:
        logger.exception(
            "Steampipe schema introspection failed connection_id=%s schema=%s",
            connection_id,
            schema_name,
        )
        raise HTTPException(
            status_code=500,
            detail=semantic_sync_error_detail(
                "Could not introspect Steampipe schema.",
                operation="steampipe_schema_introspection",
                error=f"{exc.__class__.__name__}: {exc}",
                retryable=False,
            ),
        ) from exc

    if not live_schema:
        raise HTTPException(
            status_code=404,
            detail=f"No tables found for schema '{schema_name}'",
        )

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await introspect_connection_semantics(
                db=db,
                connection={
                    "id": connection["id"],
                    "name": connection["name"],
                    "plugin": connection["plugin"],
                    "schema": schema_name,
                },
                live_schema=live_schema,
            )

            await discover_relationships(
                db,
                connection_ids=await semantic_connection_ids(db),
            )

            await write_connection_metadata_cache(
                connection_id=connection_id,
                slug=schema_name,
                plugin=str(connection["plugin"]),
                live_schema=live_schema,
            )

            relationship_row = await fetch_one_dict(
                db,
                """
                SELECT COUNT(*) AS count
                FROM semantic_relationships
                WHERE status = 'suggested'
                  AND (from_connection_id = ? OR to_connection_id = ?)
                """,
                (connection_id, connection_id),
            )
    except Exception as exc:
        logger.exception(
            "Semantic sync failed connection_id=%s schema=%s",
            connection_id,
            schema_name,
        )
        raise HTTPException(
            status_code=500,
            detail=semantic_sync_error_detail(
                "Could not sync tables.",
                operation="semantic_sync",
                error=f"{exc.__class__.__name__}: {exc}",
                retryable=False,
            ),
        ) from exc

    return {
        "ok": True,
        "connection_id": connection_id,
        "schema_name": schema_name,
        "tables_seen": len(live_schema),
        "metadata_cache_refreshed": True,
        "relationships_suggested": (
            int(relationship_row["count"]) if relationship_row else 0
        ),
    }


async def ai_introspect(body: AiIntrospectRequest) -> dict[str, Any]:
    if not body.approved:
        raise HTTPException(
            status_code=403,
            detail="AI introspection requires explicit frontend approval",
        )

    connection_ids = sorted(set(body.connection_ids))
    flows = list(dict.fromkeys(body.flows))
    semantic_table_ids = sorted(set(body.semantic_table_ids))
    llm_calls: list[dict[str, Any]] = []
    started_at = utc_now()
    started_perf = time.perf_counter()
    model_config: dict[str, Any] | None = None

    async with aiosqlite.connect(DB_PATH) as db:
        request_context = await ai_introspection_request_context(
            db,
            connection_ids=connection_ids,
            semantic_table_ids=semantic_table_ids,
            flows=flows,
            model_config_id=body.model_config_id,
        )
        run_id = await create_ai_introspection_run(
            db,
            model_config_id=body.model_config_id,
            connection_ids=connection_ids,
            semantic_table_ids=semantic_table_ids,
            flows=flows,
            request_context=request_context,
            started_at=started_at,
        )

    try:
        model_config = await get_model_config(
            body.model_config_id,
            include_secrets=True,
        )
    except ModelConfigError as exc:
        logger.warning(f"AI introspection model config load failed error={exc}")
        await fail_ai_introspection_run(
            run_id,
            request_context=request_context,
            model_config=model_config,
            started_at=started_at,
            started_perf=started_perf,
            llm_calls=llm_calls,
            error=str(exc),
        )
        raise HTTPException(
            status_code=400,
            detail=ai_introspection_error_detail(
                str(exc),
                error=f"{exc.__class__.__name__}: {exc}",
                retryable=False,
            ),
        ) from exc

    if not model_config:
        error = "Model config not found"

        await fail_ai_introspection_run(
            run_id,
            request_context=request_context,
            model_config=model_config,
            started_at=started_at,
            started_perf=started_perf,
            llm_calls=llm_calls,
            error=error,
        )
        raise HTTPException(status_code=404, detail=error)

    await update_ai_introspection_run_model(run_id, model_config)

    try:
        llm = AgentLLM(build_llm(model_config), diagnostics=llm_calls)
    except ModelConfigError as exc:
        logger.warning(f"AI introspection model build failed error={exc}")
        await fail_ai_introspection_run(
            run_id,
            request_context=request_context,
            model_config=model_config,
            started_at=started_at,
            started_perf=started_perf,
            llm_calls=llm_calls,
            error=str(exc),
        )
        raise HTTPException(
            status_code=400,
            detail=ai_introspection_error_detail(
                str(exc),
                error=f"{exc.__class__.__name__}: {exc}",
                retryable=False,
            ),
        ) from exc

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            result = await run_ai_semantic_introspection(
                db,
                connection_ids=connection_ids,
                semantic_table_ids=semantic_table_ids,
                flows=flows,
                llm=llm,
            )
        except ModelConfigError as exc:
            logger.warning(f"AI introspection model config failed error={exc}")
            await fail_ai_introspection_run(
                run_id,
                request_context=request_context,
                model_config=model_config,
                started_at=started_at,
                started_perf=started_perf,
                llm_calls=llm_calls,
                error=str(exc),
            )
            raise HTTPException(
                status_code=400,
                detail=ai_introspection_error_detail(
                    str(exc),
                    error=f"{exc.__class__.__name__}: {exc}",
                    retryable=False,
                ),
            ) from exc
        except AgentLLMError as exc:
            logger.warning(
                f"AI introspection LLM failed "
                f"operation={exc.operation} "
                f"retryable={exc.retryable} "
                f"error={exc.original_summary}"
            )
            await fail_ai_introspection_run(
                run_id,
                request_context=request_context,
                model_config=model_config,
                started_at=started_at,
                started_perf=started_perf,
                llm_calls=llm_calls,
                error=exc.original_summary,
            )
            raise HTTPException(
                status_code=422,
                detail=ai_introspection_error_detail(
                    exc.user_message,
                    operation=exc.operation,
                    error=exc.original_summary,
                    retryable=exc.retryable,
                ),
            ) from exc
        except ValidationError as exc:
            logger.warning(f"AI introspection validation failed error={exc}")
            await fail_ai_introspection_run(
                run_id,
                request_context=request_context,
                model_config=model_config,
                started_at=started_at,
                started_perf=started_perf,
                llm_calls=llm_calls,
                error=str(exc),
            )
            raise HTTPException(
                status_code=422,
                detail=ai_introspection_error_detail(
                    (
                        "AI returned malformed semantic suggestions. "
                        "No suggestions were saved; retry the AI pass."
                    ),
                    error=str(exc),
                    retryable=False,
                ),
            ) from exc
        except Exception as exc:
            logger.exception(f"AI introspection failed error={exc}")
            await fail_ai_introspection_run(
                run_id,
                request_context=request_context,
                model_config=model_config,
                started_at=started_at,
                started_perf=started_perf,
                llm_calls=llm_calls,
                error=f"{exc.__class__.__name__}: {exc}",
            )
            raise HTTPException(
                status_code=422,
                detail=ai_introspection_error_detail(
                    "AI introspection failed.",
                    error=f"{exc.__class__.__name__}: {exc}",
                    retryable=False,
                ),
            ) from exc

    diagnostics = ai_introspection_diagnostics(
        status="completed",
        request_context=request_context,
        model_config=model_config,
        started_at=started_at,
        started_perf=started_perf,
        llm_calls=llm_calls,
        result=result,
    )

    await finish_ai_introspection_run(
        run_id,
        status="completed",
        result=result,
        diagnostics=diagnostics,
    )

    run = await get_ai_introspection_run_by_id(run_id)

    return {
        "ok": True,
        "connection_ids": connection_ids,
        "semantic_table_ids": semantic_table_ids,
        "flows": flows,
        "run_id": run_id,
        "diagnostics": diagnostics,
        "run": run,
        **result,
    }


async def ai_introspection_request_context(
    db: aiosqlite.Connection,
    *,
    connection_ids: list[int],
    semantic_table_ids: list[int],
    flows: list[str],
    model_config_id: int,
) -> dict[str, Any]:
    placeholders = ",".join("?" for _ in connection_ids)
    connections = await fetch_all_dicts(
        db,
        f"""
        SELECT id, name, slug, plugin, status
        FROM connections
        WHERE id IN ({placeholders})
        ORDER BY id
        """,
        connection_ids,
    )

    table_where = [
        f"connection_id IN ({placeholders})",
        "hidden = 0",
        "status IN ('confirmed', 'published')",
    ]
    table_params: list[Any] = list(connection_ids)

    if semantic_table_ids:
        table_placeholders = ",".join("?" for _ in semantic_table_ids)
        table_where.append(f"id IN ({table_placeholders})")
        table_params.extend(semantic_table_ids)

    tables = await fetch_all_dicts(
        db,
        f"""
        SELECT id, connection_id, source_name, schema_name, table_name
        FROM semantic_tables
        WHERE {" AND ".join(table_where)}
        ORDER BY connection_id, table_name
        """,
        table_params,
    )
    table_ids = [int(table["id"]) for table in tables]
    column_count = 0

    if table_ids:
        table_placeholders = ",".join("?" for _ in table_ids)
        row = await fetch_one_dict(
            db,
            f"""
            SELECT COUNT(*) AS count
            FROM semantic_columns
            WHERE semantic_table_id IN ({table_placeholders})
              AND hidden = 0
              AND status IN ('confirmed', 'published')
            """,
            table_ids,
        )
        column_count = int(row["count"]) if row else 0

    return {
        "model_config_id": model_config_id,
        "connection_ids": connection_ids,
        "connections": connection_diagnostics(connections),
        "semantic_table_ids": semantic_table_ids,
        "flows": flows,
        "selected_connection_count": len(connections),
        "selected_table_count": len(tables),
        "selected_column_count": column_count,
        "selected_tables": [
            {
                "id": table["id"],
                "connection_id": table["connection_id"],
                "schema": table["schema_name"],
                "table": table["table_name"],
                "source": table["source_name"],
            }
            for table in tables
        ],
    }


async def create_ai_introspection_run(
    db: aiosqlite.Connection,
    *,
    model_config_id: int,
    connection_ids: list[int],
    semantic_table_ids: list[int],
    flows: list[str],
    request_context: dict[str, Any],
    started_at: str,
) -> int:
    diagnostics = {
        "status": "running",
        "request": request_context,
        "timing": {"started_at": started_at},
        "llm_calls": [],
        "token_usage": {"calls": 0, "calls_with_usage": 0},
    }
    cursor = await db.execute(
        """
        INSERT INTO semantic_ai_runs (
            status,
            model_config_id,
            connection_ids_json,
            semantic_table_ids_json,
            flows_json,
            diagnostics_json,
            started_at
        )
        VALUES ('running', ?, ?, ?, ?, ?, ?)
        """,
        (
            model_config_id,
            json.dumps(connection_ids),
            json.dumps(semantic_table_ids),
            json.dumps(flows),
            json.dumps(jsonable(diagnostics), default=str),
            started_at,
        ),
    )

    await db.commit()
    return int(cursor.lastrowid)


async def update_ai_introspection_run_model(
    run_id: int,
    model_config: dict[str, Any],
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE semantic_ai_runs
            SET model_snapshot_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                json.dumps(
                    jsonable(model_diagnostics(model_config)),
                    default=str,
                ),
                run_id,
            ),
        )
        await db.commit()


async def finish_ai_introspection_run(
    run_id: int,
    *,
    status: str,
    result: dict[str, Any] | None,
    diagnostics: dict[str, Any],
    error: str | None = None,
) -> None:
    timing = diagnostics.get("timing") if isinstance(diagnostics, dict) else {}

    if not isinstance(timing, dict):
        timing = {}

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE semantic_ai_runs
            SET status = ?,
                result_json = ?,
                diagnostics_json = ?,
                error = ?,
                finished_at = ?,
                duration_ms = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                status,
                json.dumps(jsonable(result), default=str) if result else None,
                json.dumps(jsonable(diagnostics), default=str),
                error,
                timing.get("finished_at"),
                timing.get("duration_ms"),
                run_id,
            ),
        )
        await db.commit()


async def fail_ai_introspection_run(
    run_id: int,
    *,
    request_context: dict[str, Any],
    model_config: dict[str, Any] | None,
    started_at: str,
    started_perf: float,
    llm_calls: list[dict[str, Any]],
    error: str,
) -> None:
    diagnostics = ai_introspection_diagnostics(
        status="failed",
        request_context=request_context,
        model_config=model_config,
        started_at=started_at,
        started_perf=started_perf,
        llm_calls=llm_calls,
        error=error,
    )

    await finish_ai_introspection_run(
        run_id,
        status="failed",
        result=None,
        diagnostics=diagnostics,
        error=error,
    )


def ai_introspection_diagnostics(
    *,
    status: str,
    request_context: dict[str, Any],
    model_config: dict[str, Any] | None,
    started_at: str,
    started_perf: float,
    llm_calls: list[dict[str, Any]],
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    request = dict(request_context)
    request["model"] = model_diagnostics(model_config) if model_config else None

    return {
        "status": status,
        "request": request,
        "timing": {
            "started_at": started_at,
            "finished_at": utc_now(),
            "duration_ms": round((time.perf_counter() - started_perf) * 1000, 2),
        },
        "llm_calls": llm_calls,
        "token_usage": token_usage_summary(llm_calls),
        "result": ai_introspection_result_summary(result),
        "error": error,
    }


def ai_introspection_result_summary(
    result: dict[str, Any] | None,
) -> dict[str, Any]:
    if not result:
        return {}

    keys = [
        "relationship_candidates_returned",
        "relationship_candidates_suggested",
        "relationship_candidates_existing",
        "relationship_candidates_with_notes",
        "relationship_candidates_skipped",
        "relationship_candidates_pruned",
        "metric_candidates_returned",
        "metric_candidates_suggested",
        "metric_candidates_existing",
        "metric_candidates_skipped",
    ]
    summary = {key: result.get(key) for key in keys if key in result}

    for key in ("warnings", "skipped", "metric_skipped"):
        value = result.get(key)

        if isinstance(value, list):
            summary[f"{key}_count"] = len(value)

    return summary


async def list_ai_introspection_runs(limit: int = 20) -> dict[str, Any]:
    safe_limit = min(max(limit, 1), 50)

    async with aiosqlite.connect(DB_PATH) as db:
        rows = await fetch_all_dicts(
            db,
            """
            SELECT *
            FROM semantic_ai_runs
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )

    return {
        "runs": [semantic_ai_run_payload(row, include_details=False) for row in rows]
    }


async def get_ai_introspection_run_by_id(run_id: int) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        row = await fetch_one_dict(
            db,
            """
            SELECT *
            FROM semantic_ai_runs
            WHERE id = ?
            """,
            (run_id,),
        )

    if not row:
        raise HTTPException(status_code=404, detail="AI introspection run not found")

    return semantic_ai_run_payload(row, include_details=True)


def semantic_ai_run_payload(
    row: dict[str, Any],
    *,
    include_details: bool,
) -> dict[str, Any]:
    diagnostics = decode_json_value(row.get("diagnostics_json"), {})

    if not isinstance(diagnostics, dict):
        diagnostics = {}

    result = decode_json_value(row.get("result_json"), None)
    model_snapshot = decode_json_value(row.get("model_snapshot_json"), {})
    request = diagnostics.get("request") if isinstance(diagnostics, dict) else None
    token_usage = (
        diagnostics.get("token_usage") if isinstance(diagnostics, dict) else None
    )
    payload = {
        "id": row["id"],
        "status": row["status"],
        "model_config_id": row["model_config_id"],
        "model_snapshot": model_snapshot if isinstance(model_snapshot, dict) else {},
        "connection_ids": decode_json_value(row.get("connection_ids_json"), []),
        "semantic_table_ids": decode_json_value(
            row.get("semantic_table_ids_json"),
            [],
        ),
        "flows": decode_json_value(row.get("flows_json"), []),
        "result": result if isinstance(result, dict) else None,
        "request": request if isinstance(request, dict) else None,
        "token_usage": token_usage if isinstance(token_usage, dict) else None,
        "error": row["error"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "duration_ms": row["duration_ms"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

    if include_details:
        payload["diagnostics"] = diagnostics

    return payload


def decode_json_value(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback

    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


async def get_connection_semantics(connection_id: int) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        tables = await fetch_all_dicts(
            db,
            """
            SELECT *
            FROM semantic_tables
            WHERE connection_id = ?
            ORDER BY table_name
            """,
            (connection_id,),
        )
        tables = [normalize_semantic_table(table) for table in tables]
        table_ids = [table["id"] for table in tables]

        if not table_ids:
            return {
                "connection_id": connection_id,
                "tables": [],
                "relationships": [],
                "metrics": [],
            }

        placeholders = ",".join("?" for _ in table_ids)
        columns = await fetch_all_dicts(
            db,
            f"""
            SELECT *
            FROM semantic_columns
            WHERE semantic_table_id IN ({placeholders})
            ORDER BY semantic_table_id, column_name
            """,
            table_ids,
        )
        relationships = await fetch_all_dicts(
            db,
            """
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
            WHERE r.from_connection_id = ? OR r.to_connection_id = ?
            ORDER BY r.status, r.confidence DESC
            """,
            (connection_id, connection_id),
        )
        metrics = await fetch_all_dicts(
            db,
            """
            SELECT *
            FROM semantic_metrics
            WHERE connection_id = ?
            ORDER BY name
            """,
            (connection_id,),
        )

    columns_by_table: dict[int, list[dict[str, Any]]] = {}

    for column in columns:
        columns_by_table.setdefault(column["semantic_table_id"], []).append(column)

    for table in tables:
        table["columns"] = columns_by_table.get(table["id"], [])

    return {
        "connection_id": connection_id,
        "tables": tables,
        "relationships": relationships,
        "metrics": metrics,
    }


async def list_semantic_objects(
    kind: str,
    connection_ids: str | None = None,
    semantic_filter: str = "all",
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    parsed_kind = parse_semantic_object_kind(kind)
    parsed_filter = parse_semantic_object_filter(semantic_filter)
    parsed_connection_ids = parse_optional_connection_ids(connection_ids)

    if parsed_kind == "tables":
        return await list_semantic_table_objects(
            parsed_connection_ids,
            parsed_filter,
            query,
            limit,
            offset,
        )

    if parsed_kind == "columns":
        return await list_semantic_column_objects(
            parsed_connection_ids,
            parsed_filter,
            query,
            limit,
            offset,
        )

    if parsed_kind == "metrics":
        return await list_semantic_metric_objects(
            parsed_connection_ids,
            parsed_filter,
            query,
            limit,
            offset,
        )

    return await list_semantic_relationship_objects(
        parsed_connection_ids,
        parsed_filter,
        query,
        limit,
        offset,
    )


async def list_semantic_table_objects(
    connection_ids: list[int],
    semantic_filter: str,
    query: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    from_sql = """
        FROM semantic_tables t
        JOIN connections cn ON cn.id = t.connection_id
    """
    status_expr = "t.status"
    hidden_expr = "(COALESCE(t.hidden, 0) != 0 OR t.status = 'hidden')"
    conditions: list[str] = []
    params: list[Any] = []

    add_connection_filter(conditions, params, connection_ids, "t.connection_id")
    add_search_condition(
        conditions,
        params,
        query,
        [
            "t.table_name",
            "t.label",
            "t.description",
            "cn.name",
            "cn.plugin",
        ],
    )

    async with aiosqlite.connect(DB_PATH) as db:
        counts = await semantic_counts(
            db,
            from_sql,
            conditions,
            params,
            status_expr,
            hidden_expr,
        )
        item_conditions = [*conditions]
        status_condition = semantic_status_filter_condition(
            semantic_filter,
            status_expr,
            hidden_expr,
        )

        if status_condition:
            item_conditions.append(status_condition)

        rows = await fetch_all_dicts(
            db,
            f"""
            SELECT t.*
            {from_sql}
            {where_clause(item_conditions)}
            ORDER BY t.status, t.table_name, t.id
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        )

    items = []

    for row in rows:
        table = normalize_semantic_table(row)
        table["columns"] = []
        items.append(table)

    return semantic_page_payload(
        "tables",
        items,
        counts,
        semantic_filter,
        limit,
        offset,
    )


async def list_semantic_column_objects(
    connection_ids: list[int],
    semantic_filter: str,
    query: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    from_sql = """
        FROM semantic_columns c
        JOIN semantic_tables t ON t.id = c.semantic_table_id
        JOIN connections cn ON cn.id = t.connection_id
    """
    status_expr = "c.status"
    hidden_expr = "(COALESCE(c.hidden, 0) != 0 OR c.status = 'hidden')"
    conditions: list[str] = []
    params: list[Any] = []

    add_connection_filter(conditions, params, connection_ids, "t.connection_id")
    add_search_condition(
        conditions,
        params,
        query,
        [
            "t.table_name",
            "c.column_name",
            "c.label",
            "c.description",
            "cn.name",
            "cn.plugin",
        ],
    )

    async with aiosqlite.connect(DB_PATH) as db:
        counts = await semantic_counts(
            db,
            from_sql,
            conditions,
            params,
            status_expr,
            hidden_expr,
        )
        item_conditions = [*conditions]
        status_condition = semantic_status_filter_condition(
            semantic_filter,
            status_expr,
            hidden_expr,
        )

        if status_condition:
            item_conditions.append(status_condition)

        rows = await fetch_all_dicts(
            db,
            f"""
            SELECT c.*, {prefixed_table_select("t")}
            {from_sql}
            {where_clause(item_conditions)}
            ORDER BY c.status, t.table_name, c.column_name, c.id
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        )

    return semantic_page_payload(
        "columns",
        [semantic_columns_payload(row) for row in rows],
        counts,
        semantic_filter,
        limit,
        offset,
    )


async def list_semantic_metric_objects(
    connection_ids: list[int],
    semantic_filter: str,
    query: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    from_sql = """
        FROM semantic_metrics m
        JOIN semantic_tables t ON t.id = m.semantic_table_id
        JOIN connections cn ON cn.id = m.connection_id
    """
    status_expr = "m.status"
    hidden_expr = "(m.status = 'hidden')"
    conditions: list[str] = []
    params: list[Any] = []

    add_connection_filter(conditions, params, connection_ids, "m.connection_id")
    add_search_condition(
        conditions,
        params,
        query,
        [
            "m.name",
            "m.label",
            "m.expression",
            "t.table_name",
            "cn.name",
            "cn.plugin",
        ],
    )

    async with aiosqlite.connect(DB_PATH) as db:
        counts = await semantic_counts(
            db,
            from_sql,
            conditions,
            params,
            status_expr,
            hidden_expr,
        )
        item_conditions = [*conditions]
        status_condition = semantic_status_filter_condition(
            semantic_filter,
            status_expr,
            hidden_expr,
        )
        if status_condition:
            item_conditions.append(status_condition)

        rows = await fetch_all_dicts(
            db,
            f"""
            SELECT m.*, {prefixed_table_select("t")}
            {from_sql}
            {where_clause(item_conditions)}
            ORDER BY m.status, m.name, m.id
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        )

    return semantic_page_payload(
        "metrics",
        [semantic_metrics_payload(row) for row in rows],
        counts,
        semantic_filter,
        limit,
        offset,
    )


async def list_semantic_relationship_objects(
    connection_ids: list[int],
    semantic_filter: str,
    query: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    from_sql = """
        FROM semantic_relationships r
        JOIN semantic_tables ft ON ft.id = r.from_table_id
        JOIN semantic_columns fc ON fc.id = r.from_column_id
        JOIN semantic_tables tt ON tt.id = r.to_table_id
        JOIN semantic_columns tc ON tc.id = r.to_column_id
    """
    status_expr = "r.status"
    hidden_expr = "(r.status = 'hidden')"
    conditions: list[str] = []
    params: list[Any] = []

    add_relationship_connection_filter(conditions, params, connection_ids)
    add_search_condition(
        conditions,
        params,
        query,
        [
            "ft.source_name",
            "tt.source_name",
            "ft.table_name",
            "tt.table_name",
            "fc.column_name",
            "tc.column_name",
            "r.relationship_type",
            "r.match_type",
            "r.validation_note",
            "r.evidence",
            "r.rationale",
        ],
    )

    async with aiosqlite.connect(DB_PATH) as db:
        counts = await semantic_counts(
            db,
            from_sql,
            conditions,
            params,
            status_expr,
            hidden_expr,
        )
        item_conditions = [*conditions]
        status_condition = semantic_status_filter_condition(
            semantic_filter,
            status_expr,
            hidden_expr,
        )
        if status_condition:
            item_conditions.append(status_condition)

        rows = await fetch_all_dicts(
            db,
            f"""
            SELECT
                r.*,
                ft.source_name AS from_source,
                ft.schema_name AS from_schema,
                ft.table_name AS from_table,
                fc.column_name AS from_column,
                tt.source_name AS to_source,
                tt.schema_name AS to_schema,
                tt.table_name AS to_table,
                tc.column_name AS to_column
            {from_sql}
            {where_clause(item_conditions)}
            ORDER BY r.status, r.confidence DESC, r.id
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        )

    return semantic_page_payload(
        "relationships",
        rows,
        counts,
        semantic_filter,
        limit,
        offset,
    )


async def list_relationships(
    connection_ids: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    params: list[Any] = []
    where: list[str] = []

    if status:
        where.append("r.status = ?")
        params.append(status)

    if connection_ids:
        ids = parse_connection_ids(connection_ids)
        placeholders = ",".join("?" for _ in ids)

        where.append(f"""
            (
                r.from_connection_id IN ({placeholders})
                OR r.to_connection_id IN ({placeholders})
            )
            """)
        params.extend(ids)
        params.extend(ids)

    sql = f"""
        SELECT
            r.*,
            ft.source_name AS from_source,
            ft.schema_name AS from_schema,
            ft.table_name AS from_table,
            fc.column_name AS from_column,
            tt.source_name AS to_source,
            tt.schema_name AS to_schema,
            tt.table_name AS to_table,
            tc.column_name AS to_column
        FROM semantic_relationships r
        JOIN semantic_tables ft ON ft.id = r.from_table_id
        JOIN semantic_columns fc ON fc.id = r.from_column_id
        JOIN semantic_tables tt ON tt.id = r.to_table_id
        JOIN semantic_columns tc ON tc.id = r.to_column_id
        {"WHERE " + " AND ".join(where) if where else ""}
        ORDER BY r.status, r.confidence DESC
    """

    async with aiosqlite.connect(DB_PATH) as db:
        rows = await fetch_all_dicts(db, sql, params)

    return {"relationships": rows}


async def create_relationship(body: CreateRelationshipRequest) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        from_column = await fetch_one_dict(
            db,
            """
            SELECT c.id
            FROM semantic_columns c
            JOIN semantic_tables t ON t.id = c.semantic_table_id
            WHERE c.id = ?
              AND t.id = ?
              AND t.connection_id = ?
            """,
            (body.from_column_id, body.from_table_id, body.from_connection_id),
        )
        to_column = await fetch_one_dict(
            db,
            """
            SELECT c.id
            FROM semantic_columns c
            JOIN semantic_tables t ON t.id = c.semantic_table_id
            WHERE c.id = ?
              AND t.id = ?
              AND t.connection_id = ?
            """,
            (body.to_column_id, body.to_table_id, body.to_connection_id),
        )

        if not from_column or not to_column:
            raise HTTPException(
                status_code=400,
                detail="Relationship columns must belong to their selected tables",
            )

        try:
            cursor = await db.execute(
                """
                INSERT INTO semantic_relationships (
                    from_connection_id,
                    to_connection_id,
                    from_table_id,
                    from_column_id,
                    to_table_id,
                    to_column_id,
                    relationship_type,
                    match_type,
                    confidence,
                    status,
                    source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'user')
                """,
                (
                    body.from_connection_id,
                    body.to_connection_id,
                    body.from_table_id,
                    body.from_column_id,
                    body.to_table_id,
                    body.to_column_id,
                    body.relationship_type,
                    body.match_type,
                    body.confidence,
                    body.status,
                ),
            )
        except aiosqlite.IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail="That relationship already exists",
            ) from exc

        await db.commit()

    return {
        "ok": True,
        "relationship_id": cursor.lastrowid,
    }


async def confirm_relationship(relationship_id: int) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE semantic_relationships
            SET status = 'confirmed',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (relationship_id,),
        )

        await db.commit()

    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Relationship not found")

    return {
        "ok": True,
        "relationship_id": relationship_id,
        "status": "confirmed",
    }


async def ignore_relationship(relationship_id: int) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE semantic_relationships
            SET status = 'ignored',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (relationship_id,),
        )

        await db.commit()

    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Relationship not found")

    return {
        "ok": True,
        "relationship_id": relationship_id,
        "status": "ignored",
    }


async def update_relationship(
    relationship_id: int,
    body: UpdateRelationshipRequest,
) -> dict[str, Any]:
    allowed = {
        "relationship_type",
        "match_type",
        "confidence",
        "status",
    }
    set_sql, values = update_fields(body, allowed)

    if not set_sql:
        return {"ok": True, "relationship_id": relationship_id, "updated": False}

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            f"""
            UPDATE semantic_relationships
            SET {set_sql}
            WHERE id = ?
            """,
            (*values, relationship_id),
        )

        await db.commit()

    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Relationship not found")

    return {
        "ok": True,
        "relationship_id": relationship_id,
        "updated": True,
    }


async def delete_relationship(relationship_id: int) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            DELETE FROM semantic_relationships
            WHERE id = ?
            """,
            (relationship_id,),
        )

        await db.commit()

    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Relationship not found")

    return {
        "ok": True,
        "relationship_id": relationship_id,
        "deleted": True,
    }


async def update_semantic_table(
    table_id: int,
    body: UpdateSemanticTableRequest,
) -> dict[str, Any]:
    allowed = {
        "label",
        "description",
        "table_type",
        "grain",
        "primary_time_column",
        "metadata",
        "hidden",
        "status",
    }
    set_sql, values = update_fields(body, allowed)

    if not set_sql:
        return {"ok": True, "table_id": table_id, "updated": False}

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            f"""
            UPDATE semantic_tables
            SET {set_sql}
            WHERE id = ?
            """,
            (*values, table_id),
        )

        await db.commit()

    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Semantic table not found")

    return {"ok": True, "table_id": table_id, "updated": True}


async def delete_semantic_table(table_id: int) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        table = await fetch_one_dict(
            db,
            """
            SELECT id
            FROM semantic_tables
            WHERE id = ?
            """,
            (table_id,),
        )

        if not table:
            raise HTTPException(status_code=404, detail="Semantic table not found")

        await db.execute(
            """
            DELETE FROM semantic_relationships
            WHERE from_table_id = ? OR to_table_id = ?
            """,
            (table_id, table_id),
        )
        await db.execute(
            """
            DELETE FROM semantic_metrics
            WHERE semantic_table_id = ?
            """,
            (table_id,),
        )
        await db.execute(
            """
            DELETE FROM semantic_columns
            WHERE semantic_table_id = ?
            """,
            (table_id,),
        )

        cursor = await db.execute(
            """
            DELETE FROM semantic_tables
            WHERE id = ?
            """,
            (table_id,),
        )

        await db.commit()

    return {
        "ok": True,
        "table_id": table_id,
        "deleted": cursor.rowcount > 0,
    }


async def update_semantic_column(
    column_id: int,
    body: UpdateSemanticColumnRequest,
) -> dict[str, Any]:
    allowed = {
        "label",
        "description",
        "semantic_type",
        "expression",
        "unit",
        "is_dimension",
        "is_measure",
        "is_time",
        "is_id",
        "is_foreign_key",
        "hidden",
        "status",
    }
    set_sql, values = update_fields(body, allowed)

    if not set_sql:
        return {"ok": True, "column_id": column_id, "updated": False}

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            f"""
            UPDATE semantic_columns
            SET {set_sql}
            WHERE id = ?
            """,
            (*values, column_id),
        )

        await db.commit()

    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Semantic column not found")

    return {"ok": True, "column_id": column_id, "updated": True}


async def delete_semantic_column(column_id: int) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        column = await fetch_one_dict(
            db,
            """
            SELECT id
            FROM semantic_columns
            WHERE id = ?
            """,
            (column_id,),
        )

        if not column:
            raise HTTPException(status_code=404, detail="Semantic column not found")

        await db.execute(
            """
            DELETE FROM semantic_relationships
            WHERE from_column_id = ? OR to_column_id = ?
            """,
            (column_id, column_id),
        )

        cursor = await db.execute(
            """
            DELETE FROM semantic_columns
            WHERE id = ?
            """,
            (column_id,),
        )

        await db.commit()

    return {
        "ok": True,
        "column_id": column_id,
        "deleted": cursor.rowcount > 0,
    }


async def create_metric(body: CreateMetricRequest) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        table = await fetch_one_dict(
            db,
            """
            SELECT id
            FROM semantic_tables
            WHERE id = ?
              AND connection_id = ?
            """,
            (body.semantic_table_id, body.connection_id),
        )

        if not table:
            raise HTTPException(
                status_code=400,
                detail="semantic_table_id does not belong to connection_id",
            )

        try:
            cursor = await db.execute(
                """
                INSERT INTO semantic_metrics (
                    connection_id,
                    semantic_table_id,
                    name,
                    label,
                    expression,
                    filters_json,
                    time_column,
                    unit,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    body.connection_id,
                    body.semantic_table_id,
                    body.name,
                    body.label,
                    body.expression,
                    json.dumps(body.filters),
                    body.time_column,
                    body.unit,
                    body.status,
                ),
            )
        except aiosqlite.IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail="A metric with that name already exists for this connection",
            ) from exc

        await db.commit()

    return {
        "ok": True,
        "metric_id": cursor.lastrowid,
    }


async def update_metric(
    metric_id: int,
    body: UpdateMetricRequest,
) -> dict[str, Any]:
    allowed = {
        "label",
        "expression",
        "filters",
        "time_column",
        "unit",
        "status",
    }

    set_sql, values = update_fields(body, allowed)

    if not set_sql:
        return {"ok": True, "metric_id": metric_id, "updated": False}

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            f"""
            UPDATE semantic_metrics
            SET {set_sql}
            WHERE id = ?
            """,
            (*values, metric_id),
        )

        await db.commit()

    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Metric not found")

    return {
        "ok": True,
        "metric_id": metric_id,
        "updated": True,
    }


async def delete_metric(metric_id: int) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            DELETE FROM semantic_metrics
            WHERE id = ?
            """,
            (metric_id,),
        )

        await db.commit()

    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Metric not found")

    return {
        "ok": True,
        "metric_id": metric_id,
        "deleted": True,
    }


async def get_semantic_contract(
    connection_ids: str,
) -> dict[str, Any]:
    selected_connection_ids = parse_connection_ids(connection_ids)

    async with aiosqlite.connect(DB_PATH) as db:
        return await build_semantic_contract(
            db,
            selected_connection_ids=selected_connection_ids,
        )


async def delete_connection_semantic_layer(connection_id: int) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        await delete_connection_semantics(
            db=db,
            connection_id=connection_id,
        )

    return {
        "ok": True,
        "connection_id": connection_id,
        "deleted": True,
    }
