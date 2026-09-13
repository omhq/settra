import os
import json
import time
import logging

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.common.product import PRODUCT_NAME
from app.auth import current_organization_id, require_organization_write_access
from app.cube.client import CubeAPIError
from app.errors import ApplicationError
from app.mcp_request_log import payload_size, record_mcp_request, tool_result_size
from app.utils import jsonable

Receive = Callable[[], Awaitable[Any]]
Send = Callable[[Any], Awaitable[None]]
ASGIApp = Callable[[dict[str, Any], Receive, Send], Awaitable[None]]

COLLECTION_SCOPED_TOOLS = {
    "create_semantic_overlay",
    "get_collection_context",
    "get_connection_metadata",
    "get_cube",
    "get_cube_meta",
    "get_semantic_overlay",
    "list_connections",
    "list_cubes",
    "list_semantic_overlays",
    "profile_connection_table",
    "query_cube",
    "sample_connection_table",
    "save_semantic_overlay",
    "sync_connection",
    "update_semantic_overlay",
    "validate_semantic_overlay",
}

logger = logging.getLogger(__name__)


def _csv_env(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


class TrackedFastMCP(FastMCP):
    async def call_tool(self, name: str, arguments: dict[str, Any]):
        started = time.perf_counter()
        request_id, client_id = self._request_identity()
        request_bytes = payload_size({"name": name, "arguments": arguments})

        try:
            result = await super().call_tool(name, arguments)
        except Exception as exc:
            await self._record_request(
                request_id=request_id,
                client_id=client_id,
                kind="tool",
                name=name,
                status="error",
                started=started,
                request_bytes=request_bytes,
                response_bytes=payload_size({"error": str(exc)}),
                error_type=exc.__class__.__name__,
            )
            raise

        await self._record_request(
            request_id=request_id,
            client_id=client_id,
            kind="tool",
            name=name,
            status="success",
            started=started,
            request_bytes=request_bytes,
            response_bytes=payload_size(result),
            response_token_bytes=tool_result_size(result),
        )
        return result

    async def read_resource(self, uri):
        started = time.perf_counter()
        request_id, client_id = self._request_identity()
        name = str(uri)
        request_bytes = payload_size({"uri": name})

        try:
            result = await super().read_resource(uri)
        except Exception as exc:
            await self._record_request(
                request_id=request_id,
                client_id=client_id,
                kind="resource",
                name=name,
                status="error",
                started=started,
                request_bytes=request_bytes,
                response_bytes=payload_size({"error": str(exc)}),
                error_type=exc.__class__.__name__,
            )
            raise

        await self._record_request(
            request_id=request_id,
            client_id=client_id,
            kind="resource",
            name=name,
            status="success",
            started=started,
            request_bytes=request_bytes,
            response_bytes=payload_size(result),
        )
        return result

    def _request_identity(self) -> tuple[str | None, str | None]:
        try:
            context = self.get_context()

            return context.request_id, context.client_id
        except Exception:
            return None, None

    async def _record_request(
        self,
        *,
        request_id: str | None,
        client_id: str | None,
        kind: str,
        name: str,
        status: str,
        started: float,
        request_bytes: int,
        response_bytes: int,
        response_token_bytes: int | None = None,
        error_type: str | None = None,
    ) -> None:
        try:
            await record_mcp_request(
                request_id=request_id,
                client_id=client_id,
                kind=kind,
                name=name,
                status=status,
                duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
                request_bytes=request_bytes,
                response_bytes=response_bytes,
                response_token_bytes=response_token_bytes,
                error_type=error_type,
            )
        except Exception:
            logger.exception("Could not record MCP request metric")


class RootPathAsSlash:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Receive,
        send: Send,
    ) -> None:
        path = str(scope.get("path") or "")
        collection = _collection_from_mcp_path(path)

        if scope.get("type") in {"http", "websocket"} and (
            path == "" or collection is not None
        ):
            scope = {
                **scope,
                "path": "/",
                "raw_path": b"/",
            }

        if collection and scope.get("type") == "http" and scope.get("method") == "POST":
            receive, content_length = await _collection_scoped_receive(
                receive,
                collection,
            )
            if content_length is not None:
                headers = [
                    (key, value)
                    for key, value in scope.get("headers", [])
                    if key.lower() != b"content-length"
                ]
                headers.append((b"content-length", str(content_length).encode("ascii")))
                scope = {**scope, "headers": headers}

        await self.app(scope, receive, send)


def _collection_from_mcp_path(path: str) -> str | None:
    normalized = path.strip("/")
    parts = normalized.split("/")

    if len(parts) == 3 and parts[0] == "mcp":
        parts = parts[1:]

    if len(parts) != 2 or parts[0] != "collections":
        return None

    slug = parts[1].strip()

    if not slug or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in slug
    ):
        return None

    return slug


