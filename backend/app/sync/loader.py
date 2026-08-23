from __future__ import annotations

import asyncio
import fnmatch
import logging
import os
import re
import unicodedata

from datetime import datetime, timezone
from typing import Any

import aiofiles
import yaml

from fastapi import HTTPException

from app.db import db_connection
from app.routers.constants import (
    DLT_PIPELINES_DIR,
    GOOGLE_SHEETS_KEY,
    POSTGRES_DATABASE,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
    postgres_dsn,
)
from app.sync.config import config_path, read_sync_config, table_rule
from app.sync.secrets import load_google_oauth_secret

logger = logging.getLogger(__name__)

GOOGLE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
_SYNC_LOCKS: dict[int, asyncio.Lock] = {}


async def run_connection_sync(
    connection_id: int,
    *,
    trigger: str = "manual",
) -> dict[str, Any]:
    lock = _SYNC_LOCKS.setdefault(connection_id, asyncio.Lock())

    if lock.locked():
        raise HTTPException(409, "A sync is already running for this connection")

    async with lock:
        connection = await _connection(connection_id)
        config = await read_sync_config(connection["slug"])

        if not config:
            raise HTTPException(409, "Connection sync configuration is missing")

        secret = await load_google_oauth_secret()

        if GOOGLE_FILE_SCOPE not in set(secret.get("scopes") or []):
            raise HTTPException(
                409,
                "Reconnect Google to grant file-specific spreadsheet access",
            )

        run_id = await _start_run(connection_id, trigger)
        result: dict[str, Any] | None = None

        try:
            result = await asyncio.to_thread(
                _run_dlt_sync,
                connection,
                config,
                secret,
            )
            await _refresh_models_and_metadata(connection)
            await _finish_run(run_id, connection_id, result=result)
            return {"ok": True, "run_id": run_id, **result}
        except HTTPException as exc:
            await _finish_run(
                run_id,
                connection_id,
                result=result,
                error=str(exc.detail),
            )
            raise
        except Exception as exc:
            logger.exception(
                "Google Sheets sync failed connection_id=%s trigger=%s",
                connection_id,
                trigger,
            )
            message = f"{exc.__class__.__name__}: {exc}"
            await _finish_run(
                run_id,
                connection_id,
                result=result,
                error=message,
            )
            raise HTTPException(502, f"Sheet sync failed: {message}") from exc


def _run_dlt_sync(
    connection: dict[str, Any],
    config: dict[str, Any],
    secret: dict[str, Any],
) -> dict[str, Any]:
    # Imports stay local so metadata-only commands do not need the loader runtime.
    import dlt

    from dlt.sources.credentials import GcpOAuthCredentials

    os.environ.setdefault("RUNTIME__DLTHUB_TELEMETRY", "false")
    DLT_PIPELINES_DIR.mkdir(parents=True, exist_ok=True)

    oauth = GcpOAuthCredentials(
        client_id=_google_client_id(),
        client_secret=_google_client_secret(),
        refresh_token=str(secret["refresh_token"]),
        project_id=os.getenv("GOOGLE_CLOUD_PROJECT") or None,
        scopes=[GOOGLE_FILE_SCOPE],
    )
    try:
        extracted = _extract_spreadsheet(config, oauth)
    except Exception as exc:
        from googleapiclient.errors import HttpError

        if isinstance(exc, HttpError) and getattr(exc.resp, "status", None) == 403:
            raise HTTPException(
                403,
                "The selected spreadsheet is not authorized for Settra. "
                "Choose it again through Google Picker.",
            ) from exc

        raise

    if not extracted:
        raise ValueError("No selected tabs contain a usable header row")

    resources = []
    loaded_tables: list[dict[str, Any]] = []

    for table in extracted:
        column_hints = {
            column["name"]: {
                **(
                    {"data_type": column.get("data_type") or "text"}
                    if not table["rows"] or column.get("data_type")
                    else {}
                ),
                "nullable": bool(column.get("nullable", True)),
            }
            for column in table["columns"]
        }
        resource = dlt.resource(
            table["rows"],
            name=table["table_name"],
            write_disposition="replace",
            columns=column_hints,
            schema_contract=config["load"].get("schema_contract"),
        )
        resources.append(resource)
        loaded_tables.append(
            {key: value for key, value in table.items() if key != "rows"}
            | {"row_count": len(table["rows"])}
        )

    @dlt.source(name=f"settra_{connection['slug']}_google_sheets")
    def source():
        return resources

    destination = dlt.destinations.postgres(
        credentials=postgres_dsn(),
        replace_strategy="insert-from-staging",
    )
    pipeline = dlt.pipeline(
        pipeline_name=f"settra_{connection['slug']}",
        destination=destination,
        dataset_name=connection["slug"],
        pipelines_dir=str(DLT_PIPELINES_DIR),
    )
    load_info = pipeline.run(source())
    load_ids = list(getattr(load_info, "loads_ids", []) or [])

    _finalize_postgres_schema(
        schema=connection["slug"],
        tables=loaded_tables,
        config=config,
    )
    manifest = _postgres_manifest(
        connection=connection,
        loaded_tables=loaded_tables,
        load_ids=load_ids,
    )
    _write_manifest(connection["slug"], manifest)

    return {
        "connection_id": connection["id"],
        "schema": connection["slug"],
        "tables": manifest["tables"],
        "table_count": len(manifest["tables"]),
        "row_count": sum(item["row_count"] for item in loaded_tables),
        "load_ids": load_ids,
        "completed_at": manifest["generated_at"],
    }


