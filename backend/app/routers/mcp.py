import os
import json

from typing import Any
from collections.abc import Awaitable, Callable

from fastapi import HTTPException
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.cube.client import CubeAPIError, load_cube_meta
from app.cube.model import read_model_file
from app.cube.query import (
    cube_by_name,
    execute_cube_query_payload,
    semantic_catalog,
)
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
        "to execute Cube REST query JSON against trusted business-app cubes."
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
