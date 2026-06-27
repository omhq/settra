from fastapi import HTTPException

from app.cube.client import load_cube_meta
from app.cube.model import read_model_file
from app.cube.query import cube_by_name, semantic_catalog

from .common import json_text, mcp_server, run_mcp_action


@mcp_server.resource(
    "settra://semantics/meta",
    name="cube-meta",
    title="Cube Metadata",
    description="Raw compiled Cube /v1/meta metadata.",
    mime_type="application/json",
)
async def cube_meta_resource() -> str:
    """Raw compiled Cube metadata."""

    return json_text(await run_mcp_action(load_cube_meta()))


@mcp_server.resource(
    "settra://semantics/cubes",
    name="cube-catalog",
    title="Cube Catalog",
    description="Summarized cubes, measures, dimensions, segments, and joins.",
    mime_type="application/json",
)
async def cube_catalog_resource() -> str:
    """Summarized compiled Cube catalog."""

    return json_text(await run_mcp_action(semantic_catalog()))


@mcp_server.resource(
    "settra://semantics/cubes/{name}",
    name="cube",
    title="Cube Metadata",
    description="Compiled Cube metadata by cube or view name.",
    mime_type="application/json",
)
async def cube_resource(name: str) -> str:
    """Compiled Cube metadata by name."""

    return json_text(await run_mcp_action(cube_by_name(name)))


@mcp_server.resource(
    "settra://semantics/model/{path}",
    name="cube-model-file",
    title="Cube Model File",
    description="Mounted Cube YAML model file by path.",
    mime_type="application/yaml",
)
def cube_model_resource(path: str) -> str:
    """Mounted Cube YAML model file by path."""

    try:
        return read_model_file(path)["content"]
    except HTTPException as exc:
        raise ValueError(str(exc.detail)) from exc