async def _collection_scoped_receive(
    receive: Receive,
    collection: str,
) -> tuple[Receive, int | None]:
    chunks: list[bytes] = []

    while True:
        message = await receive()
        if message.get("type") != "http.request":
            return _replay_receive(message, receive), None

        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            break

    body = b"".join(chunks)

    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _replay_receive({"type": "http.request", "body": body}, receive), len(
            body
        )

    scoped = _inject_collection_argument(payload, collection)
    scoped_body = json.dumps(scoped, separators=(",", ":")).encode("utf-8")
    return (
        _replay_receive({"type": "http.request", "body": scoped_body}, receive),
        len(scoped_body),
    )


def _replay_receive(first: dict[str, Any], receive: Receive) -> Receive:
    sent = False

    async def replay() -> Any:
        nonlocal sent
        if not sent:
            sent = True
            return first
        return await receive()

    return replay


def _inject_collection_argument(payload: Any, collection: str) -> Any:
    if isinstance(payload, list):
        return [_inject_collection_argument(item, collection) for item in payload]
    if not isinstance(payload, dict) or payload.get("method") != "tools/call":
        return payload

    params = payload.get("params")
    if (
        not isinstance(params, dict)
        or params.get("name") not in COLLECTION_SCOPED_TOOLS
    ):
        return payload

    arguments = params.get("arguments")
    arguments = dict(arguments) if isinstance(arguments, dict) else {}
    arguments["collection"] = collection

    return {
        **payload,
        "params": {
            **params,
            "arguments": arguments,
        },
    }


mcp_server = TrackedFastMCP(
    PRODUCT_NAME,
    instructions=(
        f"{PRODUCT_NAME} makes connected sheet data available to automated "
        "agents through a Cube semantic layer. When using the global MCP URL, "
        "start with list_collections, ask the user which collection to use, call "
        "get_collection_context once, and keep passing that collection slug for "
        "the conversation. A collection-pinned MCP URL supplies the slug "
        "automatically. Prefer existing compiled cubes and "
        "measures before creating new semantics. Inspect the relevant source "
        "metadata, bounded source-table samples and profiles, and existing semantic "
        "overlays before interpreting sheet data. Active durable cubes are "
        "generated from each source's latest successful PostgreSQL sync "
        "and may be prefixed with its slug. Only refresh a pipe when the user "
        "explicitly requests or approves it. When sheet-specific semantics are missing, "
        "explain the missing column mapping or metric definition to the user and "
        "identify assumptions that require a business decision. Create the "
        "smallest reusable generated semantic overlay that satisfies the "
        "requirement. Do not create or update semantic overlays unless the user "
        "has explicitly requested or approved the change. Overlay deletion is "
        "available only as a manual admin UI action; ask the user to delete an "
        "overlay when cleanup is needed. Before creating or updating an overlay, "
        "validate its source fields, grain, join "
        "cardinality, metric definitions, currency and time handling, header "
        "mapping, and missing values. Preserve purpose, originating user "
        "requirement, approved assumptions, evidence, and validation results in "
        "meta.settra. Use meta.settra.semantic_type='business_date' for "
        "timezone-neutral date-only members. After writing an overlay, verify "
        "that it compiles and successfully answers the intended question. Never "
        "silently invent entity relationships or business definitions. Use Cube "
        "REST query JSON for execution; do not use raw PostgreSQL SQL. Tool "
        "responses are compact: an omitted field means its normal default, "
        "including no error, public and visible access, a non-primary key, or an "
        "empty optional collection. Tool results do not echo request arguments; "
        "use the original tool call for search, include, limit, and cursor "
        "values. Top-level pagination returns total and next_cursor. The nested "
        "column_page from get_connection_metadata instead returns total and "
        "next_column_cursor, matching its column_cursor input."
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        allowed_hosts=_csv_env("MCP_ALLOWED_HOSTS"),
        allowed_origins=_csv_env("MCP_ALLOWED_ORIGINS"),
    ),
)


async def run_mcp_action(awaitable: Any) -> Any:
    try:
        return await awaitable
    except ApplicationError as exc:
        raise ValueError(exc.message) from exc
    except HTTPException as exc:
        raise ValueError(str(exc.detail)) from exc
    except CubeAPIError as exc:
        raise ValueError(exc.message) from exc


def run_mcp_operation(
    operation: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    try:
        return operation(*args, **kwargs)
    except ApplicationError as exc:
        raise ValueError(exc.message) from exc
    except HTTPException as exc:
        raise ValueError(str(exc.detail)) from exc
    except CubeAPIError as exc:
        raise ValueError(exc.message) from exc


def require_mcp_write_access() -> None:
    try:
        require_organization_write_access()
    except HTTPException as exc:
        raise ValueError(str(exc.detail)) from exc


def json_text(payload: Any) -> str:
    return json.dumps(jsonable(payload), indent=2, sort_keys=True)
