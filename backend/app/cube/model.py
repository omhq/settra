import os
import re
import time

from typing import Any
from pathlib import Path

import yaml
import aiosqlite

from fastapi import HTTPException

from app.cube.client import load_cube_meta
from app.cube.config import CUBE_MODEL_DIR
from app.db import DB_PATH
from app.routers.constants import CONNECTORS_DIR

GENERATED_OVERLAY_PREFIX = "overlays/generated/"
GENERATED_CONNECTION_PREFIX = "generated/connections/"


async def sync_cube_model() -> dict[str, Any]:
    """Refresh generated Cube model files from saved connections."""

    CUBE_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    bundled_models = sync_bundled_connector_models()
    connection_models = await sync_connection_models()

    return {
        "ok": True,
        "model_dir": str(CUBE_MODEL_DIR),
        "bundled_models": bundled_models,
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


def sync_bundled_connector_models() -> dict[str, Any]:
    """Track packaged connector Cube YAML as templates, not active models."""
    CUBE_MODEL_DIR.mkdir(parents=True, exist_ok=True)

    templates: list[str] = []
    removed_active_files: list[str] = []
    skipped: list[str] = []

    for source in sorted(CONNECTORS_DIR.glob("*/semantics.y*ml")):
        connector_key = source.parent.name
        templates.append(f"connectors/{connector_key}/{source.name}")
        target = CUBE_MODEL_DIR / f"{connector_key}.yaml"

        if not target.exists():
            continue

        if _same_file(source, target):
            skipped.append(_relative_model_path(target))
            continue

        if target.read_text(encoding="utf-8") == source.read_text(encoding="utf-8"):
            removed_active_files.append(_relative_model_path(target))
            target.unlink()
            continue

        skipped.append(_relative_model_path(target))

    return {
        "mode": "template_only",
        "source_dir": str(CONNECTORS_DIR),
        "templates": templates,
        "removed_active_files": removed_active_files,
        "skipped": skipped,
    }


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
        source = _connector_semantics_path(connection["plugin"])

        if source is None:
            skipped.append(
                {
                    "slug": connection["slug"],
                    "plugin": connection["plugin"],
                    "reason": "missing connector semantics template",
                }
            )
            continue

        model = render_connection_model(source, connection)
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


def render_connection_model(
    source: Path,
    connection: dict[str, Any],
) -> str:
    plugin = str(connection["plugin"])
    slug = str(connection["slug"])
    parsed = _read_model_yaml(source)
    model = _connection_model_yaml(parsed, plugin, slug, connection)

    return yaml.safe_dump(model, sort_keys=False, allow_unicode=False)


async def _saved_connections() -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("""
            SELECT id, name, slug, plugin, status, created_at
            FROM connections
            ORDER BY created_at ASC
            """) as cur:
            rows = await cur.fetchall()

    return [dict(row) for row in rows]


def _connector_semantics_path(plugin: str) -> Path | None:
    connector_dir = CONNECTORS_DIR / plugin

    for name in ("semantics.yaml", "semantics.yml"):
        candidate = connector_dir / name
        if candidate.is_file():
            return candidate

    return None


def _connection_model_yaml(
    parsed: dict[str, Any],
    plugin: str,
    slug: str,
    connection: dict[str, Any],
) -> dict[str, Any]:
    name_map = _cube_name_map(parsed, plugin, slug)
    model = _rewrite_connection_value(parsed, plugin, slug, name_map)

    for key in ("cubes", "views"):
        items = model.get(key)

        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue

            _add_connection_meta(item, connection)

            title = item.get("title")

            if slug != plugin and isinstance(title, str):
                item["title"] = f"{title} ({connection['name']})"

    return model


def _cube_name_map(parsed: dict[str, Any], plugin: str, slug: str) -> dict[str, str]:
    mapping: dict[str, str] = {}

    for key in ("cubes", "views"):
        items = parsed.get(key)

        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue

            old_name = item["name"]
            mapping[old_name] = _connection_cube_name(old_name, plugin, slug)

    return mapping


def _connection_cube_name(name: str, plugin: str, slug: str) -> str:
    if slug == plugin:
        return name

    prefix = f"{plugin}_"

    if name.startswith(prefix):
        return f"{slug}_{name.removeprefix(prefix)}"

    return f"{slug}_{name}"


def _rewrite_connection_value(
    value: Any,
    plugin: str,
    slug: str,
    name_map: dict[str, str],
    key: str | None = None,
) -> Any:
    if isinstance(value, dict):
        return {
            item_key: _rewrite_connection_value(
                item_value,
                plugin,
                slug,
                name_map,
                item_key,
            )
            for item_key, item_value in value.items()
        }

    if isinstance(value, list):
        return [
            _rewrite_connection_value(item, plugin, slug, name_map, key)
            for item in value
        ]

    if not isinstance(value, str):
        return value

    if key == "sql_table":
        return _rewrite_sql_table_schema(value, plugin, slug)

    if key == "name" and value in name_map:
        return name_map[value]

    return _rewrite_cube_references(value, name_map)


def _rewrite_sql_table_schema(value: str, plugin: str, slug: str) -> str:
    quoted = re.match(r'^"(?P<schema>[^"]+)"\."(?P<table>[^"]+)"$', value)

    if quoted and quoted.group("schema") == plugin:
        return f'"{_escape_sql_identifier(slug)}"."{quoted.group("table")}"'

    bare = re.match(r"^(?P<schema>[A-Za-z_][A-Za-z0-9_]*)\.(?P<table>.+)$", value)

    if bare and bare.group("schema") == plugin:
        return f"{slug}.{bare.group('table')}"

    return value


def _rewrite_cube_references(value: str, name_map: dict[str, str]) -> str:
    rewritten = value

    for old_name, new_name in sorted(
        name_map.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        rewritten = rewritten.replace(f"{{{old_name}}}", f"{{{new_name}}}")
        rewritten = re.sub(
            rf"\b{re.escape(old_name)}\.",
            f"{new_name}.",
            rewritten,
        )

    return rewritten


def _add_connection_meta(item: dict[str, Any], connection: dict[str, Any]) -> None:
    meta = item.get("meta")

    if not isinstance(meta, dict):
        meta = {}

    settra_meta = meta.get("settra")

    if not isinstance(settra_meta, dict):
        settra_meta = {}

    settra_meta.update(
        {
            "source_type": "generated_connection",
            "connection_id": connection["id"],
            "connection_name": connection["name"],
            "connection_slug": connection["slug"],
            "connector_key": connection["plugin"],
        }
    )
    meta["settra"] = settra_meta
    item["meta"] = meta


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


def _same_file(left: Path, right: Path) -> bool:
    try:
        return left.samefile(right)
    except FileNotFoundError:
        return False


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
