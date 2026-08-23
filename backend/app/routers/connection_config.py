import aiofiles

from fastapi import HTTPException

from app.routers.constants import (
    GOOGLE_DRIVE_CONFIG_DIR,
    GOOGLE_DRIVE_KEY,
    LEGACY_GOOGLE_DRIVE_CONFIG_DIR,
    LEGACY_GOOGLE_DRIVE_KEY,
)
from app.sync.config import connection_fields, read_sync_config
from app.utils import load_yaml_file


async def load_google_drive_config() -> dict:
    """Load the Google Drive tabular source configuration."""

    config_dir = (
        GOOGLE_DRIVE_CONFIG_DIR
        if GOOGLE_DRIVE_CONFIG_DIR.exists()
        else LEGACY_GOOGLE_DRIVE_CONFIG_DIR
    )

    for name in ("connection.yaml", "connection.yml"):
        path = config_dir / name

        if path.is_file():
            config = await load_yaml_file(path) or {}

            if (
                config_dir == LEGACY_GOOGLE_DRIVE_CONFIG_DIR
                and config.get("plugin") == LEGACY_GOOGLE_DRIVE_KEY
            ):
                config["plugin"] = GOOGLE_DRIVE_KEY

            if config.get("plugin") != GOOGLE_DRIVE_KEY:
                raise HTTPException(
                    500,
                    "Google Drive configuration must use the googledrive plugin",
                )

            return config

    return {}


def google_drive_documentation_path():
    return GOOGLE_DRIVE_CONFIG_DIR / "README.md"


def google_drive_has_documentation() -> bool:
    return google_drive_documentation_path().is_file()


async def read_google_drive_documentation() -> str | None:
    path = google_drive_documentation_path()

    if not path.is_file():
        return None

    async with aiofiles.open(path) as f:
        content = await f.read()

    return content if content.strip() else None


def field_is_secret(field: dict) -> bool:
    return bool(field.get("secret") or field.get("type") == "secret")


async def read_connection_credentials(slug: str) -> dict[str, str]:
    config = await read_sync_config(slug)
    return connection_fields(config) if config else {}


def visible_credentials(
    config: dict,
    credentials: dict[str, str],
) -> dict[str, str]:
    fields_by_key = {field["key"]: field for field in config.get("fields", [])}

    return {
        key: value
        for key, value in credentials.items()
        if not field_is_secret(fields_by_key.get(key, {}))
    }


def saved_secret_fields(config: dict, credentials: dict[str, str]) -> list[str]:
    fields_by_key = {field["key"]: field for field in config.get("fields", [])}

    return [
        key
        for key, value in credentials.items()
        if value and field_is_secret(fields_by_key.get(key, {}))
    ]


def merge_update_credentials(
    config: dict,
    submitted: dict[str, str],
    existing: dict[str, str],
) -> dict[str, str]:
    merged = {}

    for field in config.get("fields", []):
        key = field["key"]
        value = str(submitted.get(key) or "").strip()

        if value:
            merged[key] = submitted[key]
        elif field_is_secret(field) and existing.get(key):
            merged[key] = existing[key]
        elif key in submitted:
            merged[key] = submitted[key]
        elif existing.get(key):
            merged[key] = existing[key]

    return merged


def validate_connection_fields(
    config: dict,
    credentials: dict[str, str],
) -> None:
    missing = []

    for field in config.get("fields", []):
        key = field["key"]
        value = str(credentials.get(key) or field.get("default") or "").strip()

        if field.get("required") and not value:
            missing.append(field.get("label") or key)

    if missing:
        raise HTTPException(400, f"Missing required fields: {', '.join(missing)}")

    fields_by_key = {field["key"]: field for field in config.get("fields", [])}

    def has_value(key: str) -> bool:
        field = fields_by_key.get(key, {})
        return bool(str(credentials.get(key) or field.get("default") or "").strip())

    def field_label(key: str) -> str:
        return str(fields_by_key.get(key, {}).get("label") or key)

    credential_groups = config.get("credential_groups") or []

    if not credential_groups:
        return

    impersonated_email = str(credentials.get("impersonated_user_email") or "").strip()

    if (
        has_value("credentials")
        and impersonated_email.lower().endswith("@gmail.com")
        and not has_value("token_path")
    ):
        raise HTTPException(
            400,
            (
                "Google service account mode can use the service account "
                "client_email directly, or a Google Workspace/Cloud Identity user "
                "for domain-wide delegation. Consumer @gmail.com accounts cannot "
                "be impersonated; use OAuth token path for personal Google accounts."
            ),
        )

    for group in credential_groups:
        keys = group.get("keys") or []

        if keys and all(has_value(key) for key in keys):
            return

    options = ", ".join(
        (
            f"{group.get('label') or ' + '.join(group.get('keys') or [])}"
            f" (missing: {_missing_group_fields(group, has_value, field_label)})"
        )
        for group in credential_groups
    )
    raise HTTPException(400, f"Complete one authentication option: {options}")


def _missing_group_fields(group: dict, has_value, field_label) -> str:
    return ", ".join(
        field_label(key) for key in group.get("keys", []) if not has_value(key)
    )


def normalize_credentials(
    config: dict,
    credentials: dict[str, str],
) -> dict[str, str]:
    normalized = {}

    for field in config.get("fields", []):
        key = field["key"]

        if key in credentials:
            normalized[key] = str(credentials[key]).strip()

    return normalized
