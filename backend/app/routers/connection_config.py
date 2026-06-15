from typing import Any

import httpx
import aiofiles

from fastapi import HTTPException

from app.routers.constants import CONNECTORS_DIR, STEAMPIPE_CONFIG_DIR
from app.utils import escape_hcl, load_yaml_file, parse_spc_credentials


async def load_connectors() -> dict[str, dict[str, Any]]:
    connectors = {}

    if CONNECTORS_DIR.exists():
        connector_files = sorted(
            [
                *(CONNECTORS_DIR.glob("*/connection.yaml")),
                *(CONNECTORS_DIR.glob("*/connection.yml")),
            ]
        )

        for connection_file in connector_files:
            data = await load_yaml_file(connection_file)

            if data:
                connectors[connection_file.parent.name] = data

    return connectors


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
    connector: dict,
    credentials: dict[str, str],
) -> dict[str, str]:
    fields_by_key = {field["key"]: field for field in connector.get("fields", [])}

    return {
        key: value
        for key, value in credentials.items()
        if not field_is_secret(fields_by_key.get(key, {}))
    }


def saved_secret_fields(connector: dict, credentials: dict[str, str]) -> list[str]:
    fields_by_key = {field["key"]: field for field in connector.get("fields", [])}

    return [
        key
        for key, value in credentials.items()
        if value and field_is_secret(fields_by_key.get(key, {}))
    ]


def merge_update_credentials(
    connector: dict,
    submitted: dict[str, str],
    existing: dict[str, str],
) -> dict[str, str]:
    merged = {}

    for field in connector.get("fields", []):
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
    connector: dict,
) -> str:
    lines = [f'connection "{slug}" {{', f'  plugin = "{plugin}"']

    for field in connector.get("fields", []):
        key = field["key"]
        value = str(credentials.get(key) or field.get("default") or "").strip()

        if not value:
            continue

        hcl_key = field.get("hcl_key") or key
        lines.append(f"  {hcl_key} = {render_hcl_value(value, field)}")

    lines.append("}")

    return "\n".join(lines) + "\n"


def connection_plugin_spec(connector: dict, fallback_plugin: str) -> str:
    plugin = str(connector.get("plugin") or fallback_plugin).strip()
    version = str(connector.get("plugin_version") or "").strip().lstrip("v")

    if not plugin or "@" in plugin or not version:
        return plugin

    return f"{plugin}@{version}"


def validate_connection_fields(
    connector: dict,
    credentials: dict[str, str],
) -> None:
    missing = []

    for field in connector.get("fields", []):
        key = field["key"]
        value = str(credentials.get(key) or field.get("default") or "").strip()

        if field.get("required") and not value:
            missing.append(field.get("label") or key)

    if missing:
        raise HTTPException(400, f"Missing required fields: {', '.join(missing)}")

    fields_by_key = {field["key"]: field for field in connector.get("fields", [])}

    def has_value(key: str) -> bool:
        field = fields_by_key.get(key, {})
        return bool(str(credentials.get(key) or field.get("default") or "").strip())

    def field_label(key: str) -> str:
        return str(fields_by_key.get(key, {}).get("label") or key)

    credential_groups = connector.get("credential_groups") or []

    if not credential_groups:
        return

    impersonated_email = str(credentials.get("impersonated_user_email") or "").strip()

    if (
        connector.get("plugin") == "googlesheets"
        and has_value("credentials")
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


def _missing_group_fields(group: dict, has_value: Any, field_label: Any) -> str:
    return ", ".join(
        field_label(key) for key in group.get("keys", []) if not has_value(key)
    )


def normalize_credentials(
    connector: dict,
    credentials: dict[str, str],
) -> dict[str, str]:
    normalized = {}

    for field in connector.get("fields", []):
        key = field["key"]

        if key in credentials:
            normalized[key] = str(credentials[key]).strip()

    return normalized


def provider_error_detail(
    resp: httpx.Response,
    test_req: dict | None = None,
) -> str:
    detail = ""

    try:
        payload = resp.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        detail = str(
            payload.get("message")
            or payload.get("error")
            or payload.get("status")
            or ""
        )
        errors = payload.get("errors")

        if not detail and isinstance(errors, list) and errors:
            first_error = errors[0]

            if isinstance(first_error, dict):
                detail = str(
                    first_error.get("message") or first_error.get("error") or ""
                )
            else:
                detail = str(first_error)
    else:
        detail = resp.text.strip()

    required_scope = (test_req or {}).get("required_scope")

    if resp.status_code == 403 and required_scope:
        detail = f"Missing required scope `{required_scope}`. {detail}"

    suffix = f": {detail[:300]}" if detail else ""

    return f"Invalid credentials - provider returned HTTP {resp.status_code}{suffix}"


async def validate_provider_credentials(
    connector: dict,
    credentials: dict[str, str],
) -> None:
    test_req = connector.get("test_request")

    if not test_req:
        return

    try:
        auth_value = test_req["auth_header"].format(**credentials)
    except KeyError as exc:
        raise HTTPException(400, f"Missing required field: {exc.args[0]}") from exc

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                test_req["url"],
                headers={"Authorization": auth_value},
                timeout=10,
            )
    except Exception as exc:
        raise HTTPException(
            422, f"Could not reach the provider to validate credentials: {exc}"
        ) from exc

    if resp.status_code != 200:
        raise HTTPException(422, provider_error_detail(resp, test_req))
