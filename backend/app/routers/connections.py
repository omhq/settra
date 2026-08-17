import aiofiles
import aiosqlite

from fastapi import APIRouter, HTTPException

from app.cube.model import sync_connection_models
from app.db import DB_PATH
from app.routers.connection_config import (
    field_is_secret,
    google_sheets_has_documentation,
    google_sheets_plugin_spec,
    load_google_sheets_config,
    merge_update_credentials,
    normalize_credentials,
    read_connection_credentials,
    read_google_sheets_documentation,
    render_connection_hcl,
    saved_secret_fields,
    validate_connection_fields,
    visible_credentials,
)
from app.routers.connection_metadata import generate_connection_metadata
from app.routers.connection_retry import retry_connection_status
from app.routers.constants import GOOGLE_SHEETS_KEY, STEAMPIPE_CONFIG_DIR
from app.schemas import ConnectionCreate, ConnectionUpdate
from app.utils import slugify_name

router = APIRouter(tags=["connections"])


@router.get("/google-sheets/config")
async def get_google_sheets_config():
    config = await load_google_sheets_config()

    if not config:
        raise HTTPException(500, "Google Sheets configuration not found")

    return {
        "name": config.get("name") or "Google Sheets",
        "description": config.get("description") or "",
        "fields": config.get("fields") or [],
        "has_documentation": google_sheets_has_documentation(),
    }


@router.get("/google-sheets/documentation")
async def get_google_sheets_documentation():
    config = await load_google_sheets_config()

    if not config:
        raise HTTPException(500, "Google Sheets configuration not found")

    content = await read_google_sheets_documentation()

    if content is None:
        raise HTTPException(404, "Setup guide not found")

    return {
        "name": config.get("name") or "Google Sheets",
        "content": content,
    }


@router.get("/connections")
async def list_connections():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("""
            SELECT id, name, slug, plugin, status, created_at
            FROM connections
            WHERE plugin = ?
            ORDER BY created_at DESC
            """, (GOOGLE_SHEETS_KEY,)) as cur:
            rows = await cur.fetchall()

    return [dict(row) for row in rows]


