import os
import json
import time
import asyncio
import logging

from collections.abc import Awaitable, Callable
from typing import Any

import yaml

from fastapi import HTTPException
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.common.product import PRODUCT_NAME
from app.auth import current_organization_id, require_organization_write_access
from app.cube.client import CubeAPIError, load_cube_meta
from app.cube.model import (
    list_semantic_overlay_files,
    read_semantic_overlay_file,
)
from app.cube.projection import (
    OverlayListItemProjectionInput,
    OverlayListProjectionInput,
    OverlayProjectionInput,
    semantic_response_projector,
)
from app.mcp_request_log import payload_size, record_mcp_request, tool_result_size
from app.utils import jsonable

Receive = Callable[[], Awaitable[Any]]
Send = Callable[[Any], Awaitable[None]]
ASGIApp = Callable[[dict[str, Any], Receive, Send], Awaitable[None]]

SEMANTIC_OVERLAY_COMPILE_ATTEMPTS = int(
    os.getenv("SEMANTIC_OVERLAY_COMPILE_ATTEMPTS", "10")
)
SEMANTIC_OVERLAY_COMPILE_SLEEP_SECONDS = float(
    os.getenv("SEMANTIC_OVERLAY_COMPILE_SLEEP_SECONDS", "0.5")
)
OVERLAY_MANIFEST_FIELDS = (
    "purpose",
    "requirement",
    "grain",
    "assumptions",
    "relationships",
    "metrics",
    "evidence",
    "validation",
    "approval",
)
REQUIRED_OVERLAY_MANIFEST_FIELDS = (
    "purpose",
    "requirement",
    "grain",
    "assumptions",
    "evidence",
)
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
    "update_semantic_overlay",
    "validate_semantic_overlay",
}

semantic_overlay_write_lock = asyncio.Lock()
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
        "and may be prefixed with its slug. When sheet-specific semantics are missing, "
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


def overlay_path(path: str) -> str:
    normalized = os.path.normpath(path.strip().lstrip("/"))

    if normalized in {"", "."} or normalized.startswith("../"):
        raise ValueError("Invalid overlay path")

    if normalized.startswith("overlays/"):
        normalized = normalized.removeprefix("overlays/")

    if not normalized.endswith((".yaml", ".yml")):
        raise ValueError("Overlay path must end in .yaml or .yml")

    return f"overlays/{normalized}"


def generated_overlay_path(path: str) -> str:
    normalized = os.path.normpath(path.strip().lstrip("/"))

    if normalized.startswith("overlays/"):
        normalized = normalized.removeprefix("overlays/")

    tenant_prefix = f"generated/organizations/{current_organization_id()}/"
    if normalized.startswith("generated/organizations/"):
        if not normalized.startswith(tenant_prefix):
            raise ValueError("Semantic overlay is outside the active organization")
    else:
        normalized = normalized.removeprefix("generated/")
        normalized = f"{tenant_prefix}{normalized}"

    normalized_path = overlay_path(normalized)

    if not normalized_path.startswith("overlays/generated/"):
        raise ValueError("Only generated semantic overlays can be modified")

    return normalized_path


