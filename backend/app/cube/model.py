import os
import time

from typing import Any
from pathlib import Path

import yaml

from fastapi import HTTPException

from app.cube.client import load_cube_meta
from app.cube.config import CUBE_MODEL_DIR
from app.db import db_connection
from app.routers.constants import (
    CONNECTION_CONFIG_DIR,
    GOOGLE_SHEETS_KEY,
)

GENERATED_OVERLAY_PREFIX = "overlays/generated/"
GENERATED_CONNECTION_PREFIX = "generated/connections/"


async def sync_cube_model() -> dict[str, Any]:
    """Refresh generated Cube model files from saved connections."""

    CUBE_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    removed_defaults = _remove_legacy_default_models()
    connection_models = await sync_connection_models()

    return {
        "ok": True,
        "model_dir": str(CUBE_MODEL_DIR),
        "removed_defaults": removed_defaults,
        "connection_models": connection_models,
        "files": list_model_files(),
    }


async def cube_model_summary() -> dict[str, Any]:
    files = list_model_files()
    cube_status: dict[str, Any] = {
        "connected": False,
        "cube_count": 0,
        "error": None,
        "meta": None,
    }

    try:
        meta = await load_cube_meta()
        cubes = meta.get("cubes") if isinstance(meta, dict) else []
        cube_status = {
            "connected": True,
            "cube_count": len(cubes) if isinstance(cubes, list) else 0,
            "error": None,
            "meta": meta,
        }
    except Exception as exc:
        cube_status["error"] = f"{exc.__class__.__name__}: {exc}"

    return {
        "model_dir": str(CUBE_MODEL_DIR),
        "files": files,
        "source_definitions": {
            "cubes": source_definition_index(),
        },
        "cube": cube_status,
    }


async def cube_meta() -> dict[str, Any]:
    return await load_cube_meta()


def list_model_files() -> list[dict[str, Any]]:
    CUBE_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []

    for path in sorted(CUBE_MODEL_DIR.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".yml", ".yaml"}:
            continue

        files.append(_model_file_summary(path))

    return files


def list_semantic_overlay_files() -> list[dict[str, Any]]:
    """List hand-authored and generated semantic overlay model files."""

    return [
        file
        for file in list_model_files()
        if file.get("source_type") in {"overlay", "generated_overlay"}
    ]


def _remove_legacy_default_models() -> list[str]:
    """Remove root-level Google Sheets templates left by older installations."""

    removed: list[str] = []

    for name in (f"{GOOGLE_SHEETS_KEY}.yaml", f"{GOOGLE_SHEETS_KEY}.yml"):
        path = CUBE_MODEL_DIR / name

        if not path.is_file():
            continue

        removed.append(_relative_model_path(path))
        path.unlink()

    return removed


async def sync_connection_models() -> dict[str, Any]:
    """Generate active Cube model files for each saved connection."""
    CUBE_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    target_dir = CUBE_MODEL_DIR / GENERATED_CONNECTION_PREFIX

    target_dir.mkdir(parents=True, exist_ok=True)

    connections = await _saved_connections()
    written: list[str] = []
    skipped: list[dict[str, str]] = []
    expected_paths: set[Path] = set()

    for connection in connections:
        manifest_path = CONNECTION_CONFIG_DIR / f"{connection['slug']}.manifest.yaml"

        if not manifest_path.is_file():
            skipped.append(
                {
                    "slug": connection["slug"],
                    "plugin": GOOGLE_SHEETS_KEY,
                    "reason": "no successful PostgreSQL sync manifest",
                }
            )
            continue

        model = render_connection_manifest_model(manifest_path, connection)
        target = target_dir / f"{connection['slug']}.yaml"
        target.write_text(model, encoding="utf-8")
        expected_paths.add(target.resolve())
        written.append(_relative_model_path(target))

    removed: list[str] = []

    for stale in sorted(target_dir.glob("*.y*ml")):
        if stale.resolve() in expected_paths:
            continue

        removed.append(_relative_model_path(stale))
        stale.unlink()

    return {
        "prefix": GENERATED_CONNECTION_PREFIX,
        "written": written,
        "removed": removed,
        "skipped": skipped,
    }


