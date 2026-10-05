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

        if scope.get("type") in {"http", "websocket"} and path == "":
            scope = {
                **scope,
                "path": "/",
                "raw_path": b"/",
            }

        await self.app(scope, receive, send)


mcp_server = TrackedFastMCP(
    PRODUCT_NAME,
    instructions=(
        f"{PRODUCT_NAME} makes connected sheet data available to automated "
        "agents through a Cube semantic layer. For artifact-scoped work on the global MCP URL, "
        "start with list_artifacts, ask the user which artifact to use, call "
        "get_artifact_context once, and keep passing that artifact slug for the "
        "conversation. Source creation and source configuration are user-only "
        "actions in the signed-in browser under Data > Sources. If asked to create "
        "or configure a source, direct the user there; after the source is saved, "
        "list_connections can find it and get_connection_metadata can describe its "
        "synchronized schema even before it belongs to an artifact. Prefer existing compiled cubes and "
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
        "has explicitly requested or approved the change. Delete an artifact-owned "
        "overlay only after explicit user approval and after calling "
        "preview_dependency_impact for its exact dependency graph. Call the same "
        "preview before removing a source from an artifact, and use its conservative "
        "source-schema action before user-managed source configuration changes. "
        "Before creating or updating an overlay, "
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
        "empty optional artifact. Tool results do not echo request arguments; "
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
    except ApplicationError as exc:
        raise ValueError(exc.message) from exc
    except HTTPException as exc:
        raise ValueError(str(exc.detail)) from exc


def json_text(payload: Any) -> str:
    return json.dumps(jsonable(payload), indent=2, sort_keys=True)
