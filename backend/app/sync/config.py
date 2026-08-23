from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import aiofiles
import yaml

from fastapi import HTTPException

from app.routers.constants import CONNECTION_CONFIG_DIR

SUPPORTED_DATA_TYPES = {
    "text",
    "bigint",
    "double",
    "bool",
    "timestamp",
    "date",
    "decimal",
    "json",
}


def default_sync_config(
    *,
    slug: str,
    spreadsheet_id: str,
    sheets: str | list[str] = "*",
) -> dict[str, Any]:
    return {
        "version": 1,
        "source": {
            "type": "google_sheets",
            "spreadsheet_id": spreadsheet_id.strip(),
            "sheets": _sheet_patterns(sheets),
        },
        "destination": {
            "type": "postgres",
            "schema": slug,
        },
        "load": {
            "write_disposition": "replace",
            "replace_strategy": "insert-from-staging",
            "schema_contract": {
                "tables": "evolve",
                "columns": "evolve",
                "data_type": "evolve",
            },
            "schedule": {
                "enabled": False,
                "cron": "0 * * * *",
                "timezone": "UTC",
            },
        },
        "schema": {"tables": {}},
    }


def config_path(slug: str) -> Path:
    candidate = CONNECTION_CONFIG_DIR / f"{slug}.yaml"
    resolved = candidate.resolve()
    root = CONNECTION_CONFIG_DIR.resolve()

    if resolved.parent != root:
        raise HTTPException(400, "Invalid connection slug")

    return candidate


async def read_sync_config(slug: str) -> dict[str, Any]:
    path = config_path(slug)

    if not path.is_file():
        return {}

    async with aiofiles.open(path) as handle:
        content = await handle.read()

    return validate_sync_config(content, expected_slug=slug)


async def read_sync_config_text(slug: str) -> str:
    path = config_path(slug)

    if not path.is_file():
        return ""

    async with aiofiles.open(path) as handle:
        return await handle.read()


async def write_sync_config(slug: str, config: dict[str, Any]) -> Path:
    validated = validate_sync_config(config, expected_slug=slug)
    CONNECTION_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = config_path(slug)
    temp_path = path.with_suffix(".yaml.tmp")
    content = yaml.safe_dump(validated, sort_keys=False, allow_unicode=True)

    async with aiofiles.open(temp_path, "w") as handle:
        await handle.write(content)

    temp_path.chmod(0o600)
    temp_path.replace(path)
    return path


async def write_sync_config_text(slug: str, content: str) -> dict[str, Any]:
    validated = validate_sync_config(content, expected_slug=slug)
    await write_sync_config(slug, validated)
    return validated


def validate_sync_config(
    value: str | dict[str, Any],
    *,
    expected_slug: str | None = None,
) -> dict[str, Any]:
    try:
        parsed = yaml.safe_load(value) if isinstance(value, str) else deepcopy(value)
    except yaml.YAMLError as exc:
        raise HTTPException(422, f"Invalid sync YAML: {exc}") from exc

    if not isinstance(parsed, dict):
        raise HTTPException(422, "Sync YAML must contain an object")

    if parsed.get("version", 1) != 1:
        raise HTTPException(422, "Only sync configuration version 1 is supported")

    source = _mapping(parsed, "source")
    destination = _mapping(parsed, "destination")
    load = _mapping(parsed, "load")
    schema_config = parsed.setdefault("schema", {"tables": {}})

    if source.get("type") != "google_sheets":
        raise HTTPException(422, "source.type must be google_sheets")

    spreadsheet_id = str(source.get("spreadsheet_id") or "").strip()

    if not spreadsheet_id:
        raise HTTPException(422, "source.spreadsheet_id is required")

    source["spreadsheet_id"] = spreadsheet_id
    source["sheets"] = _sheet_patterns(source.get("sheets", ["*"]))

    if destination.get("type") != "postgres":
        raise HTTPException(422, "destination.type must be postgres")

    destination_schema = str(destination.get("schema") or "").strip()

    if expected_slug and destination_schema != expected_slug:
        raise HTTPException(
            422,
            f"destination.schema must remain {expected_slug!r} for this connection",
        )

    if not destination_schema:
        raise HTTPException(422, "destination.schema is required")

    if load.get("write_disposition", "replace") != "replace":
        raise HTTPException(422, "load.write_disposition must be replace")

    if load.get("replace_strategy", "insert-from-staging") != "insert-from-staging":
        raise HTTPException(
            422,
            "load.replace_strategy must be insert-from-staging",
        )

    contract = load.setdefault(
        "schema_contract",
        {"tables": "evolve", "columns": "evolve", "data_type": "evolve"},
    )

    if not isinstance(contract, dict):
        raise HTTPException(422, "load.schema_contract must be an object")

    contract_modes = {
        "tables": {"evolve", "freeze", "discard_row"},
        "columns": {"evolve", "freeze", "discard_row"},
        "data_type": {"evolve", "freeze", "discard_row", "discard_value"},
    }

    for key in ("tables", "columns", "data_type"):
        mode = str(contract.get(key) or "evolve")

        if mode not in contract_modes[key]:
            raise HTTPException(
                422,
                f"load.schema_contract.{key} must be one of: "
                + ", ".join(sorted(contract_modes[key])),
            )

        contract[key] = mode

    schedule = load.setdefault(
        "schedule",
        {"enabled": False, "cron": "0 * * * *", "timezone": "UTC"},
    )

    if not isinstance(schedule, dict):
        raise HTTPException(422, "load.schedule must be an object")

    schedule_enabled = schedule.get("enabled", False)

    if not isinstance(schedule_enabled, bool):
        raise HTTPException(422, "load.schedule.enabled must be a boolean")

    schedule["enabled"] = schedule_enabled
    schedule["cron"] = str(schedule.get("cron") or "0 * * * *").strip()
    schedule["timezone"] = str(schedule.get("timezone") or "UTC").strip()

    try:
        from croniter import croniter

        valid_cron = croniter.is_valid(schedule["cron"])
    except ImportError:
        valid_cron = len(schedule["cron"].split()) in {5, 6}

    if not valid_cron:
        raise HTTPException(422, "load.schedule.cron is not a valid cron expression")

    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(schedule["timezone"])
    except Exception as exc:
        raise HTTPException(422, "load.schedule.timezone is not valid") from exc

    if not isinstance(schema_config, dict):
        raise HTTPException(422, "schema must be an object")

    tables = schema_config.setdefault("tables", {})

    if not isinstance(tables, dict):
        raise HTTPException(422, "schema.tables must be an object")

    _validate_schema_rules(tables)
    parsed["version"] = 1
    parsed["source"] = source
    parsed["destination"] = destination
    parsed["load"] = load
    parsed["schema"] = schema_config
    return parsed