def render_connection_manifest_model(
    manifest_path: Path,
    connection: dict[str, Any],
) -> str:
    manifest = _read_model_yaml(manifest_path)
    tables = manifest.get("tables")

    if not isinstance(tables, list):
        tables = []

    cubes = []

    for table in tables:
        if not isinstance(table, dict) or not table.get("name"):
            continue

        table_name = str(table["name"])
        cube_name = f"{connection['slug']}_{table_name}"
        dimensions = []
        column_names = {
            str(column.get("name"))
            for column in table.get("columns") or []
            if isinstance(column, dict) and column.get("name")
        }
        count_measure_name = "row_count"

        while count_measure_name in column_names:
            count_measure_name = f"settra_{count_measure_name}"

        for column in table.get("columns") or []:
            if not isinstance(column, dict) or not column.get("name"):
                continue

            column_name = str(column["name"])
            dimension = {
                "name": column_name,
                "title": _human_title(column_name),
                "sql": f'"{_escape_sql_identifier(column_name)}"',
                "type": _cube_dimension_type(str(column.get("type") or "text")),
            }

            column_description = str(column.get("description") or "").strip()

            if column_description:
                dimension["description"] = column_description

            dimensions.append(dimension)

        cube: dict[str, Any] = {
            "name": cube_name,
            "sql_table": (
                f'"{_escape_sql_identifier(str(connection["slug"]))}".'
                f'"{_escape_sql_identifier(table_name)}"'
            ),
            "title": f"{_human_title(table_name)} ({connection['name']})",
            "measures": [
                {
                    "name": count_measure_name,
                    "title": "Rows",
                    "description": "Number of rows in the latest durable sheet snapshot.",
                    "type": "count",
                }
            ],
            "dimensions": dimensions,
            "meta": {
                "settra": {
                    "source_type": "generated_connection",
                    "connection_id": connection["id"],
                    "connection_name": connection["name"],
                    "connection_slug": connection["slug"],
                    "source_key": GOOGLE_SHEETS_KEY,
                    "source_sheet": table.get("source_sheet") or table_name,
                    "storage": "postgres",
                    "sync_manifest_generated_at": manifest.get("generated_at"),
                }
            },
        }
        table_description = str(table.get("description") or "").strip()

        if table_description:
            cube["description"] = table_description

        cubes.append(cube)

    return yaml.safe_dump({"cubes": cubes}, sort_keys=False, allow_unicode=True)


def _cube_dimension_type(postgres_type: str) -> str:
    lowered = postgres_type.lower()

    if "timestamp" in lowered or lowered == "date":
        return "time"
    if lowered in {
        "smallint",
        "integer",
        "bigint",
        "decimal",
        "numeric",
        "real",
        "double precision",
    }:
        return "number"
    if lowered == "boolean":
        return "boolean"

    return "string"


def _human_title(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("_", " ").split())


async def _saved_connections() -> list[dict[str, Any]]:
    async with db_connection() as db:
        rows = await db.fetch("""
            SELECT id, name, slug, plugin, status, created_at
            FROM connections
            WHERE plugin = $1
            ORDER BY created_at ASC
            """, GOOGLE_SHEETS_KEY)

    return [dict(row) for row in rows]


def _escape_sql_identifier(value: str) -> str:
    return value.replace('"', '""')


def source_definition_index() -> dict[str, Any]:
    CUBE_MODEL_DIR.mkdir(parents=True, exist_ok=True)

    definitions: dict[str, Any] = {}

    for path in sorted(CUBE_MODEL_DIR.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".yml", ".yaml"}:
            continue

        parsed = _read_model_yaml(path)

        for key in ("cubes", "views"):
            items = parsed.get(key)

            if not isinstance(items, list):
                continue

            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                    continue

                definitions[item["name"]] = _source_definition(path, item)

    return definitions