def _extract_spreadsheet(config: dict[str, Any], oauth: Any) -> list[dict[str, Any]]:
    from googleapiclient.discovery import build

    native_credentials = oauth.to_native_credentials()
    service = build(
        "sheets",
        "v4",
        credentials=native_credentials,
        cache_discovery=False,
    )
    source = config["source"]
    spreadsheet_id = source["spreadsheet_id"]
    workbook = (
        service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields="properties(title,locale,timeZone),sheets(properties(sheetId,title,index,sheetType))",
        )
        .execute()
    )
    patterns = source.get("sheets") or ["*"]
    selected = [
        item["properties"]["title"]
        for item in workbook.get("sheets", [])
        if item.get("properties", {}).get("sheetType", "GRID") == "GRID"
        and _matches_any(item["properties"]["title"], patterns)
    ]

    if not selected:
        raise ValueError("The configured sheet patterns matched no spreadsheet tabs")

    extracted: list[dict[str, Any]] = []
    used_tables: set[str] = set()

    for sheet_title in selected:
        rule = table_rule(config, sheet_title)

        if rule.get("enabled") is False:
            continue

        quoted_range = "'" + sheet_title.replace("'", "''") + "'"
        response = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=quoted_range,
                majorDimension="ROWS",
                valueRenderOption="UNFORMATTED_VALUE",
                dateTimeRenderOption="FORMATTED_STRING",
            )
            .execute()
        )
        values = response.get("values") or []

        if not values:
            continue

        raw_headers = values[0]
        headers = _headers(raw_headers)

        if not headers:
            continue

        table_name = _unique_name(
            _identifier(str(rule.get("table_name") or sheet_title), "sheet"),
            used_tables,
        )
        used_tables.add(table_name)
        column_rules = (
            rule.get("columns") if isinstance(rule.get("columns"), dict) else {}
        )
        used_columns: set[str] = set()
        columns: list[dict[str, Any]] = []

        for index, header in enumerate(headers):
            raw_rule = column_rules.get(header["source_name"], {})
            column_rule = raw_rule if isinstance(raw_rule, dict) else {}

            if column_rule.get("enabled") is False:
                continue

            name = _unique_name(
                _identifier(
                    str(column_rule.get("name") or header["source_name"]),
                    f"column_{index + 1}",
                ),
                used_columns,
            )
            used_columns.add(name)
            columns.append(
                {
                    "source_name": header["source_name"],
                    "source_index": header["source_index"],
                    "name": name,
                    "description": str(column_rule.get("description") or ""),
                    **(
                        {"data_type": str(column_rule["data_type"])}
                        if column_rule.get("data_type")
                        else {}
                    ),
                    "nullable": bool(column_rule.get("nullable", True)),
                }
            )

        if not columns:
            continue

        rows = []

        for raw_row in values[1:]:
            rows.append(
                {
                    column["name"]: (
                        raw_row[column["source_index"]]
                        if column["source_index"] < len(raw_row)
                        else None
                    )
                    for column in columns
                }
            )

        extracted.append(
            {
                "sheet_name": sheet_title,
                "table_name": table_name,
                "description": str(rule.get("description") or ""),
                "columns": columns,
                "rows": rows,
            }
        )

    return extracted


def _headers(raw_headers: list[Any]) -> list[dict[str, Any]]:
    used: set[str] = set()
    headers = []

    for index, value in enumerate(raw_headers):
        source_name = str(value).strip()

        if not source_name:
            continue

        source_name = _unique_name(source_name, used)
        used.add(source_name)
        headers.append({"source_name": source_name, "source_index": index})

    return headers


