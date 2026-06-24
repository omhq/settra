import os
import time

from typing import Any
from pathlib import Path

import yaml

from fastapi import HTTPException

from app.cube.client import load_cube_meta
from app.cube.config import CUBE_MODEL_DIR
from app.routers.constants import CONNECTORS_DIR

BUNDLED_MODEL_SYNC_MODE = os.getenv("CUBE_BUNDLED_MODEL_SYNC_MODE", "missing")
GENERATED_OVERLAY_PREFIX = "overlays/generated/"


async def sync_cube_model() -> dict[str, Any]:
    """Refresh the direct Cube model view without generating files."""

    CUBE_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    bundled_models = sync_bundled_connector_models()

    return {
        "ok": True,
        "model_dir": str(CUBE_MODEL_DIR),
        "bundled_models": bundled_models,
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


def sync_bundled_connector_models() -> dict[str, Any]:
    """Copy packaged connector Cube YAML into the active Cube model directory."""
    CUBE_MODEL_DIR.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    skipped: list[str] = []
    mode = BUNDLED_MODEL_SYNC_MODE.strip().lower()
    overwrite = mode == "overwrite"

    for source in sorted(CONNECTORS_DIR.glob("*/semantics.y*ml")):
        connector_key = source.parent.name
        target = CUBE_MODEL_DIR / f"{connector_key}.yaml"

        if target.exists() and not overwrite:
            skipped.append(_relative_model_path(target))
            continue

        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        copied.append(_relative_model_path(target))

    return {
        "mode": "overwrite" if overwrite else "missing",
        "source_dir": str(CONNECTORS_DIR),
        "copied": copied,
        "skipped": skipped,
    }


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


def save_model_file(file_path: str, content: str) -> dict[str, Any]:
    path = _safe_model_path(file_path)

    if path.suffix.lower() not in {".yml", ".yaml"}:
        raise HTTPException(400, "Only Cube YAML model files can be edited")

    try:
        loaded = yaml.safe_load(content) if content.strip() else {}
    except yaml.YAMLError as exc:
        raise HTTPException(422, f"Invalid YAML: {exc}") from exc

    if loaded is not None and not isinstance(loaded, dict):
        raise HTTPException(422, "Cube model YAML must contain a mapping")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

    return {
        "ok": True,
        "file": _model_file_summary(path),
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
    parsed = _read_model_yaml(path)
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

    return {
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


def _is_generated_overlay(path: Path) -> bool:
    if path.suffix.lower() not in {".yml", ".yaml"}:
        return False

    return _relative_model_path(path).startswith(GENERATED_OVERLAY_PREFIX)


def _model_source_type(relative_path: str) -> str:
    if relative_path.startswith(GENERATED_OVERLAY_PREFIX):
        return "generated_overlay"

    if relative_path.startswith("overlays/"):
        return "overlay"

    return "bundled_connector"
