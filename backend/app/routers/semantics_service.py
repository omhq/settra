import json
import logging

from typing import Any

import aiosqlite

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from app.agent.llm import AgentLLM, AgentLLMError
from app.agent.metadata import get_schema_with_descriptions
from app.db import DB_PATH
from app.model_configs import ModelConfigError, build_llm, get_model_config
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

logger = logging.getLogger(__name__)


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

    try:
        live_schema = await get_schema_with_descriptions(schema_name)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not introspect Steampipe schema: {exc}",
        ) from exc

    if not live_schema:
        raise HTTPException(
            status_code=404,
            detail=f"No tables found for schema '{schema_name}'",
        )

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

    return {
        "ok": True,
        "connection_id": connection_id,
        "schema_name": schema_name,
        "tables_seen": len(live_schema),
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

    try:
        model_config = await get_model_config(
            body.model_config_id,
            include_secrets=True,
        )
    except ModelConfigError as exc:
        logger.warning(f"AI introspection model config load failed error={exc}")
        raise HTTPException(
            status_code=400,
            detail=ai_introspection_error_detail(
                str(exc),
                error=f"{exc.__class__.__name__}: {exc}",
                retryable=False,
            ),
        ) from exc

    if not model_config:
        raise HTTPException(status_code=404, detail="Model config not found")

    try:
        llm = AgentLLM(build_llm(model_config))
    except ModelConfigError as exc:
        logger.warning(f"AI introspection model build failed error={exc}")
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
                semantic_table_ids=body.semantic_table_ids,
                flows=flows,
                llm=llm,
            )
        except ModelConfigError as exc:
            logger.warning(f"AI introspection model config failed error={exc}")
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
            raise HTTPException(
                status_code=422,
                detail=ai_introspection_error_detail(
                    "AI introspection failed.",
                    error=f"{exc.__class__.__name__}: {exc}",
                    retryable=False,
                ),
            ) from exc

    return {
        "ok": True,
        "connection_ids": connection_ids,
        "semantic_table_ids": sorted(set(body.semantic_table_ids)),
        "flows": flows,
        **result,
    }


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