def authored_definition_index() -> dict[str, dict[str, Any]]:
    """Index exact authored cube/view definitions with their source provenance."""

    CUBE_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    definitions: dict[str, dict[str, Any]] = {}

    for path in sorted(CUBE_MODEL_DIR.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".yml", ".yaml"}:
            continue

        parsed = _read_model_yaml(path)

        for key in ("cubes", "views"):
            items = parsed.get(key)

            if not isinstance(items, list):
                continue

            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                    continue

                relative_path = _relative_model_path(path)
                definitions[item["name"]] = {
                    "path": relative_path,
                    "source_type": _model_source_type(relative_path),
                    "definition": item,
                }

    return definitions


def read_model_file(file_path: str) -> dict[str, Any]:
    path = _safe_model_path(file_path)

    if not path.is_file():
        raise HTTPException(404, "Cube model file not found")

    return {
        **_model_file_summary(path),
        "content": path.read_text(encoding="utf-8"),
    }


def read_semantic_overlay_file(file_path: str) -> dict[str, Any]:
    """Read a semantic overlay without exposing other Cube model sources."""

    file = read_model_file(file_path)

    if file.get("source_type") not in {"overlay", "generated_overlay"}:
        raise HTTPException(400, "Path is not a semantic overlay")

    return file


def save_model_file(file_path: str, content: str) -> dict[str, Any]:
    path = _safe_model_path(file_path)

    _validate_model_content(path, content)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

    return {
        "ok": True,
        "file": _model_file_summary(path),
    }


def create_model_file(file_path: str, content: str) -> dict[str, Any]:
    """Create a Cube model file and fail rather than overwrite an existing file."""

    path = _safe_model_path(file_path)

    _validate_model_content(path, content)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with path.open("x", encoding="utf-8") as file:
            file.write(content)
    except FileExistsError as exc:
        raise HTTPException(409, "Cube model file already exists") from exc

    return {
        "ok": True,
        "created": True,
        "file": _model_file_summary(path),
    }


def update_model_file(file_path: str, content: str) -> dict[str, Any]:
    """Update an existing Cube model file and return its previous content."""

    path = _safe_model_path(file_path)

    _validate_model_content(path, content)

    if not path.is_file():
        raise HTTPException(404, "Cube model file not found")

    previous_content = path.read_text(encoding="utf-8")

    path.write_text(content, encoding="utf-8")

    return {
        "ok": True,
        "updated": previous_content != content,
        "file": _model_file_summary(path),
        "previous_content": previous_content,
    }


def delete_generated_model_file(file_path: str) -> dict[str, Any]:
    path = _safe_model_path(file_path)

    if not _is_generated_overlay(path):
        raise HTTPException(400, "Only generated semantic overlay files can be deleted")

    if not path.is_file():
        raise HTTPException(404, "Generated semantic overlay file not found")

    file = _model_file_summary(path)

    path.unlink()
    return {
        "ok": True,
        "deleted": file,
    }


def _validate_model_content(path: Path, content: str) -> None:
    if path.suffix.lower() not in {".yml", ".yaml"}:
        raise HTTPException(400, "Only Cube YAML model files can be edited")

    try:
        loaded = yaml.safe_load(content) if content.strip() else {}
    except yaml.YAMLError as exc:
        raise HTTPException(422, f"Invalid YAML: {exc}") from exc

    if loaded is not None and not isinstance(loaded, dict):
        raise HTTPException(422, "Cube model YAML must contain a mapping")


def _relative_model_path(path: Path) -> str:
    return path.resolve().relative_to(CUBE_MODEL_DIR.resolve()).as_posix()


