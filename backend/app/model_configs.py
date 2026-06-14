import os
import json
import base64
import hashlib
import logging

from pathlib import Path
from typing import Any

import yaml
import litellm
import aiosqlite

from cryptography.fernet import Fernet, InvalidToken
from langchain_litellm import ChatLiteLLM

from app.common.config import CONFIG_DIR
from app.common.logging import env_flag
from app.db import DB_PATH

logger = logging.getLogger(__name__)

SECRET_KEY_ENV = "SECRET_KEY"
DEV_SECRET_KEY = "dev-secret-change-me"


class ModelConfigError(ValueError):
    pass


def _default_model_providers_yaml() -> Path:
    config_path = CONFIG_DIR / "models" / "providers.yaml"

    if config_path.exists():
        return config_path

    return Path(__file__).resolve().parents[2] / "models" / "providers.yaml"


MODEL_PROVIDERS_YAML = Path(
    os.getenv("MODEL_PROVIDERS_YAML", str(_default_model_providers_yaml()))
)


def _fernet() -> Fernet:
    secret = os.getenv(SECRET_KEY_ENV) or DEV_SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_json(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, sort_keys=True).encode()
    return _fernet().encrypt(data).decode()


def decrypt_json(token: str) -> dict[str, Any]:
    if not token:
        return {}

    try:
        data = _fernet().decrypt(token.encode())
    except InvalidToken as exc:
        raise ModelConfigError(
            f"Could not decrypt model secrets. Check {SECRET_KEY_ENV}."
        ) from exc

    return json.loads(data.decode())


def load_model_providers() -> dict[str, Any]:
    if not MODEL_PROVIDERS_YAML.exists():
        return {"providers": {}}

    data = yaml.safe_load(MODEL_PROVIDERS_YAML.read_text()) or {}
    data.setdefault("providers", {})

    return data


def get_provider(provider: str) -> dict[str, Any]:
    providers = load_model_providers()["providers"]

    if provider not in providers:
        raise ModelConfigError(f"Unknown model provider: {provider}")

    return providers[provider]


def public_providers() -> list[dict[str, Any]]:
    providers = load_model_providers()["providers"]
    return [{"key": key, **value} for key, value in providers.items()]


def _field_map(provider_def: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {field["key"]: field for field in provider_def.get("fields", [])}


def _coerce_field_value(field: dict[str, Any], value: Any) -> Any:
    if value is None or value == "":
        return None

    if field.get("type") == "number":
        numeric = float(value)

        if numeric.is_integer():
            numeric = int(numeric)

        return numeric

    return str(value)


def split_config_values(
    provider: str,
    values: dict[str, Any],
    existing_secrets: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    provider_def = get_provider(provider)
    fields = _field_map(provider_def)

    existing_secrets = existing_secrets or {}

    unknown = set(values) - set(fields)

    if unknown:
        raise ModelConfigError(f"Unexpected model fields: {', '.join(sorted(unknown))}")

    config: dict[str, Any] = {}
    secrets = dict(existing_secrets)

    for key, field in fields.items():
        value = values.get(key, field.get("default"))
        coerced = _coerce_field_value(field, value)

        if field.get("type") == "secret":
            if coerced:
                secrets[key] = coerced
            elif field.get("required") and key not in secrets:
                raise ModelConfigError(f"{field.get('label', key)} is required")
            continue

        if coerced is not None:
            config[key] = coerced
        elif field.get("required"):
            raise ModelConfigError(f"{field.get('label', key)} is required")

    model = str(config.get("model") or "").strip()

    if not model:
        raise ModelConfigError("Model is required")

    return model, config, secrets


def public_model_config(row: aiosqlite.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    config = json.loads(data.get("config_json") or "{}")
    provider_def = get_provider(data["provider"])
    secret_fields = [
        field["key"]
        for field in provider_def.get("fields", [])
        if field.get("type") == "secret"
    ]

    return {
        "id": data["id"],
        "name": data["name"],
        "provider": data["provider"],
        "model": data["model"],
        "config": config,
        "secret_fields": secret_fields,
        "status": data["status"],
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
    }


async def get_model_config(
    model_config_id: int,
    *,
    include_secrets: bool = False,
    allow_deleted: bool = False,
) -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT id, name, provider, model, config_json, encrypted_secrets,
                   status, created_at, updated_at
            FROM model_configs
            WHERE id = ?
        """
        params: tuple[Any, ...] = (model_config_id,)

        if not allow_deleted:
            query += " AND status = 'active'"

        async with db.execute(query, params) as cur:
            row = await cur.fetchone()

    if not row:
        return None

    data = public_model_config(row)
    data["encrypted_secrets"] = row["encrypted_secrets"]

    if include_secrets:
        data["secrets"] = decrypt_json(row["encrypted_secrets"])

    return data


def snapshot_model_config(model_config: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": model_config["id"],
        "name": model_config["name"],
        "provider": model_config["provider"],
        "model": model_config["model"],
        "config": model_config["config"],
        "encrypted_secrets": model_config["encrypted_secrets"],
    }


def load_model_from_snapshot(snapshot_json: str | None) -> dict[str, Any]:
    if not snapshot_json:
        raise ModelConfigError("Chat does not have an active model snapshot")

    snapshot = json.loads(snapshot_json)
    snapshot["secrets"] = decrypt_json(snapshot.get("encrypted_secrets", ""))

    return snapshot


def _litellm_model_name(model_config: dict[str, Any]) -> str:
    provider_def = get_provider(model_config["provider"])
    model = str(model_config["model"])
    prefix = provider_def.get("model_prefix") or ""

    if prefix and not model.startswith(prefix):
        return f"{prefix}{model}"

    return model


def build_llm(model_config: dict[str, Any]) -> ChatLiteLLM:
    config = dict(model_config.get("config") or {})
    secrets = dict(model_config.get("secrets") or {})
    params = {
        **config,
        **secrets,
        "model": _litellm_model_name(model_config),
    }
    params = {key: value for key, value in params.items() if value not in ("", None)}

    if env_flag("LITELLM_DEBUG"):
        litellm._turn_on_debug()
        litellm.suppress_debug_info = False
        logging.getLogger("LiteLLM").setLevel(logging.INFO)
        logging.getLogger("litellm").setLevel(logging.INFO)
        logger.warning(
            "LiteLLM debug logging is enabled. Provider request/response payloads may be logged."
        )
    else:
        litellm.suppress_debug_info = True

    logger.info(
        "Building chat model config_id=%s provider=%s model=%s params=%s",
        model_config.get("id"),
        model_config.get("provider"),
        params.get("model"),
        _redacted_params(params),
    )

    return ChatLiteLLM(**params)


def _redacted_params(params: dict[str, Any]) -> dict[str, Any]:
    redacted = {}

    for key, value in params.items():
        lowered = key.lower()

        if any(token in lowered for token in ("key", "secret", "token", "password")):
            redacted[key] = "<redacted>"
        else:
            redacted[key] = value

    return redacted