@router.post("/connections", status_code=201)
async def create_connection(data: ConnectionCreate):
    config = await load_google_sheets_config()

    if not config:
        raise HTTPException(500, "Google Sheets configuration not found")

    expected_keys = {field["key"] for field in config.get("fields", [])}
    unknown = set(data.credentials) - expected_keys

    if unknown:
        raise HTTPException(400, f"Unexpected fields: {', '.join(unknown)}")

    credentials = normalize_credentials(config, data.credentials)

    validate_connection_fields(config, credentials)

    slug = slugify_name(data.name)
    spc_content = render_connection_hcl(
        slug,
        google_sheets_plugin_spec(config),
        credentials,
        config,
    )

    STEAMPIPE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    spc_path = STEAMPIPE_CONFIG_DIR / f"{slug}.spc"

    if not str(spc_path.resolve()).startswith(str(STEAMPIPE_CONFIG_DIR.resolve())):
        raise HTTPException(400, "Invalid connection name")

    async with aiofiles.open(spc_path, "w") as f:
        await f.write(spc_content)

    spc_path.chmod(0o644)

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                INSERT INTO connections (name, slug, plugin, status)
                VALUES (?, ?, ?, ?)
                """,
                (data.name, slug, GOOGLE_SHEETS_KEY, "active"),
            )
            await db.commit()
            async with db.execute("SELECT last_insert_rowid()") as cur:
                row_id = (await cur.fetchone())[0]
        except aiosqlite.IntegrityError as exc:
            spc_path.unlink(missing_ok=True)
            raise HTTPException(
                409, "A connection with that name already exists"
            ) from exc

    await sync_connection_models()

    return {
        "id": row_id,
        "name": data.name,
        "plugin": GOOGLE_SHEETS_KEY,
        "status": "active",
    }


@router.delete("/connections/{connection_id}")
async def delete_connection(connection_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            "SELECT slug FROM connections WHERE id = ? AND plugin = ?",
            (connection_id, GOOGLE_SHEETS_KEY),
        ) as cur:
            row = await cur.fetchone()

        if not row:
            raise HTTPException(404, "Connection not found")

        slug = row["slug"]

        await db.execute("DELETE FROM connections WHERE id = ?", (connection_id,))
        await db.commit()

    spc_path = STEAMPIPE_CONFIG_DIR / f"{slug}.spc"

    spc_path.unlink(missing_ok=True)
    await sync_connection_models()
    return {"ok": True}


@router.get("/connections/{connection_id}")
async def get_connection(connection_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            """
            SELECT id, name, slug, plugin, status, created_at
            FROM connections
            WHERE id = ? AND plugin = ?
            """,
            (connection_id, GOOGLE_SHEETS_KEY),
        ) as cur:
            row = await cur.fetchone()

    if not row:
        raise HTTPException(404, "Connection not found")

    connection = dict(row)
    config = await load_google_sheets_config()
    credentials = await read_connection_credentials(connection["slug"])
    connection["credentials"] = visible_credentials(config, credentials)
    connection["secret_fields"] = saved_secret_fields(config, credentials)

    return connection


@router.get("/connections/{connection_id}/secrets")
async def get_connection_secrets(connection_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            "SELECT slug, plugin FROM connections WHERE id = ? AND plugin = ?",
            (connection_id, GOOGLE_SHEETS_KEY),
        ) as cur:
            row = await cur.fetchone()

    if not row:
        raise HTTPException(404, "Connection not found")

    config = await load_google_sheets_config()
    credentials = await read_connection_credentials(row["slug"])
    fields_by_key = {field["key"]: field for field in config.get("fields", [])}
    secrets = {
        key: value
        for key, value in credentials.items()
        if value and field_is_secret(fields_by_key.get(key, {}))
    }

    return {"secrets": secrets}


@router.put("/connections/{connection_id}")
async def update_connection(connection_id: int, data: ConnectionUpdate):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            "SELECT slug, plugin FROM connections WHERE id = ? AND plugin = ?",
            (connection_id, GOOGLE_SHEETS_KEY),
        ) as cur:
            row = await cur.fetchone()

    if not row:
        raise HTTPException(404, "Connection not found")

    old_slug = row["slug"]
    config = await load_google_sheets_config()

    if not config:
        raise HTTPException(500, "Google Sheets configuration not found")
    existing_credentials = await read_connection_credentials(old_slug)
    credentials = merge_update_credentials(
        config,
        data.credentials,
        existing_credentials,
    )
    expected_keys = {field["key"] for field in config.get("fields", [])}
    unknown = set(data.credentials) - expected_keys

    if unknown:
        raise HTTPException(400, f"Unexpected fields: {', '.join(unknown)}")

    validate_connection_fields(config, credentials)

    credentials = normalize_credentials(config, credentials)

    new_slug = slugify_name(data.name)
    spc_content = render_connection_hcl(
        new_slug,
        google_sheets_plugin_spec(config),
        credentials,
        config,
    )
    new_spc_path = STEAMPIPE_CONFIG_DIR / f"{new_slug}.spc"

    if not str(new_spc_path.resolve()).startswith(str(STEAMPIPE_CONFIG_DIR.resolve())):
        raise HTTPException(400, "Invalid connection name")

    async with aiofiles.open(new_spc_path, "w") as f:
        await f.write(spc_content)

    new_spc_path.chmod(0o644)

    if old_slug != new_slug:
        (STEAMPIPE_CONFIG_DIR / f"{old_slug}.spc").unlink(missing_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                UPDATE connections
                SET name = ?, slug = ?, status = 'active'
                WHERE id = ?
                """,
                (data.name, new_slug, connection_id),
            )
            await db.commit()
        except aiosqlite.IntegrityError as exc:
            new_spc_path.unlink(missing_ok=True)
            raise HTTPException(
                409, "A connection with that name already exists"
            ) from exc

    await sync_connection_models()
    return await get_connection(connection_id)


@router.post("/connections/{connection_id}/retry")
async def retry_connection(connection_id: int):
    return await retry_connection_status(connection_id)


@router.post("/connections/{connection_id}/metadata")
async def generate_metadata(connection_id: int):
    return await generate_connection_metadata(connection_id)
