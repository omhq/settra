import aiofiles

from fastapi import HTTPException

from app.common.config import (
    GOOGLE_DRIVE_CONFIG_DIR,
    GOOGLE_DRIVE_KEY,
)
from app.sync.config import connection_fields, read_sync_config
from app.utils import load_yaml_file


async def load_google_drive_config() -> dict:
    """Load the Google Drive tabular source configuration."""

    for name in ("connection.yaml", "connection.yml"):
        path = GOOGLE_DRIVE_CONFIG_DIR / name

        if path.is_file():
            config = await load_yaml_file(path) or {}

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


async def read_connection_credentials(slug: str) -> dict[str, str | list[str]]:
    config = await read_sync_config(slug)
    return connection_fields(config) if config else {}


def validate_connection_fields(
    config: dict,
    credentials: dict[str, str | list[str]],
) -> None:
    missing = []

    for field in config.get("fields", []):
        key = field["key"]
        value = credentials.get(key, field.get("default") or "")

        if field.get("required") and not _has_credential_value(value):
            missing.append(field.get("label") or key)

    if missing:
        raise HTTPException(400, f"Missing required fields: {', '.join(missing)}")


def normalize_credentials(
    config: dict,
    credentials: dict[str, str | list[str]],
) -> dict[str, str | list[str]]:
    normalized: dict[str, str | list[str]] = {}

    for field in config.get("fields", []):
        key = field["key"]

        if key in credentials:
            value = credentials[key]

            if key == "sheets" and isinstance(value, list):
                normalized[key] = [
                    str(item).strip() for item in value if str(item).strip()
                ] or ["*"]
            elif isinstance(value, list):
                raise HTTPException(
                    400,
                    f"{field.get('label') or key} must be text",
                )
            else:
                normalized[key] = str(value).strip()

    return normalized


def _has_credential_value(value: object) -> bool:
    if isinstance(value, list):
        return any(str(item).strip() for item in value)

    return bool(str(value or "").strip())
