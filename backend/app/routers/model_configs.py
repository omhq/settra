import json

from typing import Any

import aiosqlite

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage

from app.db import DB_PATH
from app.model_configs import (
    ModelConfigError,
    build_llm,
    encrypt_json,
    get_model_config,
    public_model_config,
    public_providers,
    split_config_values,
)
from app.schemas import ModelConfigCreate, ModelConfigUpdate

router = APIRouter(tags=["models"])


def _as_http_error(exc: ModelConfigError) -> HTTPException:
    return HTTPException(400, str(exc))


def _public_response(model_config: dict[str, Any] | None) -> dict[str, Any] | None:
    if model_config is None:
        return None

    data = dict(model_config)

    data.pop("encrypted_secrets", None)
    data.pop("secrets", None)
    return data


@router.get("/model-providers")
async def list_model_providers():
    return public_providers()


@router.get("/models")
async def list_models():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("""
            SELECT id, name, provider, model, config_json, encrypted_secrets,
                   status, created_at, updated_at
            FROM models
            WHERE status = 'active'
            ORDER BY created_at DESC
            """) as cur:
            rows = await cur.fetchall()

    return [public_model_config(row) for row in rows]


@router.post("/models", status_code=201)
async def create_model(body: ModelConfigCreate):
    name = body.name.strip()

    if not name:
        raise HTTPException(400, "Model name is required")

    try:
        model, config, secrets = split_config_values(body.provider, body.config)
    except ModelConfigError as exc:
        raise _as_http_error(exc)

    encrypted_secrets = encrypt_json(secrets)

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                INSERT INTO models
                    (name, provider, model, config_json, encrypted_secrets)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    name,
                    body.provider,
                    model,
                    json.dumps(config, sort_keys=True),
                    encrypted_secrets,
                ),
            )
            await db.commit()
            async with db.execute("SELECT last_insert_rowid()") as cur:
                model_id = (await cur.fetchone())[0]
        except aiosqlite.IntegrityError as exc:
            raise HTTPException(400, "Model could not be saved") from exc

    created = await get_model_config(model_id)

    return _public_response(created)


@router.get("/models/{model_config_id}")
async def get_model(model_config_id: int):
    model_config = await get_model_config(model_config_id)

    if not model_config:
        raise HTTPException(404, "Model not found")

    return _public_response(model_config)


@router.get("/models/{model_config_id}/secrets")
async def get_model_secrets(model_config_id: int):
    try:
        model_config = await get_model_config(model_config_id, include_secrets=True)
    except ModelConfigError as exc:
        raise HTTPException(
            409,
            "Saved model secrets cannot be decrypted with the current SECRET_KEY. "
            "Re-enter the secret fields to replace them.",
        ) from exc

    if not model_config:
        raise HTTPException(404, "Model not found")

    return {"secrets": model_config.get("secrets", {})}


@router.put("/models/{model_config_id}")
async def update_model(model_config_id: int, body: ModelConfigUpdate):
    secrets_decrypt_failed = False

    try:
        existing = await get_model_config(
            model_config_id,
            include_secrets=True,
            allow_deleted=False,
        )
    except ModelConfigError:
        secrets_decrypt_failed = True
        existing = await get_model_config(model_config_id, allow_deleted=False)

    if not existing:
        raise HTTPException(404, "Model not found")

    name = body.name.strip()

    if not name:
        raise HTTPException(400, "Model name is required")

    try:
        model, config, secrets = split_config_values(
            existing["provider"],
            body.config,
            existing_secrets=(
                {} if secrets_decrypt_failed else existing.get("secrets", {})
            ),
        )
    except ModelConfigError as exc:
        if secrets_decrypt_failed:
            raise HTTPException(
                400,
                "Saved model secrets cannot be decrypted with the current SECRET_KEY. "
                "Re-enter the secret fields to replace them.",
            ) from exc
        raise _as_http_error(exc)

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                UPDATE models
                SET name = ?,
                    model = ?,
                    config_json = ?,
                    encrypted_secrets = ?,
                    updated_at = datetime('now')
                WHERE id = ? AND status = 'active'
                """,
                (
                    name,
                    model,
                    json.dumps(config, sort_keys=True),
                    encrypt_json(secrets),
                    model_config_id,
                ),
            )
            await db.commit()
        except aiosqlite.IntegrityError as exc:
            raise HTTPException(400, "Model could not be saved") from exc

    updated = await get_model_config(model_config_id)

    return _public_response(updated)


@router.post("/models/{model_config_id}/test")
async def test_model(model_config_id: int):
    model_config = await get_model_config(model_config_id, include_secrets=True)

    if not model_config:
        raise HTTPException(404, "Model not found")

    try:
        llm = build_llm(model_config)
        response = await llm.ainvoke([HumanMessage(content="Reply with exactly: ok")])
    except Exception as exc:
        raise HTTPException(422, f"Model test failed: {exc}")

    return {"ok": True, "response": getattr(response, "content", "")}


@router.delete("/models/{model_config_id}")
async def delete_model(model_config_id: int):
    existing = await get_model_config(model_config_id, allow_deleted=False)

    if not existing:
        raise HTTPException(404, "Model not found")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            DELETE FROM models
            WHERE id = ?
            """,
            (model_config_id,),
        )

        await db.commit()

    return {"ok": True}
