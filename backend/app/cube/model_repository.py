from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException

GENERATED_OVERLAY_PREFIX = "overlays/generated/"
GENERATED_CONNECTION_PREFIX = "generated/connections/"


class CubeModelRepository:
    """Own filesystem persistence and indexing for Cube YAML model files."""

    def __init__(self, model_dir: Path) -> None:
        self.model_dir = model_dir

    def list_files(
        self,
        *,
        allowed_names: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        self.model_dir.mkdir(parents=True, exist_ok=True)
        files: list[dict[str, Any]] = []

        for path in self._yaml_files():
            summary = self._file_summary(path)
            model_names = set(summary["cube_names"]) | set(summary["view_names"])
            if allowed_names is not None and (
                not model_names or not model_names.issubset(allowed_names)
            ):
                continue
            files.append(summary)

        return files

    def list_overlays(
        self,
        *,
        allowed_names: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        return [
            file
            for file in self.list_files(allowed_names=allowed_names)
            if file.get("source_type") in {"overlay", "generated_overlay"}
        ]

    def source_definition_index(
        self,
        *,
        allowed_names: set[str] | None = None,
    ) -> dict[str, Any]:
        definitions: dict[str, Any] = {}

        for path, _key, item in self._definitions():
            name = item["name"]
            if allowed_names is None or name in allowed_names:
                definitions[name] = self._source_definition(path, item)

        return definitions

    def authored_definition_index(
        self,
        *,
        allowed_names: set[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        definitions: dict[str, dict[str, Any]] = {}

        for path, _key, item in self._definitions():
            name = item["name"]
            if allowed_names is not None and name not in allowed_names:
                continue
            relative_path = self.relative_path(path)
            definitions[name] = {
                "path": relative_path,
                "source_type": self.model_source_type(relative_path),
                "definition": item,
            }

        return definitions

    def read(self, file_path: str) -> dict[str, Any]:
        path = self.safe_path(file_path)
        if not path.is_file():
            raise HTTPException(404, "Cube model file not found")

        return {
            **self._file_summary(path),
            "content": path.read_text(encoding="utf-8"),
        }

    def read_overlay(self, file_path: str) -> dict[str, Any]:
        file = self.read(file_path)
        if file.get("source_type") not in {"overlay", "generated_overlay"}:
            raise HTTPException(400, "Path is not a semantic overlay")
        return file

    def save(self, file_path: str, content: str) -> dict[str, Any]:
        path = self.safe_path(file_path)
        self._validate_content(path, content)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"ok": True, "file": self._file_summary(path)}

    def create(self, file_path: str, content: str) -> dict[str, Any]:
        path = self.safe_path(file_path)
        self._validate_content(path, content)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with path.open("x", encoding="utf-8") as file:
                file.write(content)
        except FileExistsError as exc:
            raise HTTPException(409, "Cube model file already exists") from exc

        return {"ok": True, "created": True, "file": self._file_summary(path)}

    def update(self, file_path: str, content: str) -> dict[str, Any]:
        path = self.safe_path(file_path)
        self._validate_content(path, content)
        if not path.is_file():
            raise HTTPException(404, "Cube model file not found")

        previous_content = path.read_text(encoding="utf-8")
        path.write_text(content, encoding="utf-8")
        return {
            "ok": True,
            "updated": previous_content != content,
            "file": self._file_summary(path),
            "previous_content": previous_content,
        }

    def delete_generated(self, file_path: str) -> dict[str, Any]:
        path = self.safe_path(file_path)
        if not self._is_generated_overlay(path):
            raise HTTPException(
                400,
                "Only generated semantic overlay files can be deleted",
            )
        if not path.is_file():
            raise HTTPException(404, "Generated semantic overlay file not found")

        file = self._file_summary(path)
        path.unlink()
        return {"ok": True, "deleted": file}

    def relative_path(self, path: Path) -> str:
        return path.resolve().relative_to(self.model_dir.resolve()).as_posix()

    def safe_path(self, file_path: str) -> Path:
        normalized = os.path.normpath(file_path.strip().lstrip("/"))
        if normalized == "." or normalized.startswith("../"):
            raise HTTPException(400, "Invalid Cube model file path")

        path = (self.model_dir / normalized).resolve()
        model_dir = self.model_dir.resolve()
        if path != model_dir and model_dir not in path.parents:
            raise HTTPException(400, "Invalid Cube model file path")
        return path

    @staticmethod
    def model_source_type(relative_path: str) -> str:
        if relative_path.startswith(GENERATED_CONNECTION_PREFIX):
            return "generated_connection"
        if relative_path.startswith(GENERATED_OVERLAY_PREFIX):
            return "generated_overlay"
        if relative_path.startswith("overlays/"):
            return "overlay"
        return "bundled_connector"

    def _yaml_files(self) -> list[Path]:
        self.model_dir.mkdir(parents=True, exist_ok=True)
        return [
            path
            for path in sorted(self.model_dir.rglob("*"))
            if path.is_file() and path.suffix.lower() in {".yml", ".yaml"}
        ]

    def _definitions(self):
        for path in self._yaml_files():
            parsed = self._read_yaml(path)
            for key in ("cubes", "views"):
                items = parsed.get(key)
                for item in items if isinstance(items, list) else []:
                    if isinstance(item, dict) and isinstance(item.get("name"), str):
                        yield path, key, item

    def _validate_content(self, path: Path, content: str) -> None:
        if path.suffix.lower() not in {".yml", ".yaml"}:
            raise HTTPException(400, "Only Cube YAML model files can be edited")

        try:
            loaded = yaml.safe_load(content) if content.strip() else {}
        except yaml.YAMLError as exc:
            raise HTTPException(422, f"Invalid YAML: {exc}") from exc
        if loaded is not None and not isinstance(loaded, dict):
            raise HTTPException(422, "Cube model YAML must contain a mapping")

    def _file_summary(self, path: Path) -> dict[str, Any]:
        stat = path.stat()
        relative_path = self.relative_path(path)
        parse_error = None

        try:
            parsed = self._read_yaml(path)
        except yaml.YAMLError as exc:
            parsed = {}
            parse_error = str(exc)

        cubes = parsed.get("cubes")
        views = parsed.get("views")
        cube_names = self._definition_names(cubes)
        view_names = self._definition_names(views)
        summary = {
            "path": relative_path,
            "source_type": self.model_source_type(relative_path),
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

    def _read_yaml(self, path: Path) -> dict[str, Any]:
        content = path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(content) if content.strip() else {}
        return parsed if isinstance(parsed, dict) else {}

    def _source_definition(
        self,
        path: Path,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        relative_path = self.relative_path(path)
        return {
            "path": relative_path,
            "source_type": self.model_source_type(relative_path),
            "sql": self._string_or_none(item.get("sql")),
            "sql_table": self._string_or_none(item.get("sql_table")),
            "measures": self._source_members(item.get("measures")),
            "dimensions": self._source_members(item.get("dimensions")),
            "segments": self._source_members(item.get("segments")),
            "joins": self._source_joins(item.get("joins")),
        }

    def _source_members(self, members: Any) -> dict[str, Any]:
        if not isinstance(members, list):
            return {}
        return {
            member["name"]: {
                "sql": self._string_or_none(member.get("sql")),
                "filters": self._source_filters(member.get("filters")),
            }
            for member in members
            if isinstance(member, dict) and isinstance(member.get("name"), str)
        }

    def _source_joins(self, joins: Any) -> dict[str, Any]:
        if not isinstance(joins, list):
            return {}
        return {
            join["name"]: {
                "sql": self._string_or_none(join.get("sql")),
                "relationship": self._string_or_none(join.get("relationship")),
            }
            for join in joins
            if isinstance(join, dict) and isinstance(join.get("name"), str)
        }

    @staticmethod
    def _source_filters(filters: Any) -> list[dict[str, str]]:
        if not isinstance(filters, list):
            return []
        return [
            {"sql": filter_item["sql"]}
            for filter_item in filters
            if isinstance(filter_item, dict) and isinstance(filter_item.get("sql"), str)
        ]

    @staticmethod
    def _definition_names(items: Any) -> list[str]:
        if not isinstance(items, list):
            return []
        return [
            item["name"]
            for item in items
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        ]

    @staticmethod
    def _string_or_none(value: Any) -> str | None:
        return value if isinstance(value, str) else None

    def _is_generated_overlay(self, path: Path) -> bool:
        return path.suffix.lower() in {".yml", ".yaml"} and self.relative_path(
            path
        ).startswith(GENERATED_OVERLAY_PREFIX)
