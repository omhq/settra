from urllib.parse import unquote

from app.cube.client import load_cube_meta
from app.cube.model import read_model_file
from app.cube.query import cube_by_name, semantic_catalog
from app.collection_service import collection_cube_names

from .common import json_text, mcp_server, run_mcp_action, run_mcp_operation


@mcp_server.resource(
    "settra://artifacts/{artifact}/semantics/meta",
    name="artifact-cube-meta",
    title="Artifact Cube Metadata",
    description="Compiled Cube metadata filtered to one artifact.",
    mime_type="application/json",
)
async def cube_meta_resource(artifact: str) -> str:
    """Compiled Cube metadata filtered to one artifact."""

    allowed_names = await run_mcp_action(collection_cube_names(artifact))
    meta = await run_mcp_action(load_cube_meta())
    cubes = meta.get("cubes") if isinstance(meta, dict) else []
    cubes = cubes if isinstance(cubes, list) else []

    return json_text(
        {
            "cubes": [
                cube
                for cube in cubes
                if isinstance(cube, dict) and cube.get("name") in allowed_names
            ]
        }
    )


@mcp_server.resource(
    "settra://artifacts/{artifact}/semantics/cubes",
    name="artifact-cube-catalog",
    title="Artifact Cube Catalog",
    description=(
        "First bounded page of high-level compiled cube summaries. Use the "
        "list_cubes tool for cursor pagination beyond this fixed resource page."
    ),
    mime_type="application/json",
)
async def cube_catalog_resource(artifact: str) -> str:
    """First bounded page of one artifact's compiled Cube catalog."""

    allowed_names = await run_mcp_action(collection_cube_names(artifact))
    catalog = await run_mcp_action(semantic_catalog(allowed_names=allowed_names))
    page = catalog.get("page") if isinstance(catalog.get("page"), dict) else {}

    return json_text(
        {
            **catalog,
            "page": {key: value for key, value in page.items() if key != "next_cursor"},
        }
    )


@mcp_server.resource(
    "settra://artifacts/{artifact}/semantics/cubes/{name}",
    name="artifact-cube",
    title="Artifact Cube Semantics",
    description="Compact semantic definition by artifact and cube or view name.",
    mime_type="application/json",
)
async def cube_resource(artifact: str, name: str) -> str:
    """Compact Cube semantics by artifact and name."""

    allowed_names = await run_mcp_action(collection_cube_names(artifact))

    return json_text(
        await run_mcp_action(cube_by_name(name, allowed_names=allowed_names))
    )


@mcp_server.resource(
    "settra://artifacts/{artifact}/semantics/model/{path}",
    name="artifact-cube-model-file",
    title="Artifact Cube Model File",
    description=(
        "Mounted Cube YAML model file when all declared models belong to a "
        "artifact. Percent-encode slashes in nested model paths."
    ),
    mime_type="application/yaml",
)
async def cube_model_resource(artifact: str, path: str) -> str:
    """Mounted Cube YAML model file constrained to one artifact."""

    allowed_names = await run_mcp_action(collection_cube_names(artifact))
    file = run_mcp_operation(read_model_file, unquote(path))
    model_names = {
        *file.get("cube_names", []),
        *file.get("view_names", []),
    }

    if not model_names or not model_names.issubset(allowed_names):
        raise ValueError("Cube model file is outside the selected artifact")

    return file["content"]