def parse_overlay_yaml(content: str) -> dict[str, Any]:
    try:
        parsed = yaml.safe_load(content) if content.strip() else {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid overlay YAML: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Overlay YAML must contain a mapping")

    return parsed


def declared_model_names(parsed: dict[str, Any]) -> list[str]:
    names: list[str] = []

    for key in ("cubes", "views"):
        items = parsed.get(key)

        if not isinstance(items, list):
            continue

        for item in items:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                names.append(item["name"])

    return names


def compiled_cube_names(meta: dict[str, Any]) -> set[str]:
    cubes = meta.get("cubes") if isinstance(meta, dict) else []

    return {
        cube["name"]
        for cube in cubes
        if isinstance(cube, dict) and isinstance(cube.get("name"), str)
    }


def semantic_overlay_manifest(parsed: dict[str, Any]) -> dict[str, Any]:
    models: list[dict[str, Any]] = []

    for model_type in ("cubes", "views"):
        items = parsed.get(model_type)

        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue

            settra_meta = _settra_meta(item)
            manifest = {
                field: settra_meta[field]
                for field in OVERLAY_MANIFEST_FIELDS
                if field in settra_meta
            }
            missing_fields = [
                field
                for field in REQUIRED_OVERLAY_MANIFEST_FIELDS
                if field not in manifest
            ]

            models.append(
                {
                    "name": item["name"],
                    "type": model_type.removesuffix("s"),
                    "title": item.get("title"),
                    "description": item.get("description"),
                    "manifest": manifest or None,
                    "manifest_complete": not missing_fields,
                    "missing_manifest_fields": missing_fields,
                }
            )

    model_manifests = [model for model in models if model["manifest"]]

    if models and all(model["manifest_complete"] for model in models):
        status = "complete"
    elif model_manifests:
        status = "partial"
    else:
        status = "missing"

    first_manifest = model_manifests[0]["manifest"] if model_manifests else {}
    first_model = models[0] if models else {}

    return {
        "status": status,
        "purpose": first_manifest.get("purpose") or first_model.get("description"),
        "requirement": first_manifest.get("requirement"),
        "evidence": first_manifest.get("evidence"),
        "models": models,
    }


def require_complete_overlay_manifest(content: str) -> dict[str, Any]:
    manifest = semantic_overlay_manifest(parse_overlay_yaml(content))

    if manifest.get("status") != "complete":
        missing = sorted(
            {
                field
                for model in manifest.get("models", [])
                for field in model.get("missing_manifest_fields", [])
            }
        )
        detail = f" Missing fields: {', '.join(missing)}." if missing else ""

        raise ValueError(
            "Generated overlays require a complete meta.settra provenance manifest."
            f"{detail}"
        )

    return manifest


def _settra_meta(item: dict[str, Any]) -> dict[str, Any]:
    meta = item.get("meta")

    if not isinstance(meta, dict):
        return {}

    settra = meta.get("settra")

    if not isinstance(settra, dict):
        return {}

    nested = settra.get("overlay")

    return nested if isinstance(nested, dict) else settra


async def list_overlay_details(
    scope: str = "all",
    *,
    allowed_names: set[str] | None = None,
) -> dict[str, Any]:
    normalized_scope = scope.strip().lower().replace("-", "_")
    allowed_scopes = {"all", "generated", "hand_authored"}

    if normalized_scope not in allowed_scopes:
        raise ValueError("scope must be all, generated, or hand_authored")

    files = list_semantic_overlay_files(allowed_names=allowed_names)

    if normalized_scope == "generated":
        files = [
            file for file in files if file.get("source_type") == "generated_overlay"
        ]
    elif normalized_scope == "hand_authored":
        files = [file for file in files if file.get("source_type") == "overlay"]

    meta, metadata_error = await _load_optional_cube_meta()
    compiled_names = compiled_cube_names(meta)
    overlays: list[OverlayListItemProjectionInput] = []

    for file in files:
        detail = read_semantic_overlay_file(str(file["path"]))
        parsed, parse_error = _parse_overlay_for_discovery(str(detail["content"]))
        names = [*file.get("cube_names", []), *file.get("view_names", [])]
        if allowed_names is not None and (
            not names or not set(names).issubset(allowed_names)
        ):
            continue
        overlays.append(
            OverlayListItemProjectionInput(
                path=str(file["path"]),
                model_names=names,
                manifest=semantic_overlay_manifest(parsed),
                compile_status=_overlay_compile_status(
                    file,
                    compiled_names,
                    metadata_error,
                ),
                parse_error=parse_error,
            )
        )

    return semantic_response_projector.overlay_list(
        OverlayListProjectionInput(
            overlays=overlays,
            error=metadata_error,
        )
    )


async def get_overlay_detail(
    path: str,
    *,
    allowed_names: set[str] | None = None,
) -> dict[str, Any]:
    normalized = overlay_path(path)
    file = read_semantic_overlay_file(normalized)
    parsed, parse_error = _parse_overlay_for_discovery(str(file["content"]))
    meta, metadata_error = await _load_optional_cube_meta()
    names = [*file.get("cube_names", []), *file.get("view_names", [])]
    if allowed_names is not None and (
        not names or not set(names).issubset(allowed_names)
    ):
        raise ValueError("Semantic overlay is outside the selected collection")
    manifest = semantic_overlay_manifest(parsed)
    compile_status = _overlay_compile_status(
        file,
        compiled_cube_names(meta),
        metadata_error,
    )

    return semantic_response_projector.overlay(
        OverlayProjectionInput(
            path=str(file["path"]),
            content=str(file["content"]),
            model_names=names,
            manifest=manifest,
            compile_status=compile_status,
            parse_error=parse_error,
        )
    )


def _parse_overlay_for_discovery(
    content: str,
) -> tuple[dict[str, Any], str | None]:
    try:
        return parse_overlay_yaml(content), None
    except ValueError as exc:
        return {}, str(exc)


async def _load_optional_cube_meta() -> tuple[dict[str, Any], str | None]:
    try:
        return await load_cube_meta(), None
    except CubeAPIError as exc:
        return {}, exc.message


def _overlay_compile_status(
    file: dict[str, Any],
    compiled_names: set[str],
    metadata_error: str | None,
) -> dict[str, Any]:
    names = [*file.get("cube_names", []), *file.get("view_names", [])]
    missing_names = sorted(set(names) - compiled_names)
    compiled_models = sorted(set(names) & compiled_names)

    if metadata_error:
        status = "unknown"
    elif not names:
        status = "empty"
    elif not missing_names:
        status = "compiled"
    elif compiled_models:
        status = "partial"
    else:
        status = "not_compiled"

    return {
        "connected": metadata_error is None,
        "status": status,
        "compiled": status == "compiled",
        "compiled_names": compiled_models,
        "missing_names": missing_names,
        "error": metadata_error,
    }


async def wait_for_compiled_model_names(
    expected_names: list[str],
    *,
    after_compiler_id: str | None = None,
    validation_token: str | None = None,
) -> dict[str, Any]:
    expected = {name for name in expected_names if isinstance(name, str)}
    status: dict[str, Any] = {
        "connected": False,
        "compiled": False,
        "cube_count": 0,
        "missing_names": sorted(expected),
        "compiler_id": None,
        "validation_token_seen": False,
        "error": None,
    }

    for attempt in range(SEMANTIC_OVERLAY_COMPILE_ATTEMPTS):
        try:
            meta = await load_cube_meta()
            cubes = meta.get("cubes") if isinstance(meta, dict) else []
            names = {
                cube.get("name")
                for cube in cubes
                if isinstance(cube, dict) and isinstance(cube.get("name"), str)
            }
            missing = sorted(expected - names)
            token_names = {
                cube.get("name")
                for cube in cubes
                if isinstance(cube, dict)
                and isinstance(cube.get("name"), str)
                and _cube_validation_token(cube) == validation_token
            }
            token_missing = sorted(expected - token_names) if validation_token else []
            compiler_id = meta.get("compilerId") if isinstance(meta, dict) else None
            compiler_reloaded = (
                after_compiler_id is None or compiler_id != after_compiler_id
            )
            validation_seen = not validation_token or not token_missing
            status = {
                "connected": True,
                "compiled": (
                    bool(expected)
                    and not missing
                    and compiler_reloaded
                    and validation_seen
                ),
                "cube_count": len(cubes) if isinstance(cubes, list) else 0,
                "missing_names": missing,
                "compiler_id": compiler_id,
                "validation_token_seen": bool(validation_token) and not token_missing,
                "error": None,
            }

            if not missing and compiler_reloaded and validation_seen:
                return status
        except CubeAPIError as exc:
            status = {
                "connected": False,
                "compiled": False,
                "cube_count": 0,
                "missing_names": sorted(expected),
                "compiler_id": None,
                "validation_token_seen": False,
                "error": exc.message,
            }

        if attempt < SEMANTIC_OVERLAY_COMPILE_ATTEMPTS - 1:
            await asyncio.sleep(SEMANTIC_OVERLAY_COMPILE_SLEEP_SECONDS)

    return status


def _cube_validation_token(cube: dict[str, Any]) -> str | None:
    meta = cube.get("meta")

    if not isinstance(meta, dict):
        return None

    settra = meta.get("settra")

    if not isinstance(settra, dict):
        return None

    token = settra.get("validation_token")

    return token if isinstance(token, str) else None


async def wait_for_removed_model_names(
    removed_names: list[str],
) -> dict[str, Any]:
    removed = {name for name in removed_names if isinstance(name, str)}
    status: dict[str, Any] = {
        "connected": False,
        "removed": False,
        "cube_count": 0,
        "remaining_names": sorted(removed),
        "error": None,
    }

    for attempt in range(SEMANTIC_OVERLAY_COMPILE_ATTEMPTS):
        try:
            meta = await load_cube_meta()
            cubes = meta.get("cubes") if isinstance(meta, dict) else []
            names = {
                cube.get("name")
                for cube in cubes
                if isinstance(cube, dict) and isinstance(cube.get("name"), str)
            }
            remaining = sorted(removed & names)
            status = {
                "connected": True,
                "removed": not remaining,
                "cube_count": len(cubes) if isinstance(cubes, list) else 0,
                "remaining_names": remaining,
                "error": None,
            }

            if not remaining:
                return status
        except CubeAPIError as exc:
            status = {
                "connected": False,
                "removed": False,
                "cube_count": 0,
                "remaining_names": sorted(removed),
                "error": exc.message,
            }

        if attempt < SEMANTIC_OVERLAY_COMPILE_ATTEMPTS - 1:
            await asyncio.sleep(SEMANTIC_OVERLAY_COMPILE_SLEEP_SECONDS)

    return status
