import json

from typing import Any

from fastapi import HTTPException
from mcp.types import ToolAnnotations

from app.cube.query import (
    execute_cube_query_payload,
    normalize_cube_query_payload,
    sentinel_mcp_cube_query,
)
from app.cube.projection import (
    QueryResultProjectionInput,
    semantic_response_projector,
)

from .common import mcp_server, run_mcp_action

PERMISSION_ERROR_MARKERS = (
    "access denied",
    "forbidden",
    "invalid access token",
    "invalid api key",
    "do not have permission",
    "insufficient permission",
    "insufficient permissions",
    "insufficient scope",
    "missing required scope",
    "missing scope",
    "not authorized",
    "permission denied",
    "status code 401",
    "status code 403",
    "unauthorized",
)
CUBE_NOT_FOUND_MARKERS = (
    "cube not found",
    "does not exist in the schema",
    "unknown cube",
)
INVALID_QUERY_MARKERS = (
    "can't find member",
    "cannot find member",
    "member not found",
    "unknown member",
)
MAX_SOURCE_ERROR_LENGTH = 800


@mcp_server.tool(
    name="query_cube",
    title="Query Cube",
    description=(
        "Execute a bounded Cube REST query against existing compiled semantics. "
        "Pass Cube query JSON using measures, dimensions, filters, timeDimensions, "
        "segments, limit, offset, order, and timezone. Results contain one data "
        "array plus row_count, has_more, limit, offset, next_offset, and an optional "
        "total when the query explicitly sets total=true. Pagination uses one extra "
        "sentinel row instead of requesting an exact total. Set a stable order when "
        "paging. Cube execution internals are omitted. Annotated numeric values are "
        "returned as compact JSON numbers, and date-only/business-date time members "
        "are returned as YYYY-MM-DD to avoid timezone display shifts. This tool "
        "accepts exactly one query object: arrays, Cube data blending, and "
        "independent batch execution are not supported. Use separate tool calls for "
        "independent queries. limit defaults to 100 rows and is capped at 500. Use "
        "this to answer questions and verify saved overlays; raw SQL is not accepted. "
        "When execution fails, the tool error identifies the referenced cubes, "
        "classifies access, query, and transient failures when possible, preserves "
        "a bounded source error, and tells the agent what to surface to the user."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def query_cube(query: dict[str, Any]) -> dict[str, Any]:
    """Execute a Cube semantic query."""

    if not isinstance(query, dict):
        raise ValueError(
            "query_cube accepts one Cube query object. Arrays are not independent "
            "batch execution; use separate tool calls."
        )

    return await run_mcp_action(_execute_bounded_cube_query(query))


async def _execute_bounded_cube_query(
    query: dict[str, Any],
) -> dict[str, Any]:
    """Normalizes, executes, and projects the actual query execution.

    Args:
        query (dict[str, Any]): The Cube query object to execute.

    Returns:
        dict[str, Any]: The projected query result.
    """
    normalized_query = normalize_cube_query_payload({"query": query})

    if not isinstance(normalized_query, dict):
        raise ValueError("query_cube accepts exactly one Cube query object.")

    executable_query, requested_limit, offset = sentinel_mcp_cube_query(
        normalized_query
    )

    try:
        response = await execute_cube_query_payload({"query": executable_query})
    except HTTPException as exc:
        detail = _cube_query_failure_detail(normalized_query, exc)
        raise ValueError(json.dumps(detail, separators=(",", ":"))) from exc

    return semantic_response_projector.query_result(
        QueryResultProjectionInput(
            response=response,
            limit=requested_limit,
            offset=offset,
        )
    )


def _cube_query_failure_detail(
    query: dict[str, Any],
    exc: HTTPException,
) -> dict[str, Any]:
    source_detail = exc.detail if isinstance(exc.detail, dict) else {}
    source_message = str(source_detail.get("message") or exc.detail or "").strip()
    retryable = bool(source_detail.get("retryable"))
    code, message, agent_action = _classify_cube_query_failure(
        source_message,
        retryable=retryable,
    )

    if code in {"cube_access_denied", "cube_not_found", "invalid_cube_query"}:
        retryable = False

    return {
        "code": code,
        "message": message,
        "cubes": _cube_names_from_query(query),
        "retryable": retryable,
        "source_error": source_message[:MAX_SOURCE_ERROR_LENGTH],
        "agent_action": agent_action,
    }


def _classify_cube_query_failure(
    source_message: str,
    *,
    retryable: bool,
) -> tuple[str, str, str]:
    normalized = source_message.lower()

    if any(marker in normalized for marker in PERMISSION_ERROR_MARKERS):
        return (
            "cube_access_denied",
            "The cube is compiled, but its connection credential appears unable "
            "to access the requested source.",
            "Tell the user which cube is unavailable and include the source error. "
            "Recommend granting the required provider permission or updating and "
            "retrying the connection. Do not infer or fabricate query results.",
        )

    if any(marker in normalized for marker in CUBE_NOT_FOUND_MARKERS):
        return (
            "cube_not_found",
            "The requested cube is not available in the compiled semantic layer.",
            "Refresh discovery with list_cubes and use get_cube before retrying. "
            "Tell the user if the expected cube is absent.",
        )

    if any(marker in normalized for marker in INVALID_QUERY_MARKERS):
        return (
            "invalid_cube_query",
            "The cube query references a member that is not available.",
            "Inspect the current cube with get_cube, correct the Cube member names, "
            "and do not treat this as a provider permission failure.",
        )

    if retryable:
        return (
            "cube_temporarily_unavailable",
            "The cube source is temporarily unavailable.",
            "Tell the user the source could not be reached and that the failure is "
            "retryable. Retry later without inferring or fabricating results.",
        )

    return (
        "cube_query_failed",
        "The cube exists, but its query could not be executed.",
        "Surface the cube name and source error to the user. Recommend checking "
        "connection permissions and health before retrying, and do not infer or "
        "fabricate results.",
    )


def _cube_names_from_query(query: dict[str, Any]) -> list[str]:
    cubes: set[str] = set()

    def add_member(value: Any) -> None:
        if not isinstance(value, str) or "." not in value:
            return

        cube_name = value.split(".", 1)[0].strip()

        if cube_name:
            cubes.add(cube_name)

    for key in ("measures", "dimensions", "segments"):
        members = query.get(key)

        if isinstance(members, list):
            for member in members:
                add_member(member)

    time_dimensions = query.get("timeDimensions")

    if isinstance(time_dimensions, list):
        for item in time_dimensions:
            if isinstance(item, dict):
                add_member(item.get("dimension"))

    def walk_filters(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"dimension", "member"}:
                    add_member(item)
                else:
                    walk_filters(item)
        elif isinstance(value, list):
            for item in value:
                walk_filters(item)

    walk_filters(query.get("filters"))

    order = query.get("order")

    if isinstance(order, dict):
        for member in order:
            add_member(member)
    elif isinstance(order, list):
        for item in order:
            if isinstance(item, (list, tuple)) and item:
                add_member(item[0])

    return sorted(cubes)
