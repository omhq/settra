from __future__ import annotations

import asyncpg

from fastapi import APIRouter, HTTPException

from app.cube.model import sync_connection_models
from app.db import db_connection
from app.routers.connection_config import (
    google_drive_has_documentation,
    load_google_drive_config,
    normalize_credentials,
    read_connection_credentials,
    read_google_drive_documentation,
    validate_connection_fields,
    visible_credentials,
)
from app.routers.connection_metadata import generate_connection_metadata
from app.routers.connection_retry import retry_connection_status
from app.routers.constants import GOOGLE_DRIVE_KEY
from app.schemas import ConnectionCreate, ConnectionUpdate, SyncConfigUpdate
from app.sync.config import (
    config_path,
    default_sync_config,
    read_sync_config_text,
    write_sync_config,
    write_sync_config_text,
)
from app.sync.loader import run_connection_sync
from app.utils import slugify_name

router = APIRouter(tags=["connections"])


@router.get("/google-drive/config")
@router.get("/google-sheets/config", include_in_schema=False)
async def get_google_drive_config():
    config = await load_google_drive_config()

    if not config:
        raise HTTPException(500, "Google Drive configuration not found")

    return {
        "name": config.get("name") or "Google Drive files",
        "description": config.get("description") or "",
        "fields": config.get("fields") or [],
        "has_documentation": google_drive_has_documentation(),
    }


@router.get("/google-drive/documentation")
@router.get("/google-sheets/documentation", include_in_schema=False)
async def get_google_drive_documentation():
    config = await load_google_drive_config()

    if not config:
        raise HTTPException(500, "Google Drive configuration not found")

    content = await read_google_drive_documentation()

    if content is None:
        raise HTTPException(404, "Setup guide not found")

    return {"name": config.get("name") or "Google Drive files", "content": content}


@router.get("/connections")
async def list_connections():
    async with db_connection() as db:
        rows = await db.fetch(
            """
            SELECT *
            FROM connections
            WHERE plugin = $1
            ORDER BY created_at DESC
            """,
            GOOGLE_DRIVE_KEY,
        )

    return [dict(row) for row in rows]


@router.post("/connections", status_code=201)
async def create_connection(data: ConnectionCreate):
    connector = await load_google_drive_config()

    if not connector:
        raise HTTPException(500, "Google Drive configuration not found")

    name = data.name.strip()

    if not name:
        raise HTTPException(400, "Connection name is required")

    credentials = _validated_fields(connector, data.credentials)
    slug = slugify_name(name)[:63].rstrip("_")
    sync_config = default_sync_config(
        slug=slug,
        file_id=credentials["file_id"],
        file_name=credentials.get("file_name") or "",
        mime_type=credentials.get("mime_type") or "",
        sheets=credentials.get("sheets") or "*",
    )
    await write_sync_config(slug, sync_config)

    async with db_connection() as db:
        try:
            row_id = await db.fetchval(
                """
                INSERT INTO connections (name, slug, plugin, status)
                VALUES ($1, $2, $3, 'pending')
                RETURNING id
                """,
                name,
                slug,
                GOOGLE_DRIVE_KEY,
            )
        except asyncpg.UniqueViolationError as exc:
            config_path(slug).unlink(missing_ok=True)
            raise HTTPException(
                409,
                "A connection with that name already exists",
            ) from exc

    sync_error = None

    try:
        await run_connection_sync(row_id, trigger="create")
    except HTTPException as exc:
        # The source definition is durable even if its first load cannot complete.
        sync_error = str(exc.detail)

    connection = await get_connection(row_id)

    if sync_error:
        connection["sync_error"] = sync_error

    return connection


@router.delete("/connections/{connection_id}")
async def delete_connection(connection_id: int):
    connection = await _connection_row(connection_id)
    slug = connection["slug"]

    async with db_connection() as db:
        await db.execute("DELETE FROM connections WHERE id = $1", connection_id)

    config_path(slug).unlink(missing_ok=True)
    config_path(slug).with_suffix(".manifest.yaml").unlink(missing_ok=True)
    from app.common.config import DATA_DIR

    (DATA_DIR / "metadata" / f"{slug}.json").unlink(missing_ok=True)
    await sync_connection_models()
    return {
        "ok": True,
        "data_retained": True,
        "detail": (
            f"The {slug} PostgreSQL schema was retained. "
            "Deleting a source does not destroy its last durable snapshot."
        ),
    }


@router.get("/connections/{connection_id}")
async def get_connection(connection_id: int):
    connection = await _connection_row(connection_id)
    connector = await load_google_drive_config()
    credentials = await read_connection_credentials(connection["slug"])
    connection["credentials"] = visible_credentials(connector, credentials)
    connection["secret_fields"] = []
    return connection


