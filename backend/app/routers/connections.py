import asyncpg

from fastapi import APIRouter, HTTPException

from app.auth import current_identity, require_organization_write_access
from app.common.config import deployment_mode
from app.cube.model import sync_connection_models
from app.db import db_connection
from app.destinations import (
    MANAGED_DESTINATION_SLUG,
    connection_destination,
)
from app.routers.connection_config import (
    google_drive_has_documentation,
    load_google_drive_config,
    normalize_credentials,
    read_google_drive_documentation,
    validate_connection_fields,
    visible_credentials,
)
from app.routers.connection_metadata import generate_connection_metadata
from app.routers.connection_retry import retry_connection_status
from app.common.config import GOOGLE_DRIVE_KEY
from app.schemas import ConnectionCreate, ConnectionUpdate, SyncConfigUpdate
from app.sync.config import (
    connection_fields,
    connection_row_keys,
    config_path,
    default_sync_config,
    read_sync_config,
    read_sync_config_text,
    set_connection_row_keys,
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
        "has_documentation": (
            deployment_mode() == "self_hosted" and google_drive_has_documentation()
        ),
    }


@router.get("/google-drive/documentation")
@router.get("/google-sheets/documentation", include_in_schema=False)
async def get_google_drive_documentation():
    if deployment_mode() == "managed":
        raise HTTPException(404, "Setup guide not available")

    config = await load_google_drive_config()

    if not config:
        raise HTTPException(500, "Google Drive configuration not found")

    content = await read_google_drive_documentation()

    if content is None:
        raise HTTPException(404, "Setup guide not found")

    return {"name": config.get("name") or "Google Drive files", "content": content}


@router.get("/connections")
async def list_connections():
    identity = current_identity()
    async with db_connection() as db:
        rows = await db.fetch(
            """
            SELECT c.*,
                   d.name AS destination_name,
                   d.slug AS destination_slug,
                   d.type AS destination_type,
                   d.configuration AS destination_configuration,
                   d.is_builtin AS destination_is_builtin,
                   d.is_default AS destination_is_default
            FROM connections c
            JOIN destinations d ON d.id = c.destination_id
            WHERE c.plugin = $1 AND c.organization_id = $2
            ORDER BY c.created_at DESC
            """,
            GOOGLE_DRIVE_KEY,
            identity.organization_id,
        )

    return [_connection_response(row) for row in rows]


@router.post("/connections", status_code=201)
async def create_connection(data: ConnectionCreate):
    identity = require_organization_write_access()
    connector = await load_google_drive_config()

    if not connector:
        raise HTTPException(500, "Google Drive configuration not found")

    name = data.name.strip()

    if not name:
        raise HTTPException(400, "Connection name is required")

    credentials = _validated_fields(connector, data.credentials)
    slug = slugify_name(name)[:40].rstrip("_")
    if not slug:
        raise HTTPException(400, "Connection name must contain letters or numbers")
    storage_key = f"o{identity.organization_id}_{slug}"
    async with db_connection() as db:
        destination = await _destination_row(db, data.destination_id)

    sync_config = default_sync_config(
        slug=storage_key,
        file_id=credentials["file_id"],
        file_name=credentials.get("file_name") or "",
        mime_type=credentials.get("mime_type") or "",
        sheets=credentials.get("sheets") or "*",
        destination_key=destination["slug"],
        destination_type=destination["type"],
        destination_schema=storage_key,
        row_keys=data.row_keys,
    )
    async with db_connection() as db:
        try:
            row_id = await db.fetchval(
                """
                INSERT INTO connections
                    (name, slug, storage_key, plugin, status, destination_id,
                     destination_schema, organization_id, created_by_user_id)
                VALUES ($1, $2, $3, $4, 'pending', $5, $6, $7, $8)
                RETURNING id
                """,
                name,
                slug,
                storage_key,
                GOOGLE_DRIVE_KEY,
                destination["id"],
                storage_key,
                identity.organization_id,
                identity.user_id,
            )
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(
                409,
                "A connection with that name already exists",
            ) from exc

    try:
        await write_sync_config(
            storage_key,
            sync_config,
            expected_destination_key=destination["slug"],
            expected_destination_schema=storage_key,
        )
    except Exception:
        async with db_connection() as db:
            await db.execute(
                "DELETE FROM connections WHERE id = $1 AND organization_id = $2",
                row_id,
                identity.organization_id,
            )
        raise

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
    require_organization_write_access()
    connection = await _connection_row(connection_id)
    storage_key = connection["storage_key"]

    async with db_connection() as db:
        await db.execute(
            "DELETE FROM connections WHERE id = $1 AND organization_id = $2",
            connection_id,
            current_identity().organization_id,
        )

    config_path(storage_key).unlink(missing_ok=True)
    config_path(storage_key).with_suffix(".manifest.yaml").unlink(missing_ok=True)
    from app.common.config import DATA_DIR

    (DATA_DIR / "metadata" / f"{storage_key}.json").unlink(missing_ok=True)
    await sync_connection_models()
    return {
        "ok": True,
        "data_retained": True,
        "detail": (
            f"The {connection['destination_schema']} schema in "
            f"{connection['destination']['name']} was retained. "
            "Deleting a source does not destroy its last durable snapshot."
        ),
    }


