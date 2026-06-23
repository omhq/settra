import os
import json

from typing import Any
from collections.abc import Awaitable, Callable

import aiosqlite

from fastapi import HTTPException
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.cube.client import CubeAPIError, load_cube_meta
from app.cube.model import read_model_file, save_model_file
from app.cube.query import (
    cube_by_name,
    execute_cube_query_payload,
    semantic_catalog,
)
from app.db import DB_PATH
from app.routers.connection_metadata import generate_connection_metadata
from app.utils import jsonable

Receive = Callable[[], Awaitable[Any]]
Send = Callable[[Any], Awaitable[None]]
ASGIApp = Callable[[dict[str, Any], Receive, Send], Awaitable[None]]

DEFAULT_ALLOWED_HOSTS = [
    "127.0.0.1",
    "127.0.0.1:*",
    "localhost",
    "localhost:*",
    "[::1]",
    "[::1]:*",
]

DEFAULT_ALLOWED_ORIGINS = [
    "http://127.0.0.1",
    "http://127.0.0.1:*",
    "http://localhost",
    "http://localhost:*",
    "http://[::1]",
    "http://[::1]:*",
]


def _csv_env(name: str, default: list[str]) -> list[str]:
    configured = [
        item.strip() for item in os.getenv(name, "").split(",") if item.strip()
    ]

    return configured or default


class _RootPathAsSlash:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Receive,
        send: Send,
    ) -> None:
        if scope.get("type") in {"http", "websocket"} and scope.get("path") == "":
            scope = {
                **scope,
                "path": "/",
                "raw_path": b"/",
            }

        await self.app(scope, receive, send)


mcp_server = FastMCP(
    "Settra",
    instructions=(
        "Use list_cubes to inspect the Cube semantic model and query_cube "
        "to execute Cube REST query JSON against trusted business-app cubes. "
        "For user-specific worksheet or cross-app models, inspect saved "
        "connections and write Cube YAML overlays under /cube/conf/model/overlays."
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        allowed_hosts=_csv_env("MCP_ALLOWED_HOSTS", DEFAULT_ALLOWED_HOSTS),
        allowed_origins=_csv_env("MCP_ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS),
    ),
)


@mcp_server.tool(
    name="list_cubes",
    title="List Cubes",
    description=(
        "List compiled Cube cubes, views, measures, dimensions, segments, "
        "and joins exposed by Settra."
    ),
)
async def list_cubes(search: str | None = None) -> dict[str, Any]:
    """List compiled Cube semantic metadata."""

    return await _run_mcp_action(semantic_catalog(search=search))


@mcp_server.tool(
    name="get_cube",
    title="Get Cube",
    description="Fetch full Cube metadata for one compiled cube or view.",
)
async def get_cube(name: str) -> dict[str, Any]:
    """Fetch metadata for a single cube or view."""

    if not name.strip():
        raise ValueError("name is required")

    return await _run_mcp_action(cube_by_name(name))


@mcp_server.tool(
    name="query_cube",
    title="Query Cube",
    description=(
        "Execute a Cube REST query. Pass Cube query JSON using measures, "
        "dimensions, filters, timeDimensions, segments, limit, offset, "
        "order, and timezone."
    ),
)
async def query_cube(query: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    """Execute a Cube semantic query."""

    return await _run_mcp_action(execute_cube_query_payload({"query": query}))


@mcp_server.tool(
    name="get_cube_meta",
    title="Get Cube Metadata",
    description="Fetch the raw Cube /v1/meta metadata payload.",
)
async def get_cube_meta() -> dict[str, Any]:
    """Fetch the raw Cube metadata payload."""

    return await _run_mcp_action(load_cube_meta())


@mcp_server.tool(
    name="list_connections",
    title="List Connections",
    description=(
        "List saved Settra connections without secrets. Use this before generating "
        "user-specific semantic overlays."
    ),
)
async def list_connections() -> list[dict[str, Any]]:
    """List non-secret saved connections."""

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("""
            SELECT id, name, slug, plugin, status, created_at
            FROM connections
            ORDER BY created_at DESC
            """) as cur:
            rows = await cur.fetchall()

    return [dict(row) for row in rows]


@mcp_server.tool(
    name="get_connection_metadata",
    title="Get Connection Metadata",
    description=(
        "Refresh and return non-secret Steampipe metadata for one saved connection. "
        "For Google Sheets, this includes worksheet tables synthesized from header "
        "rows, such as target_revenue."
    ),
)
async def get_connection_metadata(connection_id: int) -> dict[str, Any]:
    """Fetch live non-secret schema metadata for a saved connection."""

    return await _run_mcp_action(generate_connection_metadata(connection_id))


@mcp_server.tool(
    name="save_semantic_overlay",
    title="Save Semantic Overlay",
    description=(
        "Create or update a Cube YAML model file under /cube/conf/model/overlays. "
        "Use generated/*.yaml for user-specific files that should not be committed."
    ),
)
async def save_semantic_overlay(path: str, content: str) -> dict[str, Any]:
    """Save a Cube YAML overlay file."""

    normalized = _overlay_path(path)

    return save_model_file(normalized, content)


@mcp_server.resource(
    "settra://semantics/meta",
    name="cube-meta",
    title="Cube Metadata",
    description="Raw compiled Cube /v1/meta metadata.",
    mime_type="application/json",
)
async def cube_meta_resource() -> str:
    """Raw compiled Cube metadata."""

    return _json_text(await _run_mcp_action(load_cube_meta()))


@mcp_server.resource(
    "settra://semantics/cubes",
    name="cube-catalog",
    title="Cube Catalog",
    description="Summarized cubes, measures, dimensions, segments, and joins.",
    mime_type="application/json",
)
async def cube_catalog_resource() -> str:
    """Summarized compiled Cube catalog."""

    return _json_text(await _run_mcp_action(semantic_catalog()))


@mcp_server.resource(
    "settra://semantics/cubes/{name}",
    name="cube",
    title="Cube Metadata",
    description="Compiled Cube metadata by cube or view name.",
    mime_type="application/json",
)
async def cube_resource(name: str) -> str:
    """Compiled Cube metadata by name."""

    return _json_text(await _run_mcp_action(cube_by_name(name)))


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


mcp_app = _RootPathAsSlash(mcp_server.streamable_http_app())


async def _run_mcp_action(awaitable: Any) -> Any:
    try:
        return await awaitable
    except HTTPException as exc:
        raise ValueError(str(exc.detail)) from exc
    except CubeAPIError as exc:
        raise ValueError(exc.message) from exc


def _json_text(payload: Any) -> str:
    return json.dumps(jsonable(payload), indent=2, sort_keys=True)


def _overlay_path(path: str) -> str:
    normalized = os.path.normpath(path.strip().lstrip("/"))

    if normalized in {"", "."} or normalized.startswith("../"):
        raise ValueError("Invalid overlay path")

    if normalized.startswith("overlays/"):
        normalized = normalized.removeprefix("overlays/")

    if not normalized.endswith((".yaml", ".yml")):
        raise ValueError("Overlay path must end in .yaml or .yml")

    return f"overlays/{normalized}"
