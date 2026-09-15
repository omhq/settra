import logging
import re
from typing import Any

from app.auth import current_organization_id
from app.common.config import GOOGLE_DRIVE_KEY
from app.cube.client import load_cube_meta
from app.cube.model_repository import CubeModelRepository
from app.db import db_connection

logger = logging.getLogger(__name__)


class SemanticCatalogService:
    """Combine authored Cube definitions with compiled, tenant-visible metadata."""

    def __init__(self, repository: CubeModelRepository) -> None:
        self.repository = repository

    def source_definitions(
        self,
        *,
        allowed_names: set[str] | None = None,
    ) -> dict[str, Any]:
        return self.repository.source_definition_index(allowed_names=allowed_names)

    def authored_definitions(
        self,
        *,
        allowed_names: set[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        return self.repository.authored_definition_index(allowed_names=allowed_names)

    async def compiled_meta(
        self,
        *,
        allowed_names: set[str],
    ) -> dict[str, Any]:
        meta = await load_cube_meta()
        cubes = meta.get("cubes") if isinstance(meta, dict) else []
        visible = (
            [
                cube
                for cube in cubes
                if isinstance(cube, dict) and cube.get("name") in allowed_names
            ]
            if isinstance(cubes, list)
            else []
        )
        return (
            {**meta, "cubes": visible} if isinstance(meta, dict) else {"cubes": visible}
        )

    async def summary(self, *, allowed_names: set[str]) -> dict[str, Any]:
        files = self.repository.list_files(allowed_names=allowed_names)
        cube_status: dict[str, Any] = {
            "connected": False,
            "cube_count": 0,
            "error": None,
            "meta": None,
        }

        try:
            meta = await self.compiled_meta(allowed_names=allowed_names)
            cubes = meta.get("cubes") if isinstance(meta, dict) else []
            cube_status = {
                "connected": True,
                "cube_count": len(cubes) if isinstance(cubes, list) else 0,
                "error": None,
                "meta": meta,
            }
        except Exception:
            # Cube is shared infrastructure. Compiler details can mention another
            # tenant's model, so only record them in server logs.
            logger.exception("Could not load Cube metadata for model summary")
            cube_status["error"] = "Cube metadata is currently unavailable"

        return {
            "model_dir": str(self.repository.model_dir),
            "files": files,
            "source_definitions": {
                "cubes": self.source_definitions(allowed_names=allowed_names),
            },
            "cube": cube_status,
        }


def semantic_catalog_service(
    repository: CubeModelRepository | None = None,
) -> SemanticCatalogService:
    if repository is None:
        # Resolve the configured adapter lazily so tests and alternate runtimes
        # can replace the Cube model root without domain-level global state.
        from app.cube.model import model_repository

        repository = model_repository()
    return SemanticCatalogService(repository)


def source_definition_index(
    *,
    allowed_names: set[str] | None = None,
) -> dict[str, Any]:
    return semantic_catalog_service().source_definitions(allowed_names=allowed_names)


def authored_definition_index(
    *,
    allowed_names: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    return semantic_catalog_service().authored_definitions(allowed_names=allowed_names)


async def cube_model_summary(
    organization_id: int | None = None,
) -> dict[str, Any]:
    allowed_names = await organization_cube_names(organization_id)
    return await semantic_catalog_service().summary(allowed_names=allowed_names)


async def cube_meta(organization_id: int | None = None) -> dict[str, Any]:
    allowed_names = await organization_cube_names(organization_id)
    return await semantic_catalog_service().compiled_meta(allowed_names=allowed_names)


async def organization_connection_ids(
    organization_id: int | None = None,
) -> set[int]:
    effective_id = organization_id or current_organization_id()
    async with db_connection() as db:
        rows = await db.fetch(
            """
            SELECT id
            FROM connections
            WHERE organization_id = $1 AND plugin = $2
            """,
            effective_id,
            GOOGLE_DRIVE_KEY,
        )
    return {int(row[0]) for row in rows}


async def organization_cube_names(
    organization_id: int | None = None,
) -> set[str]:
    return allowed_cube_names_for_pipe_ids(
        await organization_connection_ids(organization_id)
    )


def allowed_cube_names_for_pipe_ids(pipe_ids: set[int]) -> set[str]:
    """Derive visible models from their source-connection provenance."""

    if not pipe_ids:
        return set()

    definitions = authored_definition_index()
    allowed: set[str] = set()

    for name, source in definitions.items():
        definition = source.get("definition") if isinstance(source, dict) else None
        if not isinstance(definition, dict):
            continue
        connection_ids = definition_connection_ids(definition)
        if connection_ids and connection_ids.issubset(pipe_ids):
            allowed.add(name)

    changed = True
    while changed:
        changed = False
        for name, source in definitions.items():
            if name in allowed or not isinstance(source, dict):
                continue
            definition = source.get("definition")
            if not isinstance(definition, dict):
                continue
            dependencies = definition_dependencies(definition)
            if dependencies and dependencies.issubset(allowed):
                allowed.add(name)
                changed = True

    # Provenance identifies physical tables; dependencies identify every source
    # required by an authored join, view, or member expression.
    changed = True
    while changed:
        changed = False
        for name in list(allowed):
            definition = definitions[name]["definition"]
            if not definition_dependencies(definition).issubset(allowed):
                allowed.remove(name)
                changed = True

    return allowed


def definition_connection_ids(definition: dict[str, Any]) -> set[int]:
    meta = definition.get("meta")
    settra = meta.get("settra") if isinstance(meta, dict) else None
    if not isinstance(settra, dict):
        return set()

    metadata_sources = [settra]
    if isinstance(settra.get("overlay"), dict):
        metadata_sources.append(settra["overlay"])

    values: list[Any] = []
    for source in metadata_sources:
        if source.get("connection_id") is not None:
            values.append(source["connection_id"])
        if isinstance(source.get("connection_ids"), list):
            values.extend(source["connection_ids"])

    result: set[int] = set()
    for value in values:
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            continue
    return result


def definition_dependencies(definition: dict[str, Any]) -> set[str]:
    dependencies: set[str] = set()

    cubes = definition.get("cubes")
    for item in cubes if isinstance(cubes, list) else []:
        if not isinstance(item, dict):
            continue
        join_path = item.get("join_path")
        if isinstance(join_path, str) and join_path.strip():
            dependencies.add(join_path.strip().split(".", 1)[0])

    joins = definition.get("joins")
    for item in joins if isinstance(joins, list) else []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            dependencies.add(item["name"].strip())

    extends = definition.get("extends")
    for value in extends if isinstance(extends, list) else [extends]:
        if isinstance(value, str) and value.strip():
            dependencies.add(value.strip().strip("{}").split(".", 1)[0])

    def expression_references(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, str) and (
                    str(key).startswith("sql") or key == "expression"
                ):
                    dependencies.update(
                        match.group(1) or match.group(2)
                        for match in re.finditer(
                            r"\{([A-Za-z][A-Za-z0-9_]*)\.[A-Za-z][A-Za-z0-9_]*\}"
                            r"|\{([A-Za-z][A-Za-z0-9_]*)\}\s*\.",
                            child,
                        )
                    )
                else:
                    expression_references(child)
        elif isinstance(value, list):
            for child in value:
                expression_references(child)

    expression_references(definition)
    return dependencies - {"", "CUBE", str(definition.get("name") or "")}
