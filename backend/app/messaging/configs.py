import json

from typing import Any

import aiosqlite

from app.db import DB_PATH
from app.messaging.base import MessagingProviderError
from app.messaging.discovery import get_channel_definition
from app.model_configs import ModelConfigError, decrypt_json, encrypt_json


class MessagingConfigError(ValueError):
    pass


def _field_map(provider: str) -> dict[str, dict[str, Any]]:
    definition = get_channel_definition(provider)
    return {field["key"]: field for field in definition.fields}


def _coerce_field_value(field: dict[str, Any], value: Any) -> Any:
    if value is None or value == "":
        return None

    field_type = field.get("type")

    if field_type == "number":
        numeric = float(value)
        return int(numeric) if numeric.is_integer() else numeric

    if field_type == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    return str(value)


def split_config_values(
    provider: str,
    values: dict[str, Any],
    existing_secrets: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    fields = _field_map(provider)
    existing_secrets = existing_secrets or {}
    unknown = set(values) - set(fields)

    if unknown:
        raise MessagingConfigError(
            f"Unexpected messaging fields: {', '.join(sorted(unknown))}"
        )

    config: dict[str, Any] = {}
    secrets = dict(existing_secrets)

    for key, field in fields.items():
        value = values.get(key, field.get("default"))
        coerced = _coerce_field_value(field, value)

        if field.get("type") == "secret":
            if coerced:
                secrets[key] = coerced
            elif field.get("required") and key not in secrets:
                raise MessagingConfigError(f"{field.get('label', key)} is required")
            continue

        if coerced is not None:
            config[key] = coerced
        elif field.get("required"):
            raise MessagingConfigError(f"{field.get('label', key)} is required")

    return config, secrets


def decrypt_messaging_secrets(token: str) -> dict[str, Any]:
    try:
        return decrypt_json(token)
    except ModelConfigError as exc:
        raise MessagingConfigError(
            "Could not decrypt messaging secrets. Check SECRET_KEY."
        ) from exc


def public_messaging_config(row: aiosqlite.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    definition = get_channel_definition(data["provider"])
    secret_fields = [
        field["key"] for field in definition.fields if field.get("type") == "secret"
    ]

    return {
        "id": data["id"],
        "name": data["name"],
        "provider": data["provider"],
        "config": json.loads(data.get("config_json") or "{}"),
        "secret_fields": secret_fields,
        "model_config_id": data["default_model_config_id"],
        "connection_ids": json.loads(data.get("default_connection_ids_json") or "[]"),
        "status": data["status"],
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
    }


async def get_messaging_config(
    config_id: int,
    *,
    include_secrets: bool = False,
    allow_inactive: bool = False,
) -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT id, name, provider, config_json, encrypted_secrets,
                   default_model_config_id, default_connection_ids_json,
                   status, created_at, updated_at
            FROM messaging_configs
            WHERE id = ?
        """
        params: tuple[Any, ...] = (config_id,)

        if not allow_inactive:
            query += " AND status = 'active'"

        async with db.execute(query, params) as cur:
            row = await cur.fetchone()

    if not row:
        return None

    config = public_messaging_config(row)
    config["encrypted_secrets"] = row["encrypted_secrets"]

    if include_secrets:
        config["secrets"] = decrypt_messaging_secrets(row["encrypted_secrets"])

    return config


def encrypted_secrets(secrets: dict[str, Any]) -> str:
    return encrypt_json(secrets)


def as_config_error(exc: Exception) -> MessagingConfigError:
    if isinstance(exc, MessagingConfigError):
        return exc
    if isinstance(exc, MessagingProviderError):
        return MessagingConfigError(str(exc))
    return MessagingConfigError(str(exc))
