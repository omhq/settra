import aiofiles
import aiosqlite

from fastapi import APIRouter, HTTPException

from app.db import DB_PATH
from app.routers.connection_config import (
    connection_plugin_spec,
    field_is_secret,
    load_connectors,
    merge_update_credentials,
    normalize_credentials,
    read_connection_credentials,
    render_connection_hcl,
    saved_secret_fields,
    validate_connection_fields,
    validate_provider_credentials,
    visible_credentials,
)
from app.routers.connection_metadata import generate_connection_metadata
from app.routers.connection_retry import retry_connection_status
from app.routers.constants import STEAMPIPE_CONFIG_DIR
from app.schemas import ConnectionCreate, ConnectionUpdate
from app.semantic.loader import delete_connection_semantics
from app.utils import slugify_name

router = APIRouter(tags=["connections"])


@router.get("/connectors")
async def list_connectors():
    connectors = await load_connectors()

    return [{"key": key, **value} for key, value in connectors.items()]


@router.get("/connections")
async def list_connections():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("""
            SELECT id, name, slug, plugin, status, created_at
            FROM connections
            ORDER BY created_at DESC
            """) as cur:
            rows = await cur.fetchall()

    return [dict(row) for row in rows]


@router.post("/connections", status_code=201)
async def create_connection(data: ConnectionCreate):
    connectors = await load_connectors()

    if data.plugin not in connectors:
        raise HTTPException(400, f"Unknown plugin: {data.plugin}")

    connector = connectors[data.plugin]
    expected_keys = {field["key"] for field in connector.get("fields", [])}
    unknown = set(data.credentials) - expected_keys

    if unknown:
        raise HTTPException(400, f"Unexpected fields: {', '.join(unknown)}")

    credentials = normalize_credentials(connector, data.credentials)

    validate_connection_fields(connector, credentials)

    slug = slugify_name(data.name)
    spc_content = render_connection_hcl(
        slug,
        connection_plugin_spec(connector, data.plugin),
        credentials,
        connector,
    )

    STEAMPIPE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    spc_path = STEAMPIPE_CONFIG_DIR / f"{slug}.spc"

    if not str(spc_path.resolve()).startswith(str(STEAMPIPE_CONFIG_DIR.resolve())):
        raise HTTPException(400, "Invalid connection name")

    await validate_provider_credentials(connector, credentials)

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
                (data.name, slug, data.plugin, "active"),
            )
            await db.commit()
            async with db.execute("SELECT last_insert_rowid()") as cur:
                row_id = (await cur.fetchone())[0]
        except aiosqlite.IntegrityError as exc:
            spc_path.unlink(missing_ok=True)
            raise HTTPException(
                409, "A connection with that name already exists"
            ) from exc

    return {"id": row_id, "name": data.name, "plugin": data.plugin, "status": "active"}


@router.delete("/connections/{connection_id}")
async def delete_connection(connection_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            "SELECT slug FROM connections WHERE id = ?",
            (connection_id,),
        ) as cur:
            row = await cur.fetchone()

        if not row:
            raise HTTPException(404, "Connection not found")

        slug = row["slug"]

        await delete_connection_semantics(db, connection_id)

        await db.execute(
            """
            UPDATE chat_threads
            SET status = 'inactive',
                inactive_reason = 'Connection deleted',
                updated_at = datetime('now')
            WHERE status = 'active'
              AND (
                connection_id = ?
                OR id IN (
                    SELECT thread_id
                    FROM chat_thread_connections
                    WHERE connection_id = ?
                )
              )
            """,
            (connection_id, connection_id),
        )
        await db.execute("DELETE FROM connections WHERE id = ?", (connection_id,))
        await db.commit()

    spc_path = STEAMPIPE_CONFIG_DIR / f"{slug}.spc"

    spc_path.unlink(missing_ok=True)
    return {"ok": True}


@router.get("/connections/{connection_id}")
async def get_connection(connection_id: int):
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

    connection = dict(row)
    connectors = await load_connectors()
    connector = connectors.get(connection["plugin"], {})
    credentials = await read_connection_credentials(connection["slug"])
    connection["credentials"] = visible_credentials(connector, credentials)
    connection["secret_fields"] = saved_secret_fields(connector, credentials)

    return connection


@router.get("/connections/{connection_id}/secrets")
async def get_connection_secrets(connection_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            "SELECT slug, plugin FROM connections WHERE id = ?",
            (connection_id,),
        ) as cur:
            row = await cur.fetchone()

    if not row:
        raise HTTPException(404, "Connection not found")

    connectors = await load_connectors()
    connector = connectors.get(row["plugin"], {})
    credentials = await read_connection_credentials(row["slug"])
    fields_by_key = {field["key"]: field for field in connector.get("fields", [])}
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
            "SELECT slug, plugin FROM connections WHERE id = ?",
            (connection_id,),
        ) as cur:
            row = await cur.fetchone()

    if not row:
        raise HTTPException(404, "Connection not found")

    old_slug, plugin = row["slug"], row["plugin"]
    connectors = await load_connectors()
    connector = connectors[plugin]
    existing_credentials = await read_connection_credentials(old_slug)
    credentials = merge_update_credentials(
        connector,
        data.credentials,
        existing_credentials,
    )
    expected_keys = {field["key"] for field in connector.get("fields", [])}
    unknown = set(data.credentials) - expected_keys

    if unknown:
        raise HTTPException(400, f"Unexpected fields: {', '.join(unknown)}")

    validate_connection_fields(connector, credentials)

    credentials = normalize_credentials(connector, credentials)

    await validate_provider_credentials(connector, credentials)

    new_slug = slugify_name(data.name)
    spc_content = render_connection_hcl(
        new_slug,
        connection_plugin_spec(connector, plugin),
        credentials,
        connector,
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

    return await get_connection(connection_id)


@router.post("/connections/{connection_id}/retry")
async def retry_connection(connection_id: int):
    return await retry_connection_status(connection_id)


@router.post("/connections/{connection_id}/metadata")
async def generate_metadata(connection_id: int):
    return await generate_connection_metadata(connection_id)