def connection_fields(config: dict[str, Any]) -> dict[str, str]:
    source = config.get("source") if isinstance(config.get("source"), dict) else {}
    sheets = source.get("sheets") if isinstance(source, dict) else []

    return {
        "spreadsheet_id": str(source.get("spreadsheet_id") or ""),
        "sheets": ", ".join(str(item) for item in sheets or ["*"]),
    }


def table_rule(config: dict[str, Any], sheet_title: str) -> dict[str, Any]:
    schema_config = config.get("schema")
    tables = schema_config.get("tables") if isinstance(schema_config, dict) else {}
    rule = tables.get(sheet_title) if isinstance(tables, dict) else None
    return rule if isinstance(rule, dict) else {}


def _mapping(parsed: dict[str, Any], key: str) -> dict[str, Any]:
    value = parsed.get(key)

    if not isinstance(value, dict):
        raise HTTPException(422, f"{key} must be an object")

    return value


def _sheet_patterns(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = [item for line in value.splitlines() for item in line.split(",")]
    elif isinstance(value, list):
        raw = value
    else:
        raise HTTPException(422, "source.sheets must be a string or list")

    patterns = [str(item).strip() for item in raw if str(item).strip()]
    return patterns or ["*"]


def _validate_schema_rules(tables: dict[str, Any]) -> None:
    for sheet_name, raw_rule in tables.items():
        if not isinstance(raw_rule, dict):
            raise HTTPException(422, f"schema.tables.{sheet_name} must be an object")

        if "enabled" in raw_rule and not isinstance(raw_rule["enabled"], bool):
            raise HTTPException(
                422,
                f"schema.tables.{sheet_name}.enabled must be a boolean",
            )

        columns = raw_rule.get("columns", {})

        if not isinstance(columns, dict):
            raise HTTPException(
                422,
                f"schema.tables.{sheet_name}.columns must be an object",
            )

        for column_name, raw_column in columns.items():
            if not isinstance(raw_column, dict):
                raise HTTPException(
                    422,
                    f"schema.tables.{sheet_name}.columns.{column_name} must be an object",
                )

            for boolean_key in ("enabled", "nullable"):
                if boolean_key in raw_column and not isinstance(
                    raw_column[boolean_key],
                    bool,
                ):
                    raise HTTPException(
                        422,
                        f"schema.tables.{sheet_name}.columns.{column_name}."
                        f"{boolean_key} must be a boolean",
                    )

            data_type = raw_column.get("data_type")

            if data_type and data_type not in SUPPORTED_DATA_TYPES:
                allowed = ", ".join(sorted(SUPPORTED_DATA_TYPES))
                raise HTTPException(
                    422,
                    f"Unsupported data_type {data_type!r}; choose one of: {allowed}",
                )