def _identifier(value: str, fallback: str) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    )
    normalized = re.sub(r"[^a-z0-9]+", "_", ascii_value.lower()).strip("_")

    if not normalized:
        normalized = fallback

    if normalized[0].isdigit():
        normalized = f"col_{normalized}"

    return normalized[:63].rstrip("_")


def _unique_name(value: str, used: set[str]) -> str:
    candidate = value
    suffix = 2

    while candidate in used:
        ending = f"_{suffix}"
        candidate = f"{value[: 63 - len(ending)]}{ending}"
        suffix += 1

    return candidate


def _matches_any(title: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(title, pattern) for pattern in patterns)


def _finalize_postgres_schema(
    *,
    schema: str,
    tables: list[dict[str, Any]],
    config: dict[str, Any],
) -> None:
    import psycopg2

    from psycopg2 import sql

    connection = psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DATABASE,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
    )

    try:
        with connection.cursor() as cursor:
            previous_tables = _previous_manifest_table_names(schema)
            current_tables = {item["table_name"] for item in tables}

            for stale in sorted(previous_tables - current_tables):
                cursor.execute(
                    sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
                        sql.Identifier(schema),
                        sql.Identifier(stale),
                    )
                )

            for table in tables:
                if not table.get("rows") and not table.get("row_count"):
                    cursor.execute(
                        sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                            sql.Identifier(schema)
                        )
                    )
                    definitions = []

                    for column in table["columns"]:
                        definition = sql.SQL("{} {}").format(
                            sql.Identifier(column["name"]),
                            sql.SQL(_postgres_type(column.get("data_type") or "text")),
                        )

                        if not column.get("nullable", True):
                            definition += sql.SQL(" NOT NULL")

                        definitions.append(definition)

                    cursor.execute(
                        sql.SQL("CREATE TABLE IF NOT EXISTS {}.{} ({})").format(
                            sql.Identifier(schema),
                            sql.Identifier(table["table_name"]),
                            sql.SQL(", ").join(definitions),
                        )
                    )
                    cursor.execute(
                        sql.SQL("TRUNCATE TABLE {}.{}").format(
                            sql.Identifier(schema),
                            sql.Identifier(table["table_name"]),
                        )
                    )

                cursor.execute(
                    sql.SQL("COMMENT ON TABLE {}.{} IS %s").format(
                        sql.Identifier(schema),
                        sql.Identifier(table["table_name"]),
                    ),
                    (table.get("description") or None,),
                )

                for column in table["columns"]:
                    cursor.execute(
                        sql.SQL("COMMENT ON COLUMN {}.{}.{} IS %s").format(
                            sql.Identifier(schema),
                            sql.Identifier(table["table_name"]),
                            sql.Identifier(column["name"]),
                        ),
                        (column.get("description") or None,),
                    )

        connection.commit()
    finally:
        connection.close()


def _postgres_type(data_type: str) -> str:
    return {
        "text": "text",
        "bigint": "bigint",
        "double": "double precision",
        "bool": "boolean",
        "timestamp": "timestamp with time zone",
        "date": "date",
        "decimal": "numeric",
        "json": "jsonb",
    }[data_type]


