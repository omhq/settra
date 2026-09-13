import json

from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from app.collection_service import collection_cube_names
from app.cube.client import CubeAPIError
from app.cube.query import (
    execute_cube_query_payload,
    normalize_cube_query_payload,
    sentinel_mcp_cube_query,
)
from app.semantic.query import referenced_cube_names
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
async def query_cube(
    collection: Annotated[
        str,
        Field(description="Selected collection slug from list_collections."),
    ],
    query: dict[str, Any],
) -> dict[str, Any]:
    """Execute a Cube semantic query."""

    if not isinstance(query, dict):
        raise ValueError(
            "query_cube accepts one Cube query object. Arrays are not independent "
            "batch execution; use separate tool calls."
        )

    allowed_names = await run_mcp_action(collection_cube_names(collection))
    return await run_mcp_action(
        _execute_bounded_cube_query(query, allowed_names=allowed_names)
    )


async def _execute_bounded_cube_query(
    query: dict[str, Any],
    *,
    allowed_names: set[str],
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

    referenced_names = referenced_cube_names(normalized_query)
    unavailable_names = sorted(referenced_names - allowed_names)

    if not referenced_names:
        raise ValueError(
            "Cube query must reference at least one collection cube member."
        )
    if unavailable_names:
        raise ValueError(
            "Cube query references models outside the selected collection: "
            + ", ".join(unavailable_names)
        )

    executable_query, requested_limit, offset = sentinel_mcp_cube_query(
        normalized_query
    )

    try:
        response = await execute_cube_query_payload({"query": executable_query})
    except CubeAPIError as exc:
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
    exc: CubeAPIError,
) -> dict[str, Any]:
    source_message = exc.message.strip()
    retryable = exc.retryable
    code, message, agent_action = _classify_cube_query_failure(
        source_message,
        retryable=retryable,
    )

    if code in {"cube_access_denied", "cube_not_found", "invalid_cube_query"}:
        retryable = False

    return {
        "code": code,
        "message": message,
        "cubes": sorted(referenced_cube_names(query)),
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
            "The cube is compiled, but Cube cannot access its PostgreSQL snapshot.",
            "Tell the user which cube is unavailable and include the source error. "
            "Recommend checking the PostgreSQL destination and Cube database "
            "credentials. Do not infer or fabricate query results.",
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
            "and do not treat this as a source permission failure.",
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
