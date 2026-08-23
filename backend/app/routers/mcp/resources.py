from urllib.parse import unquote

from fastapi import HTTPException

from app.cube.client import load_cube_meta
from app.cube.model import read_model_file
from app.cube.query import cube_by_name, semantic_catalog
from app.collection_service import collection_cube_names

from .common import json_text, mcp_server, run_mcp_action


@mcp_server.resource(
    "settra://collections/{collection}/semantics/meta",
    name="collection-cube-meta",
    title="Collection Cube Metadata",
    description="Compiled Cube metadata filtered to one collection.",
    mime_type="application/json",
)
async def cube_meta_resource(collection: str) -> str:
    """Compiled Cube metadata filtered to one collection."""

    allowed_names = await run_mcp_action(collection_cube_names(collection))
    meta = await run_mcp_action(load_cube_meta())
    cubes = meta.get("cubes") if isinstance(meta, dict) else []
    cubes = cubes if isinstance(cubes, list) else []
    return json_text(
        {
            "cubes": [
                cube
                for cube in cubes if isinstance(cube, dict)
                and cube.get("name") in allowed_names
            ]
        }
    )


@mcp_server.resource(
    "settra://collections/{collection}/semantics/cubes",
    name="collection-cube-catalog",
    title="Collection Cube Catalog",
    description=(
        "First bounded page of high-level compiled cube summaries. Use the "
        "list_cubes tool for cursor pagination beyond this fixed resource page."
    ),
    mime_type="application/json",
)
async def cube_catalog_resource(collection: str) -> str:
    """First bounded page of one collection's compiled Cube catalog."""

    allowed_names = await run_mcp_action(collection_cube_names(collection))
    catalog = await run_mcp_action(semantic_catalog(allowed_names=allowed_names))
    page = catalog.get("page") if isinstance(catalog.get("page"), dict) else {}

    return json_text(
        {
            **catalog,
            "page": {key: value for key, value in page.items() if key != "next_cursor"},
        }
    )


@mcp_server.resource(
    "settra://collections/{collection}/semantics/cubes/{name}",
    name="collection-cube",
    title="Collection Cube Semantics",
    description="Compact semantic definition by collection and cube or view name.",
    mime_type="application/json",
)
async def cube_resource(collection: str, name: str) -> str:
    """Compact Cube semantics by collection and name."""

    allowed_names = await run_mcp_action(collection_cube_names(collection))
    return json_text(
        await run_mcp_action(cube_by_name(name, allowed_names=allowed_names))
    )


@mcp_server.resource(
    "settra://collections/{collection}/semantics/model/{path}",
    name="collection-cube-model-file",
    title="Collection Cube Model File",
    description=(
        "Mounted Cube YAML model file when all declared models belong to a "
        "collection. Percent-encode slashes in nested model paths."
    ),
    mime_type="application/yaml",
)
async def cube_model_resource(collection: str, path: str) -> str:
    """Mounted Cube YAML model file constrained to one collection."""

    try:
        allowed_names = await run_mcp_action(collection_cube_names(collection))
        file = read_model_file(unquote(path))
        model_names = {
            *file.get("cube_names", []),
            *file.get("view_names", []),
        }
        if not model_names or not model_names.issubset(allowed_names):
            raise ValueError("Cube model file is outside the selected collection")
        return file["content"]
    except HTTPException as exc:
        raise ValueError(str(exc.detail)) from exc