def _postgres_manifest(
    *,
    connection: dict[str, Any],
    loaded_tables: list[dict[str, Any]],
    load_ids: list[str],
) -> dict[str, Any]:
    import psycopg2

    connection_pg = psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DATABASE,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
    )

    try:
        with connection_pg.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    c.table_name,
                    c.column_name,
                    c.data_type,
                    c.is_nullable,
                    c.ordinal_position,
                    pg_catalog.obj_description(
                        (quote_ident(c.table_schema) || '.' || quote_ident(c.table_name))::regclass,
                        'pg_class'
                    ) AS table_description,
                    pg_catalog.col_description(
                        (quote_ident(c.table_schema) || '.' || quote_ident(c.table_name))::regclass,
                        c.ordinal_position
                    ) AS column_description
                FROM information_schema.columns c
                WHERE c.table_schema = %s
                  AND c.table_name NOT LIKE '\\_dlt\\_%%' ESCAPE '\\'
                  AND c.column_name NOT LIKE '\\_dlt\\_%%' ESCAPE '\\'
                ORDER BY c.table_name, c.ordinal_position
                """,
                (connection["slug"],),
            )
            rows = cursor.fetchall()
    finally:
        connection_pg.close()

    source_by_table = {item["table_name"]: item for item in loaded_tables}
    tables: dict[str, dict[str, Any]] = {}

    for row in rows:
        table_name = row[0]
        source = source_by_table.get(table_name, {})
        table = tables.setdefault(
            table_name,
            {
                "name": table_name,
                "source_sheet": source.get("sheet_name", table_name),
                "description": row[5] or "",
                "row_count": source.get("row_count", 0),
                "columns": [],
            },
        )
        table["columns"].append(
            {
                "name": row[1],
                "type": row[2],
                "nullable": row[3] == "YES",
                "description": row[6] or "",
            }
        )

    return {
        "version": 1,
        "connection_id": connection["id"],
        "connection_name": connection["name"],
        "slug": connection["slug"],
        "plugin": GOOGLE_SHEETS_KEY,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "load_ids": load_ids,
        "tables": list(tables.values()),
    }


def _manifest_path(slug: str):
    return config_path(slug).with_suffix(".manifest.yaml")


def _write_manifest(slug: str, manifest: dict[str, Any]) -> None:
    path = _manifest_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".yaml.tmp")
    temp_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    temp_path.chmod(0o600)
    temp_path.replace(path)


def _previous_manifest_table_names(slug: str) -> set[str]:
    path = _manifest_path(slug)

    if not path.is_file():
        return set()

    try:
        manifest = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return set()

    tables = manifest.get("tables") if isinstance(manifest, dict) else []
    return {
        str(table.get("name"))
        for table in tables or []
        if isinstance(table, dict) and table.get("name")
    }


async def _connection(connection_id: int) -> dict[str, Any]:
    async with db_connection() as db:
        row = await db.fetchrow(
            """
            SELECT id, name, slug, plugin, status, created_at,
                   last_synced_at, last_sync_error
            FROM connections
            WHERE id = $1 AND plugin = $2
            """,
            connection_id,
            GOOGLE_SHEETS_KEY,
        )

    if not row:
        raise HTTPException(404, "Connection not found")

    return dict(row)


async def _start_run(connection_id: int, trigger: str) -> int:
    async with db_connection() as db, db.transaction():
        run_id = await db.fetchval(
            """
            INSERT INTO sync_runs (connection_id, trigger, status)
            VALUES ($1, $2, 'running')
            RETURNING id
            """,
            connection_id,
            trigger,
        )
        await db.execute(
            """
            UPDATE connections
            SET status = 'syncing', last_sync_started_at = now(),
                last_sync_error = NULL
            WHERE id = $1
            """,
            connection_id,
        )
        return int(run_id)


async def _finish_run(
    run_id: int,
    connection_id: int,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    result = result or {}
    async with db_connection() as db, db.transaction():
        await db.execute(
            """
            UPDATE sync_runs
            SET status = $1, finished_at = now(), table_count = $2,
                row_count = $3, load_ids = $4, error = $5
            WHERE id = $6
            """,
            "failed" if error else "success",
            result.get("table_count"),
            result.get("row_count"),
            ",".join(result.get("load_ids") or []),
            error,
            run_id,
        )
        await db.execute(
            """
            UPDATE connections
            SET status = $1,
                last_synced_at = CASE WHEN $2::text IS NULL THEN now() ELSE last_synced_at END,
                last_sync_error = $3
            WHERE id = $4
            """,
            "failed" if error else "active",
            error,
            error,
            connection_id,
        )


async def _refresh_models_and_metadata(connection: dict[str, Any]) -> None:
    from app.agent.metadata import get_schema_with_descriptions
    from app.cube.client import CubeAPIError, load_cube_meta
    from app.cube.model import sync_connection_models
    from app.routers.connection_metadata import write_connection_metadata_cache

    schema = await get_schema_with_descriptions(connection["slug"], use_cache=False)
    await write_connection_metadata_cache(
        connection_id=connection["id"],
        slug=connection["slug"],
        plugin=connection["plugin"],
        live_schema=schema,
    )
    await sync_connection_models()

    try:
        await load_cube_meta()
    except CubeAPIError as exc:
        raise HTTPException(
            502,
            "PostgreSQL sync completed, but Cube rejected the generated "
            f"semantic model: {exc.message}",
        ) from exc


def _google_client_id() -> str:
    value = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()

    if not value:
        raise ValueError("GOOGLE_OAUTH_CLIENT_ID is not configured")

    return value


def _google_client_secret() -> str:
    value = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()

    if not value:
        raise ValueError("GOOGLE_OAUTH_CLIENT_SECRET is not configured")

    return value