@router.get("/connections/{connection_id}/secrets")
async def get_connection_secrets(connection_id: int):
    await _connection_row(connection_id)
    return {"secrets": {}}


@router.put("/connections/{connection_id}")
async def update_connection(connection_id: int, data: ConnectionUpdate):
    connection = await _connection_row(connection_id)
    connector = await load_google_drive_config()

    if not connector:
        raise HTTPException(500, "Google Drive configuration not found")

    name = data.name.strip()

    if not name:
        raise HTTPException(400, "Connection name is required")

    fields = _validated_fields(connector, data.credentials)
    slug = connection["slug"]
    existing_text = await read_sync_config_text(slug)
    if existing_text:
        from app.sync.config import validate_sync_config

        existing = validate_sync_config(existing_text, expected_slug=slug)
    else:
        existing = default_sync_config(
            slug=slug,
            file_id=fields["file_id"],
            file_name=fields.get("file_name") or "",
            mime_type=fields.get("mime_type") or "",
            sheets=fields.get("sheets") or "*",
        )
    source = existing["source"]
    file_changed = source.get("file_id") != fields["file_id"]
    source["file_id"] = fields["file_id"]
    source["file_name"] = fields.get("file_name") or ""
    source["mime_type"] = fields.get("mime_type") or ""

    if file_changed:
        source["format"] = "auto"
        source["parsing"] = {
            "delimiter": "auto",
            "encoding": "auto",
            "header_row": "auto",
        }

    source["sheets"] = [
        item.strip()
        for item in (fields.get("sheets") or "*").split(",")
        if item.strip()
    ] or ["*"]
    await write_sync_config(slug, existing)

    async with db_connection() as db:
        await db.execute(
            "UPDATE connections SET name = $1, status = 'pending' WHERE id = $2",
            name,
            connection_id,
        )

    try:
        await run_connection_sync(connection_id, trigger="update")
    except HTTPException:
        pass

    return await get_connection(connection_id)


@router.post("/connections/{connection_id}/retry")
async def retry_connection(connection_id: int):
    return await retry_connection_status(connection_id)


@router.post("/connections/{connection_id}/sync")
async def sync_connection(connection_id: int):
    return await run_connection_sync(connection_id)


@router.get("/connections/{connection_id}/sync-runs")
async def list_sync_runs(connection_id: int, limit: int = 20):
    await _connection_row(connection_id)
    bounded_limit = max(1, min(limit, 100))
    async with db_connection() as db:
        rows = await db.fetch(
            """
            SELECT id, connection_id, trigger, status, table_count, row_count,
                   load_ids, error, started_at, finished_at
            FROM sync_runs
            WHERE connection_id = $1
            ORDER BY id DESC
            LIMIT $2
            """,
            connection_id,
            bounded_limit,
        )

    return {"runs": [dict(row) for row in rows]}


@router.get("/connections/{connection_id}/sync-config")
async def get_sync_config(connection_id: int):
    connection = await _connection_row(connection_id)
    content = await read_sync_config_text(connection["slug"])

    if not content:
        raise HTTPException(404, "Connection sync configuration is missing")

    return {"content": content}


@router.put("/connections/{connection_id}/sync-config")
async def update_sync_config(connection_id: int, data: SyncConfigUpdate):
    connection = await _connection_row(connection_id)
    config = await write_sync_config_text(connection["slug"], data.content)
    return {
        "ok": True,
        "content": await read_sync_config_text(connection["slug"]),
        "config": config,
    }


@router.post("/connections/{connection_id}/metadata")
async def generate_metadata(connection_id: int):
    return await generate_connection_metadata(connection_id)


async def _connection_row(connection_id: int) -> dict:
    async with db_connection() as db:
        row = await db.fetchrow(
            """
            SELECT id, name, slug, plugin, status, created_at,
                   last_sync_started_at, last_synced_at, last_sync_error
            FROM connections
            WHERE id = $1 AND plugin = $2
            """,
            connection_id,
            GOOGLE_DRIVE_KEY,
        )

    if not row:
        raise HTTPException(404, "Connection not found")

    return dict(row)


def _validated_fields(connector: dict, submitted: dict[str, str]) -> dict[str, str]:
    expected_keys = {field["key"] for field in connector.get("fields", [])}
    unknown = set(submitted) - expected_keys

    if unknown:
        raise HTTPException(400, f"Unexpected fields: {', '.join(sorted(unknown))}")

    credentials = normalize_credentials(connector, submitted)
    validate_connection_fields(connector, credentials)
    return credentials
