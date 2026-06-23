import os
import time

from pathlib import Path
from typing import Any

import yaml

from fastapi import HTTPException

from app.cube.client import load_cube_meta
from app.cube.config import CUBE_MODEL_DIR


async def sync_cube_model() -> dict[str, Any]:
    """Refresh the direct Cube model view without generating files."""

    CUBE_MODEL_DIR.mkdir(parents=True, exist_ok=True)

    return {
        "ok": True,
        "model_dir": str(CUBE_MODEL_DIR),
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
    content = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content) if content.strip() else {}
    parsed = parsed if isinstance(parsed, dict) else {}
    cubes = parsed.get("cubes")
    views = parsed.get("views")
    cube_names = [
        cube["name"]
        for cube in cubes
        if isinstance(cube, dict) and isinstance(cube.get("name"), str)
    ] if isinstance(cubes, list) else []

    return {
        "path": _relative_model_path(path),
        "size": stat.st_size,
        "updated_at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(stat.st_mtime),
        ),
        "cube_count": len(cubes) if isinstance(cubes, list) else 0,
        "view_count": len(views) if isinstance(views, list) else 0,
        "cube_names": cube_names,
    }