@router.get("/connections/{connection_id}")
async def get_connection(connection_id: int):
    connection = await _connection_row(connection_id)
    connector = await load_google_drive_config()
    sync_config = await read_sync_config(connection["storage_key"])
    credentials = connection_fields(sync_config) if sync_config else {}
    connection["credentials"] = visible_credentials(connector, credentials)
    connection["row_keys"] = connection_row_keys(sync_config)
    connection["secret_fields"] = []
    connection.pop("storage_key", None)
    return connection


@router.get("/connections/{connection_id}/secrets")
async def get_connection_secrets(connection_id: int):
    await _connection_row(connection_id)
    return {"secrets": {}}


@router.put("/connections/{connection_id}")
async def update_connection(connection_id: int, data: ConnectionUpdate):
    require_organization_write_access()
    connection = await _connection_row(connection_id)
    connector = await load_google_drive_config()

    if not connector:
        raise HTTPException(500, "Google Drive configuration not found")

    name = data.name.strip()

    if not name:
        raise HTTPException(400, "Connection name is required")

    fields = _validated_fields(connector, data.credentials)
    storage_key = connection["storage_key"]
    destination = connection["destination"]

    if data.destination_id is not None and data.destination_id != destination["id"]:
        async with db_connection() as db:
            destination = dict(await _destination_row(db, data.destination_id))

    existing_text = await read_sync_config_text(storage_key)
    if existing_text:
        from app.sync.config import validate_sync_config

        existing = validate_sync_config(
            existing_text,
            expected_destination_key=connection["destination"]["slug"],
            expected_destination_schema=connection["destination_schema"],
        )
    else:
        existing = default_sync_config(
            slug=storage_key,
            file_id=fields["file_id"],
            file_name=fields.get("file_name") or "",
            mime_type=fields.get("mime_type") or "",
            sheets=fields.get("sheets") or "*",
            destination_key=destination["slug"],
            destination_type=destination["type"],
            destination_schema=connection["destination_schema"],
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

    source["sheets"] = _submitted_sheet_patterns(fields.get("sheets"))
    submitted_row_keys = data.row_keys

    if file_changed and submitted_row_keys is None:
        submitted_row_keys = {}
    if submitted_row_keys is not None:
        existing = set_connection_row_keys(existing, submitted_row_keys)

    existing["destination"]["key"] = destination["slug"]
    existing["destination"]["type"] = destination["type"]
    existing["destination"]["schema"] = connection["destination_schema"]
    await write_sync_config(
        storage_key,
        existing,
        expected_destination_key=destination["slug"],
        expected_destination_schema=connection["destination_schema"],
    )

    async with db_connection() as db:
        await db.execute(
            """
            UPDATE connections
            SET name = $1, destination_id = $2, status = 'pending'
            WHERE id = $3
            """,
            name,
            destination["id"],
            connection_id,
        )

    try:
        await run_connection_sync(connection_id, trigger="update")
    except HTTPException:
        pass

    return await get_connection(connection_id)


@router.post("/connections/{connection_id}/retry")
async def retry_connection(connection_id: int):
    require_organization_write_access()
    return await retry_connection_status(connection_id)


@router.post("/connections/{connection_id}/sync")
async def sync_connection(connection_id: int):
    require_organization_write_access()
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
    content = await read_sync_config_text(connection["storage_key"])

    if not content:
        raise HTTPException(404, "Connection sync configuration is missing")

    return {"content": content}


@router.put("/connections/{connection_id}/sync-config")
async def update_sync_config(connection_id: int, data: SyncConfigUpdate):
    require_organization_write_access()
    connection = await _connection_row(connection_id)
    config = await write_sync_config_text(
        connection["storage_key"],
        data.content,
        expected_destination_key=connection["destination"]["slug"],
        expected_destination_schema=connection["destination_schema"],
    )
    return {
        "ok": True,
        "content": await read_sync_config_text(connection["storage_key"]),
        "config": config,
        "row_keys": connection_row_keys(config),
    }


@router.post("/connections/{connection_id}/metadata")
async def generate_metadata(connection_id: int):
    return await generate_connection_metadata(connection_id)


async def _connection_row(connection_id: int) -> dict:
    async with db_connection() as db:
        row = await db.fetchrow(
            """
            SELECT c.id, c.name, c.slug, c.plugin, c.status, c.created_at,
                   c.last_sync_started_at, c.last_synced_at, c.last_sync_error,
                   c.destination_id, c.destination_schema, c.storage_key,
                   d.name AS destination_name,
                   d.slug AS destination_slug,
                   d.type AS destination_type,
                   d.configuration AS destination_configuration,
                   d.is_builtin AS destination_is_builtin,
                   d.is_default AS destination_is_default
            FROM connections c
            JOIN destinations d ON d.id = c.destination_id
            WHERE c.id = $1 AND c.plugin = $2 AND c.organization_id = $3
            """,
            connection_id,
            GOOGLE_DRIVE_KEY,
            current_identity().organization_id,
        )

    if not row:
        raise HTTPException(404, "Connection not found")

    return _connection_response(row, include_storage_key=True)


async def _destination_row(db, destination_id: int | None):
    if destination_id is None:
        row = await db.fetchrow("""
            SELECT id, name, slug, type, configuration, is_builtin, is_default
            FROM destinations
            WHERE is_default = true
            """)
    else:
        row = await db.fetchrow(
            """
            SELECT id, name, slug, type, configuration, is_builtin, is_default
            FROM destinations
            WHERE id = $1
            """,
            destination_id,
        )

    if not row:
        raise HTTPException(422, "Destination not found")
    if row["slug"] != MANAGED_DESTINATION_SLUG or row["type"] != "postgres":
        raise HTTPException(
            422,
            "Only the managed PostgreSQL destination is currently supported",
        )

    return row


def _connection_response(row, *, include_storage_key: bool = False) -> dict:
    connection = dict(row)
    destination = connection_destination(connection)

    for key in (
        "destination_name",
        "destination_slug",
        "destination_type",
        "destination_configuration",
        "destination_is_builtin",
        "destination_is_default",
    ):
        connection.pop(key, None)

    connection["destination"] = destination
    if not include_storage_key:
        connection.pop("storage_key", None)
    connection.pop("organization_id", None)
    connection.pop("created_by_user_id", None)
    return connection


def _validated_fields(
    connector: dict,
    submitted: dict[str, str | list[str]],
) -> dict[str, str | list[str]]:
    expected_keys = {field["key"] for field in connector.get("fields", [])}
    unknown = set(submitted) - expected_keys

    if unknown:
        raise HTTPException(400, f"Unexpected fields: {', '.join(sorted(unknown))}")

    credentials = normalize_credentials(connector, submitted)
    validate_connection_fields(connector, credentials)
    return credentials


def _submitted_sheet_patterns(value: str | list[str] | None) -> list[str]:
    if isinstance(value, list):
        patterns = [str(item).strip() for item in value if str(item).strip()]
    else:
        patterns = [
            item.strip()
            for line in str(value or "*").splitlines()
            for item in line.split(",")
            if item.strip()
        ]

    return patterns or ["*"]
