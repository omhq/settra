from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.common.config import (
    CONNECTION_CONFIG_DIR,
    GOOGLE_DRIVE_KEY,
)
from app.cube.model_repository import (
    GENERATED_CONNECTION_PREFIX,
    CubeModelRepository,
)
from app.db import db_connection


class CubeModelGenerator:
    """Generate Cube models from durable connection manifests."""

    def __init__(
        self,
        repository: CubeModelRepository,
        connection_config_dir: Path = CONNECTION_CONFIG_DIR,
    ) -> None:
        self.repository = repository
        self.connection_config_dir = connection_config_dir

    async def sync_all(self) -> dict[str, Any]:
        connection_models = await self.sync_connections()
        return {
            "ok": True,
            "model_dir": str(self.repository.model_dir),
            "connection_models": connection_models,
            "files": self.repository.list_files(),
        }

    async def sync_connections(self) -> dict[str, Any]:
        target_dir = self.repository.model_dir / GENERATED_CONNECTION_PREFIX
        target_dir.mkdir(parents=True, exist_ok=True)

        connections = await _saved_connections()
        written: list[str] = []
        skipped: list[dict[str, str]] = []
        expected_paths: set[Path] = set()

        for connection in connections:
            storage_key = connection.get("storage_key") or connection["slug"]
            manifest_path = self.connection_config_dir / f"{storage_key}.manifest.yaml"
            if not manifest_path.is_file():
                skipped.append(
                    {
                        "slug": connection["slug"],
                        "plugin": GOOGLE_DRIVE_KEY,
                        "reason": "no successful PostgreSQL sync manifest",
                    }
                )
                continue

            model = render_connection_manifest_model(manifest_path, connection)
            target = target_dir / f"{storage_key}.yaml"
            target.write_text(model, encoding="utf-8")
            expected_paths.add(target.resolve())
            written.append(self.repository.relative_path(target))

        removed: list[str] = []
        for stale in sorted(target_dir.glob("*.y*ml")):
            if stale.resolve() in expected_paths:
                continue
            removed.append(self.repository.relative_path(stale))
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
    manifest = _read_yaml(manifest_path)
    tables = manifest.get("tables")
    if not isinstance(tables, list):
        tables = []

    cubes = []
    storage_key = connection.get("storage_key") or connection["slug"]

    for table in tables:
        if not isinstance(table, dict) or not table.get("name"):
            continue

        table_name = str(table["name"])
        cube_name = f"{storage_key}_{table_name}"
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
                f'"{_escape_sql_identifier(str(connection.get("destination_schema") or storage_key))}".'
                f'"{_escape_sql_identifier(table_name)}"'
            ),
            "title": f"{_human_title(table_name)} ({connection['name']})",
            "measures": [
                {
                    "name": count_measure_name,
                    "title": "Rows",
                    "description": "Number of rows in the latest durable source snapshot.",
                    "type": "count",
                    "meta": {"settra": {"internal": True}},
                }
            ],
            "dimensions": dimensions,
            "meta": {
                "settra": {
                    "source_type": "generated_connection",
                    "connection_id": connection["id"],
                    "connection_name": connection["name"],
                    "connection_slug": connection["slug"],
                    "organization_id": connection.get("organization_id"),
                    "destination_id": connection.get("destination_id"),
                    "destination_slug": connection.get("destination_slug"),
                    "destination_schema": (
                        connection.get("destination_schema") or storage_key
                    ),
                    "source_key": GOOGLE_DRIVE_KEY,
                    "source_table": (
                        table.get("source_name")
                        or table.get("source_sheet")
                        or table_name
                    ),
                    "source_format": (
                        manifest.get("source", {}).get("format")
                        if isinstance(manifest.get("source"), dict)
                        else None
                    ),
                    "storage": "postgres",
                    "sync_manifest_generated_at": manifest.get("generated_at"),
                    **({"row_key": table["row_key"]} if table.get("row_key") else {}),
                }
            },
        }
        table_description = str(table.get("description") or "").strip()
        if table_description:
            cube["description"] = table_description
        cubes.append(cube)

    return yaml.safe_dump({"cubes": cubes}, sort_keys=False, allow_unicode=True)


async def _saved_connections() -> list[dict[str, Any]]:
    async with db_connection() as db:
        rows = await db.fetch(
            """
            SELECT c.id, c.name, c.slug, c.storage_key, c.organization_id,
                   c.plugin, c.status, c.created_at,
                   c.destination_id, c.destination_schema,
                   d.slug AS destination_slug, d.type AS destination_type
            FROM connections c
            JOIN destinations d ON d.id = c.destination_id
            WHERE c.plugin = $1
            ORDER BY c.created_at ASC
            """,
            GOOGLE_DRIVE_KEY,
        )
    return [dict(row) for row in rows]


def _read_yaml(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content) if content.strip() else {}
    return parsed if isinstance(parsed, dict) else {}


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


def _escape_sql_identifier(value: str) -> str:
    return value.replace('"', '""')
