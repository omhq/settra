from typing import Any

from app.common.config import CONNECTION_CONFIG_DIR
from app.cube.config import CUBE_MODEL_DIR
from app.cube.model_generation import (
    CubeModelGenerator,
    _saved_connections,
    render_connection_manifest_model,
)
from app.cube.model_repository import CubeModelRepository


def model_repository() -> CubeModelRepository:
    """Return a repository bound to the currently configured Cube model root."""

    return CubeModelRepository(CUBE_MODEL_DIR)


def model_generator() -> CubeModelGenerator:
    return CubeModelGenerator(
        model_repository(),
        connection_config_dir=CONNECTION_CONFIG_DIR,
    )


async def sync_cube_model() -> dict[str, Any]:
    return await model_generator().sync_all()


async def sync_connection_models() -> dict[str, Any]:
    return await model_generator().sync_connections()


async def cube_model_summary(
    organization_id: int | None = None,
) -> dict[str, Any]:
    from app.semantic.catalog import cube_model_summary as load_summary

    return await load_summary(organization_id)


async def cube_meta(organization_id: int | None = None) -> dict[str, Any]:
    from app.semantic.catalog import cube_meta as load_meta

    return await load_meta(organization_id)


def list_model_files(
    *,
    allowed_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    return model_repository().list_files(allowed_names=allowed_names)


def list_semantic_overlay_files(
    *,
    allowed_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    return model_repository().list_overlays(allowed_names=allowed_names)


def source_definition_index(
    *,
    allowed_names: set[str] | None = None,
) -> dict[str, Any]:
    return model_repository().source_definition_index(allowed_names=allowed_names)


def authored_definition_index(
    *,
    allowed_names: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    return model_repository().authored_definition_index(allowed_names=allowed_names)


async def organization_connection_ids(
    organization_id: int | None = None,
) -> set[int]:
    from app.semantic.catalog import organization_connection_ids as load_ids

    return await load_ids(organization_id)


async def organization_cube_names(
    organization_id: int | None = None,
) -> set[str]:
    from app.semantic.catalog import organization_cube_names as load_names

    return await load_names(organization_id)


def read_model_file(file_path: str) -> dict[str, Any]:
    return model_repository().read(file_path)


def read_semantic_overlay_file(file_path: str) -> dict[str, Any]:
    return model_repository().read_overlay(file_path)


def save_model_file(file_path: str, content: str) -> dict[str, Any]:
    return model_repository().save(file_path, content)


def create_model_file(file_path: str, content: str) -> dict[str, Any]:
    return model_repository().create(file_path, content)


def update_model_file(file_path: str, content: str) -> dict[str, Any]:
    return model_repository().update(file_path, content)


def delete_generated_model_file(file_path: str) -> dict[str, Any]:
    return model_repository().delete_generated(file_path)
