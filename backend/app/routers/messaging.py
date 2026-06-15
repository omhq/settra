import json

from typing import Any

import aiosqlite

from fastapi import APIRouter, HTTPException, Request, Response

from app.db import DB_PATH
from app.messaging.base import MessagingProviderError
from app.messaging.configs import (
    MessagingConfigError,
    encrypted_secrets,
    get_messaging_config,
    public_messaging_config,
    split_config_values,
)
from app.messaging.discovery import (
    get_channel_definition,
    list_channel_definitions,
    load_provider,
)
from app.messaging.service import process_webhook, verify_webhook
from app.schemas import MessagingConfigCreate, MessagingConfigUpdate

router = APIRouter(prefix="/messaging", tags=["messaging"])


@router.get("/providers")
async def list_messaging_providers():
    return [definition.public_dict() for definition in list_channel_definitions()]


@router.get("/configs")
async def list_messaging_configs():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("""
            SELECT id, name, provider, config_json, encrypted_secrets,
                   default_model_config_id, default_connection_ids_json,
                   status, created_at, updated_at
            FROM messaging_configs
            WHERE status = 'active'
            ORDER BY datetime(updated_at) DESC, id DESC
            """) as cur:
            rows = await cur.fetchall()

    return [public_messaging_config(row) for row in rows]


@router.post("/configs", status_code=201)
async def create_messaging_config(body: MessagingConfigCreate):
    name = body.name.strip()

    if not name:
        raise HTTPException(400, "Messaging config name is required")

    try:
        get_channel_definition(body.provider)

        config, secrets = split_config_values(body.provider, body.config)

        await load_provider(body.provider).validate_config(config, secrets)
    except (MessagingConfigError, MessagingProviderError) as exc:
        raise HTTPException(400, str(exc))

    connection_ids = await _validate_defaults(
        body.model_config_id,
        body.connection_ids,
    )

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                INSERT INTO messaging_configs (
                    name,
                    provider,
                    config_json,
                    encrypted_secrets,
                    default_model_config_id,
                    default_connection_ids_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    body.provider,
                    json.dumps(config, sort_keys=True),
                    encrypted_secrets(secrets),
                    body.model_config_id,
                    json.dumps(connection_ids),
                ),
            )
            await db.commit()
            async with db.execute("SELECT last_insert_rowid()") as cur:
                config_id = (await cur.fetchone())[0]
        except aiosqlite.IntegrityError:
            raise HTTPException(409, "A messaging config with that name already exists")

    created = await get_messaging_config(config_id)

    return _public_response(created)


@router.get("/configs/{config_id}")
async def get_config(config_id: int):
    config = await get_messaging_config(config_id)

    if not config:
        raise HTTPException(404, "Messaging config not found")

    return _public_response(config)


@router.get("/configs/{config_id}/secrets")
async def get_config_secrets(config_id: int):
    try:
        config = await get_messaging_config(config_id, include_secrets=True)
    except MessagingConfigError as exc:
        raise HTTPException(
            409,
            "Saved channel secrets cannot be decrypted with the current SECRET_KEY. "
            "Re-enter the secret fields to replace them.",
        ) from exc

    if not config:
        raise HTTPException(404, "Messaging config not found")

    return {"secrets": config.get("secrets", {})}


@router.put("/configs/{config_id}")
async def update_config(config_id: int, body: MessagingConfigUpdate):
    secrets_decrypt_failed = False

    try:
        existing = await get_messaging_config(
            config_id,
            include_secrets=True,
            allow_inactive=False,
        )
    except MessagingConfigError:
        secrets_decrypt_failed = True
        existing = await get_messaging_config(config_id, allow_inactive=False)

    if not existing:
        raise HTTPException(404, "Messaging config not found")

    name = body.name.strip()

    if not name:
        raise HTTPException(400, "Messaging config name is required")

    try:
        config, secrets = split_config_values(
            existing["provider"],
            body.config,
            existing_secrets=(
                {} if secrets_decrypt_failed else existing.get("secrets", {})
            ),
        )
        await load_provider(existing["provider"]).validate_config(config, secrets)
    except (MessagingConfigError, MessagingProviderError) as exc:
        if secrets_decrypt_failed:
            raise HTTPException(
                400,
                "Saved channel secrets cannot be decrypted with the current SECRET_KEY. "
                "Re-enter the secret fields to replace them.",
            ) from exc
        raise HTTPException(400, str(exc))

    connection_ids = await _validate_defaults(
        body.model_config_id,
        body.connection_ids,
    )

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                UPDATE messaging_configs
                SET name = ?,
                    config_json = ?,
                    encrypted_secrets = ?,
                    default_model_config_id = ?,
                    default_connection_ids_json = ?,
                    updated_at = datetime('now')
                WHERE id = ? AND status = 'active'
                """,
                (
                    name,
                    json.dumps(config, sort_keys=True),
                    encrypted_secrets(secrets),
                    body.model_config_id,
                    json.dumps(connection_ids),
                    config_id,
                ),
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            raise HTTPException(409, "A messaging config with that name already exists")

    updated = await get_messaging_config(config_id)

    return _public_response(updated)


@router.delete("/configs/{config_id}")
async def delete_config(config_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            UPDATE messaging_configs
            SET status = 'deleted',
                encrypted_secrets = '',
                updated_at = datetime('now')
            WHERE id = ? AND status = 'active'
            """,
            (config_id,),
        )
        await db.commit()

    if cur.rowcount == 0:
        raise HTTPException(404, "Messaging config not found")

    return {"ok": True}


@router.get("/webhooks/{provider}/{config_id}")
async def webhook_verification(provider: str, config_id: int, request: Request):
    result = await verify_webhook(provider, config_id, request)

    if result is None:
        raise HTTPException(404, "Webhook verification is not supported")

    return Response(
        content=result.content,
        status_code=result.status_code,
        media_type=result.media_type,
        headers=result.headers,
    )


@router.post("/webhooks/{provider}/{config_id}")
async def webhook(provider: str, config_id: int, request: Request):
    return await process_webhook(provider, config_id, request)


def _public_response(config: dict[str, Any] | None) -> dict[str, Any] | None:
    if config is None:
        return None

    data = dict(config)

    data.pop("encrypted_secrets", None)
    data.pop("secrets", None)
    return data


async def _validate_defaults(
    model_config_id: int,
    connection_ids: list[int],
) -> list[int]:
    if not connection_ids:
        raise HTTPException(400, "At least one connection is required")

    unique_connection_ids = list(dict.fromkeys(connection_ids))

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT id
            FROM models
            WHERE id = ? AND status = 'active'
            """,
            (model_config_id,),
        ) as cur:
            model = await cur.fetchone()

        if not model:
            raise HTTPException(404, "Model not found")

        placeholders = ", ".join("?" for _ in unique_connection_ids)

        async with db.execute(
            f"""
            SELECT id
            FROM connections
            WHERE id IN ({placeholders}) AND status = 'active'
            """,
            unique_connection_ids,
        ) as cur:
            rows = await cur.fetchall()

    found = {row[0] for row in rows}
    missing = [
        connection_id
        for connection_id in unique_connection_ids
        if connection_id not in found
    ]

    if missing:
        raise HTTPException(404, f"Connection(s) not found or inactive: {missing}")

    return unique_connection_ids
