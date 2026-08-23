from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import aiofiles
import yaml

from fastapi import HTTPException

from app.routers.constants import CONNECTION_CONFIG_DIR
from app.sync.inspection import normalize_delimiter, normalize_source_format

SUPPORTED_DATA_TYPES = {
    "binary",
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
    file_id: str | None = None,
    file_name: str = "",
    mime_type: str = "",
    sheets: str | list[str] = "*",
    destination_key: str = "built_in_postgres",
    destination_type: str = "postgres",
    destination_schema: str | None = None,
    # Kept for callers and saved definitions created before Drive file support.
    spreadsheet_id: str | None = None,
) -> dict[str, Any]:
    selected_file_id = str(file_id or spreadsheet_id or "").strip()

    return {
        "version": 1,
        "source": {
            "type": "google_drive",
            "file_id": selected_file_id,
            **({"file_name": file_name.strip()} if file_name.strip() else {}),
            **({"mime_type": mime_type.strip()} if mime_type.strip() else {}),
            "format": "auto",
            "sheets": _sheet_patterns(sheets),
            "parsing": {
                "delimiter": "auto",
                "encoding": "auto",
                "header_row": "auto",
            },
        },
        "destination": {
            "key": destination_key,
            "type": destination_type,
            "schema": destination_schema or slug,
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


async def read_sync_config(
    slug: str,
    *,
    expected_destination_key: str | None = None,
    expected_destination_schema: str | None = None,
) -> dict[str, Any]:
    path = config_path(slug)

    if not path.is_file():
        return {}

    async with aiofiles.open(path) as handle:
        content = await handle.read()

    return validate_sync_config(
        content,
        expected_destination_key=expected_destination_key,
        expected_destination_schema=expected_destination_schema,
    )


async def read_sync_config_text(slug: str) -> str:
    path = config_path(slug)

    if not path.is_file():
        return ""

    async with aiofiles.open(path) as handle:
        return await handle.read()


async def write_sync_config(
    slug: str,
    config: dict[str, Any],
    *,
    expected_destination_key: str | None = None,
    expected_destination_schema: str | None = None,
) -> Path:
    validated = validate_sync_config(
        config,
        expected_destination_key=expected_destination_key,
        expected_destination_schema=expected_destination_schema or slug,
    )
    CONNECTION_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = config_path(slug)
    temp_path = path.with_suffix(".yaml.tmp")
    content = yaml.safe_dump(validated, sort_keys=False, allow_unicode=True)

    async with aiofiles.open(temp_path, "w") as handle:
        await handle.write(content)

    temp_path.chmod(0o600)
    temp_path.replace(path)
    return path


async def write_sync_config_text(
    slug: str,
    content: str,
    *,
    expected_destination_key: str | None = None,
    expected_destination_schema: str | None = None,
) -> dict[str, Any]:
    validated = validate_sync_config(
        content,
        expected_destination_key=expected_destination_key,
        expected_destination_schema=expected_destination_schema or slug,
    )
    await write_sync_config(
        slug,
        validated,
        expected_destination_key=expected_destination_key,
        expected_destination_schema=expected_destination_schema,
    )
    return validated


def validate_sync_config(
    value: str | dict[str, Any],
    *,
    expected_slug: str | None = None,
    expected_destination_key: str | None = None,
    expected_destination_schema: str | None = None,
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

    source_type = str(source.get("type") or "").strip()
    legacy_google_sheet = source_type == "google_sheets"

    if source_type not in {"google_drive", "google_sheets"}:
        raise HTTPException(422, "source.type must be google_drive")

    file_id = str(source.get("file_id") or source.get("spreadsheet_id") or "").strip()

    if not file_id:
        raise HTTPException(422, "source.file_id is required")

    source["type"] = "google_drive"
    source["file_id"] = file_id
    source.pop("spreadsheet_id", None)
    source["file_name"] = str(source.get("file_name") or "").strip()
    source["mime_type"] = str(source.get("mime_type") or "").strip()

    try:
        source["format"] = normalize_source_format(
            source.get("format") or ("google_sheets" if legacy_google_sheet else "auto")
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    source["sheets"] = _sheet_patterns(source.get("sheets", ["*"]))
    source["parsing"] = _validate_parsing(
        source.get("parsing"),
        legacy_google_sheet=legacy_google_sheet,
    )

    destination["key"] = str(destination.get("key") or "built_in_postgres").strip()

    if not destination["key"]:
        raise HTTPException(422, "destination.key is required")

    if expected_destination_key and destination["key"] != expected_destination_key:
        raise HTTPException(
            422,
            f"destination.key must remain {expected_destination_key!r} for this pipe",
        )

    if destination.get("type") != "postgres":
        raise HTTPException(422, "destination.type must be postgres")

    destination_schema = str(destination.get("schema") or "").strip()

    locked_destination_schema = expected_destination_schema or expected_slug

    if locked_destination_schema and destination_schema != locked_destination_schema:
        raise HTTPException(
            422,
            "destination.schema must remain "
            f"{locked_destination_schema!r} for this pipe",
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
        "file_id": str(source.get("file_id") or source.get("spreadsheet_id") or ""),
        "file_name": str(source.get("file_name") or ""),
        "mime_type": str(source.get("mime_type") or ""),
        "sheets": ", ".join(str(item) for item in sheets or ["*"]),
    }


def table_rule(config: dict[str, Any], sheet_title: str) -> dict[str, Any]:
    schema_config = config.get("schema")
    tables = schema_config.get("tables") if isinstance(schema_config, dict) else {}
    rule = tables.get(sheet_title) if isinstance(tables, dict) else None
    return rule if isinstance(rule, dict) else {}


def apply_detected_source_config(
    config: dict[str, Any],
    detected: dict[str, Any],
) -> dict[str, Any]:
    """Persist inferred values only where the YAML still requests auto detection."""

    updated = deepcopy(config)
    source = updated["source"]
    source["file_name"] = str(
        detected.get("file_name") or source.get("file_name") or ""
    )
    source["mime_type"] = str(
        detected.get("mime_type") or source.get("mime_type") or ""
    )

    if source.get("format") == "auto" and detected.get("format"):
        source["format"] = detected["format"]

    parsing = source.setdefault("parsing", {})
    detected_parsing = detected.get("parsing")

    if isinstance(detected_parsing, dict):
        for key in ("delimiter", "encoding", "header_row"):
            if parsing.get(key, "auto") == "auto" and key in detected_parsing:
                parsing[key] = detected_parsing[key]

    header_rows = detected.get("header_rows")

    if isinstance(header_rows, dict) and header_rows:
        distinct = {int(value) for value in header_rows.values()}

        if parsing.get("header_row", "auto") == "auto" and len(distinct) == 1:
            parsing["header_row"] = distinct.pop()
        elif len(distinct) > 1:
            tables = updated.setdefault("schema", {}).setdefault("tables", {})

            for source_name, header_row in header_rows.items():
                rule = tables.setdefault(str(source_name), {})

                if rule.get("header_row", "auto") == "auto":
                    rule["header_row"] = int(header_row)

    return validate_sync_config(updated)


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


def _validate_parsing(value: Any, *, legacy_google_sheet: bool) -> dict[str, Any]:
    if value is None:
        parsing: dict[str, Any] = {}
    elif isinstance(value, dict):
        parsing = deepcopy(value)
    else:
        raise HTTPException(422, "source.parsing must be an object")

    unknown = set(parsing) - {"delimiter", "encoding", "header_row"}

    if unknown:
        raise HTTPException(
            422,
            "Unsupported source.parsing fields: " + ", ".join(sorted(unknown)),
        )

    try:
        delimiter = normalize_delimiter(parsing.get("delimiter", "auto"))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    encoding = str(parsing.get("encoding") or "auto").strip()

    if not encoding:
        raise HTTPException(422, "source.parsing.encoding cannot be empty")

    default_header: str | int = 1 if legacy_google_sheet else "auto"
    header_row = _validate_header_row(
        parsing.get("header_row", default_header),
        path="source.parsing.header_row",
    )
    return {
        "delimiter": "tab" if delimiter == "\t" else delimiter,
        "encoding": encoding,
        "header_row": header_row,
    }


def _validate_header_row(value: Any, *, path: str) -> str | int:
    if isinstance(value, str) and value.strip().lower() == "auto":
        return "auto"
    if isinstance(value, bool):
        raise HTTPException(422, f"{path} must be auto or a positive integer")

    try:
        resolved = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            422,
            f"{path} must be auto or a positive integer",
        ) from exc

    if resolved < 1:
        raise HTTPException(422, f"{path} must be auto or a positive integer")

    return resolved


def _validate_schema_rules(tables: dict[str, Any]) -> None:
    for sheet_name, raw_rule in tables.items():
        if not isinstance(raw_rule, dict):
            raise HTTPException(422, f"schema.tables.{sheet_name} must be an object")

        if "enabled" in raw_rule and not isinstance(raw_rule["enabled"], bool):
            raise HTTPException(
                422,
                f"schema.tables.{sheet_name}.enabled must be a boolean",
            )

        if "header_row" in raw_rule:
            raw_rule["header_row"] = _validate_header_row(
                raw_rule["header_row"],
                path=f"schema.tables.{sheet_name}.header_row",
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
