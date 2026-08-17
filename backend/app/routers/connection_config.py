import aiofiles

from fastapi import HTTPException

from app.routers.constants import (
    GOOGLE_SHEETS_CONFIG_DIR,
    GOOGLE_SHEETS_KEY,
    STEAMPIPE_CONFIG_DIR,
)
from app.utils import escape_hcl, load_yaml_file, parse_spc_credentials


async def load_google_sheets_config() -> dict:
    """Load the only supported source configuration."""

    for name in ("connection.yaml", "connection.yml"):
        path = GOOGLE_SHEETS_CONFIG_DIR / name

        if path.is_file():
            config = await load_yaml_file(path) or {}

            if config.get("plugin") != GOOGLE_SHEETS_KEY:
                raise HTTPException(
                    500,
                    "Google Sheets configuration must use the googlesheets plugin",
                )

            return config

    return {}


def google_sheets_documentation_path():
    return GOOGLE_SHEETS_CONFIG_DIR / "README.md"


def google_sheets_has_documentation() -> bool:
    return google_sheets_documentation_path().is_file()


async def read_google_sheets_documentation() -> str | None:
    path = google_sheets_documentation_path()

    if not path.is_file():
        return None

    async with aiofiles.open(path) as f:
        content = await f.read()

    return content if content.strip() else None


def quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def field_is_secret(field: dict) -> bool:
    return bool(field.get("secret") or field.get("type") == "secret")


async def read_connection_credentials(slug: str) -> dict[str, str]:
    spc_path = STEAMPIPE_CONFIG_DIR / f"{slug}.spc"

    if not spc_path.exists():
        return {}

    async with aiofiles.open(spc_path) as f:
        return parse_spc_credentials(await f.read())


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


def render_hcl_value(value: str, field: dict) -> str:
    hcl_type = field.get("hcl_type") or "string"

    if hcl_type == "string_list":
        items = [
            item.strip()
            for chunk in value.splitlines()
            for item in chunk.split(",")
            if item.strip()
        ]
        return "[" + ", ".join(f'"{escape_hcl(item)}"' for item in items) + "]"

    return f'"{escape_hcl(value)}"'


def render_connection_hcl(
    slug: str,
    plugin: str,
    credentials: dict[str, str],
    config: dict,
) -> str:
    lines = [f'connection "{slug}" {{', f'  plugin = "{plugin}"']

    for field in config.get("fields", []):
        key = field["key"]
        value = str(credentials.get(key) or field.get("default") or "").strip()

        if not value:
            continue

        hcl_key = field.get("hcl_key") or key
        lines.append(f"  {hcl_key} = {render_hcl_value(value, field)}")

    lines.append("}")

    return "\n".join(lines) + "\n"


def google_sheets_plugin_spec(config: dict) -> str:
    plugin = str(config.get("plugin") or "googlesheets").strip()
    version = str(config.get("plugin_version") or "").strip().lstrip("v")

    if not plugin or "@" in plugin or not version:
        return plugin

    return f"{plugin}@{version}"


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
                "Google Sheets service account mode can use the service account "
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