def _safe_model_path(file_path: str) -> Path:
    normalized = os.path.normpath(file_path.strip().lstrip("/"))

    if normalized == "." or normalized.startswith("../"):
        raise HTTPException(400, "Invalid Cube model file path")

    path = (CUBE_MODEL_DIR / normalized).resolve()
    model_dir = CUBE_MODEL_DIR.resolve()

    if path != model_dir and model_dir not in path.parents:
        raise HTTPException(400, "Invalid Cube model file path")

    return path


def _model_file_summary(path: Path) -> dict[str, Any]:
    stat = path.stat()
    relative_path = _relative_model_path(path)
    parse_error = None

    try:
        parsed = _read_model_yaml(path)
    except yaml.YAMLError as exc:
        parsed = {}
        parse_error = str(exc)

    cubes = parsed.get("cubes")
    views = parsed.get("views")
    cube_names = (
        [
            cube["name"]
            for cube in cubes
            if isinstance(cube, dict) and isinstance(cube.get("name"), str)
        ]
        if isinstance(cubes, list)
        else []
    )
    view_names = (
        [
            view["name"]
            for view in views
            if isinstance(view, dict) and isinstance(view.get("name"), str)
        ]
        if isinstance(views, list)
        else []
    )
    summary = {
        "path": relative_path,
        "source_type": _model_source_type(relative_path),
        "size": stat.st_size,
        "updated_at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(stat.st_mtime),
        ),
        "cube_count": len(cubes) if isinstance(cubes, list) else 0,
        "view_count": len(views) if isinstance(views, list) else 0,
        "cube_names": cube_names,
        "view_names": view_names,
    }

    if parse_error:
        summary["parse_error"] = parse_error

    return summary


def _read_model_yaml(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content) if content.strip() else {}

    return parsed if isinstance(parsed, dict) else {}


def _source_definition(path: Path, item: dict[str, Any]) -> dict[str, Any]:
    relative_path = _relative_model_path(path)

    return {
        "path": relative_path,
        "source_type": _model_source_type(relative_path),
        "sql": _string_or_none(item.get("sql")),
        "sql_table": _string_or_none(item.get("sql_table")),
        "measures": _source_members(item.get("measures")),
        "dimensions": _source_members(item.get("dimensions")),
        "segments": _source_members(item.get("segments")),
        "joins": _source_joins(item.get("joins")),
    }


def _source_members(members: Any) -> dict[str, Any]:
    if not isinstance(members, list):
        return {}

    return {
        member["name"]: {
            "sql": _string_or_none(member.get("sql")),
            "filters": _source_filters(member.get("filters")),
        }
        for member in members
        if isinstance(member, dict) and isinstance(member.get("name"), str)
    }


def _source_joins(joins: Any) -> dict[str, Any]:
    if not isinstance(joins, list):
        return {}

    return {
        join["name"]: {
            "sql": _string_or_none(join.get("sql")),
            "relationship": _string_or_none(join.get("relationship")),
        }
        for join in joins
        if isinstance(join, dict) and isinstance(join.get("name"), str)
    }


def _source_filters(filters: Any) -> list[dict[str, str]]:
    if not isinstance(filters, list):
        return []

    return [
        {"sql": filter_item["sql"]}
        for filter_item in filters
        if isinstance(filter_item, dict) and isinstance(filter_item.get("sql"), str)
    ]


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _is_generated_overlay(path: Path) -> bool:
    if path.suffix.lower() not in {".yml", ".yaml"}:
        return False

    return _relative_model_path(path).startswith(GENERATED_OVERLAY_PREFIX)


def _model_source_type(relative_path: str) -> str:
    if relative_path.startswith(GENERATED_CONNECTION_PREFIX):
        return "generated_connection"

    if relative_path.startswith(GENERATED_OVERLAY_PREFIX):
        return "generated_overlay"

    if relative_path.startswith("overlays/"):
        return "overlay"

    return "bundled_connector"
