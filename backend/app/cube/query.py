import re

from typing import Any

from fastapi import HTTPException

from app.cube.client import CubeAPIError, load_cube_meta, load_cube_query
from app.cube.model import authored_definition_index, source_definition_index
from app.cube.projection import (
    CubeCatalogProjectionInput,
    CubeMetaProjectionInput,
    CubeProjectionInput,
    semantic_response_projector,
)

CubeQueryPayload = dict[str, Any] | list[dict[str, Any]]

CUBE_QUERY_KEYS = {
    "measures",
    "dimensions",
    "filters",
    "timeDimensions",
    "segments",
    "limit",
    "total",
    "offset",
    "order",
    "timezone",
    "renewQuery",
    "ungrouped",
    "joinHints",
}
CUBE_META_COLLECTIONS = (
    "measures",
    "dimensions",
    "segments",
    "joins",
    "hierarchies",
    "folders",
    "nestedFolders",
)
CUBE_CATALOG_COLLECTIONS = ("measures", "dimensions", "segments", "joins")
DEFAULT_CUBE_CATALOG_LIMIT = 5
MAX_CUBE_CATALOG_LIMIT = 5
DEFAULT_CUBE_CATALOG_MEMBER_LIMIT = 10
MAX_CUBE_CATALOG_MEMBER_LIMIT = 10
DEFAULT_CUBE_META_LIMIT = 5
MAX_CUBE_META_LIMIT = 10
DEFAULT_CUBE_META_MEMBER_LIMIT = 10
MAX_CUBE_META_MEMBER_LIMIT = 25
DEFAULT_MCP_CUBE_QUERY_LIMIT = 100
MAX_MCP_CUBE_QUERY_LIMIT = 500
MAX_MCP_CUBE_BLEND_QUERIES = 10
SEARCH_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "by",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "show",
    "the",
    "to",
    "with",
}


def normalize_cube_query_payload(payload: Any) -> CubeQueryPayload:
    if isinstance(payload, dict) and "sql" in payload:
        raise HTTPException(
            status_code=400,
            detail=(
                "Raw SQL execution has been replaced by Cube semantic queries. "
                "Send Cube REST query JSON in a 'query' field, or as the request body."
            ),
        )

    if isinstance(payload, dict) and "query" in payload:
        return _normalize_cube_query(payload["query"])

    return _normalize_cube_query(payload)


def cube_api_error_detail(exc: CubeAPIError) -> dict[str, Any]:
    return {
        "message": exc.message,
        "retryable": exc.status_code in {408, 429, 500, 502, 503, 504},
    }


async def execute_cube_query_payload(payload: Any) -> dict[str, Any]:
    query = normalize_cube_query_payload(payload)

    try:
        cube_response = await load_cube_query(query)
    except CubeAPIError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=cube_api_error_detail(exc),
        ) from exc

    result: dict[str, Any] = {
        "ok": True,
        "query": query,
        "cube": cube_response,
    }

    if "data" in cube_response:
        result["data"] = cube_response["data"]
        result["result"] = cube_response["data"]

    return result


def bounded_mcp_cube_query(query: CubeQueryPayload) -> CubeQueryPayload:
    """Apply explicit row limits to each query submitted through MCP."""

    if isinstance(query, list):
        return [_bounded_mcp_cube_query_item(item) for item in query]

    return _bounded_mcp_cube_query_item(query)


def _bounded_mcp_cube_query_item(query: dict[str, Any]) -> dict[str, Any]:
    bounded = dict(query)
    limit = bounded.get("limit")

    if limit is None:
        bounded["limit"] = DEFAULT_MCP_CUBE_QUERY_LIMIT
    elif (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_MCP_CUBE_QUERY_LIMIT
    ):
        raise HTTPException(
            status_code=422,
            detail=f"query limit must be between 1 and {MAX_MCP_CUBE_QUERY_LIMIT}",
        )

    return bounded


async def semantic_catalog(
    search: str | None = None,
    *,
    include: list[str] | None = None,
    cursor: int = 0,
    limit: int = DEFAULT_CUBE_CATALOG_LIMIT,
    member_limit: int = DEFAULT_CUBE_CATALOG_MEMBER_LIMIT,
) -> dict[str, Any]:
    """Return a bounded catalog for discovering compiled Cube semantics."""

    _validate_meta_page(
        cursor=cursor,
        limit=limit,
        member_limit=member_limit,
        max_limit=MAX_CUBE_CATALOG_LIMIT,
        max_member_limit=MAX_CUBE_CATALOG_MEMBER_LIMIT,
    )

    requested_collections = _requested_collections(
        include,
        supported=CUBE_CATALOG_COLLECTIONS,
    )

    try:
        meta = await load_cube_meta()
    except CubeAPIError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=cube_api_error_detail(exc),
        ) from exc

    cubes = meta.get("cubes") if isinstance(meta, dict) else []
    cubes = cubes if isinstance(cubes, list) else []
    normalized_search = _normalize_search_text(search or "")

    if normalized_search:
        scored_cubes = [
            (_search_score(normalized_search, cube), cube)
            for cube in cubes
            if isinstance(cube, dict)
        ]
        cubes = [
            cube
            for score, cube in sorted(
                scored_cubes,
                key=lambda item: item[0],
                reverse=True,
            )
            if score > 0
        ]

    total = len(cubes)
    page = cubes[cursor : cursor + limit]
    next_cursor = cursor + len(page)
    source_definitions = source_definition_index()

    return semantic_response_projector.cube_catalog(
        CubeCatalogProjectionInput(
            cubes=[cube for cube in page if isinstance(cube, dict)],
            source_definitions=source_definitions,
            requested_collections=requested_collections,
            member_limit=member_limit,
            next_cursor=next_cursor if next_cursor < total else None,
            total=total,
        )
    )


async def bounded_cube_meta(
    *,
    search: str | None = None,
    include: list[str] | None = None,
    cursor: int = 0,
    limit: int = DEFAULT_CUBE_META_LIMIT,
    member_limit: int = DEFAULT_CUBE_META_MEMBER_LIMIT,
) -> dict[str, Any]:
    """Return a filtered, paginated projection of Cube's compiled metadata."""

    _validate_meta_page(
        cursor=cursor,
        limit=limit,
        member_limit=member_limit,
        max_limit=MAX_CUBE_META_LIMIT,
        max_member_limit=MAX_CUBE_META_MEMBER_LIMIT,
    )

    requested_collections = _requested_collections(
        include,
        supported=CUBE_META_COLLECTIONS,
    )

    try:
        meta = await load_cube_meta()
    except CubeAPIError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=cube_api_error_detail(exc),
        ) from exc

    cubes = meta.get("cubes") if isinstance(meta, dict) else []
    cubes = [cube for cube in cubes if isinstance(cube, dict)]
    normalized_search = _normalize_search_text(search or "")

    if normalized_search:
        scored_cubes = [
            (_search_score(normalized_search, cube), cube) for cube in cubes
        ]
        cubes = [
            cube
            for score, cube in sorted(
                scored_cubes,
                key=lambda item: item[0],
                reverse=True,
            )
            if score > 0
        ]

    total = len(cubes)
    page = cubes[cursor : cursor + limit]
    next_cursor = cursor + len(page)

    return semantic_response_projector.cube_meta(
        CubeMetaProjectionInput(
            cubes=page,
            requested_collections=requested_collections,
            member_limit=member_limit,
            next_cursor=next_cursor if next_cursor < total else None,
            total=total,
        )
    )


async def cube_by_name(name: str) -> dict[str, Any]:
    try:
        meta = await load_cube_meta()
    except CubeAPIError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=cube_api_error_detail(exc),
        ) from exc

    cubes = meta.get("cubes") if isinstance(meta, dict) else []
    source_definitions = authored_definition_index()

    for cube in cubes if isinstance(cubes, list) else []:
        if isinstance(cube, dict) and cube.get("name") == name:
            return semantic_response_projector.cube(
                CubeProjectionInput(
                    compiled=cube,
                    authored_source=source_definitions.get(name),
                )
            )

    raise HTTPException(status_code=404, detail=f"Cube '{name}' not found")


def _normalize_cube_query(query: Any) -> CubeQueryPayload:
    if isinstance(query, list):
        if (
            not query
            or len(query) > MAX_MCP_CUBE_BLEND_QUERIES
            or not all(isinstance(item, dict) for item in query)
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Cube data blending queries must be a non-empty list of at most "
                    f"{MAX_MCP_CUBE_BLEND_QUERIES} query objects. Arrays are one "
                    "Cube blending request, not independent batch execution."
                ),
            )

        normalized_items: list[dict[str, Any]] = []

        for item in query:
            normalized_item = _normalize_cube_query(item)

            if not isinstance(normalized_item, dict):
                raise HTTPException(
                    status_code=422,
                    detail="Each Cube data blending item must be one query object.",
                )

            normalized_items.append(normalized_item)

        return normalized_items

    if not isinstance(query, dict):
        raise HTTPException(
            status_code=422,
            detail="Cube query must be a JSON object or a list of JSON objects.",
        )

    if not any(key in query for key in CUBE_QUERY_KEYS):
        raise HTTPException(
            status_code=422,
            detail=(
                "Expected Cube query JSON with members such as measures, "
                "dimensions, filters, timeDimensions, or segments."
            ),
        )

    return query


def _validate_meta_page(
    *,
    cursor: int,
    limit: int,
    member_limit: int,
    max_limit: int,
    max_member_limit: int,
) -> None:
    if cursor < 0:
        raise HTTPException(status_code=422, detail="cursor must be at least 0")
    if not 1 <= limit <= max_limit:
        raise HTTPException(
            status_code=422,
            detail=f"limit must be between 1 and {max_limit}",
        )
    if not 1 <= member_limit <= max_member_limit:
        raise HTTPException(
            status_code=422,
            detail=f"member_limit must be between 1 and {max_member_limit}",
        )


def _requested_collections(
    include: list[str] | None,
    *,
    supported: tuple[str, ...],
) -> list[str]:
    requested_collections = list(dict.fromkeys(include or []))
    invalid_collections = [
        name for name in requested_collections if name not in supported
    ]

    if invalid_collections:
        raise HTTPException(
            status_code=422,
            detail=(
                "include contains unsupported collections: "
                f"{', '.join(invalid_collections)}"
            ),
        )

    return requested_collections


def _cube_search_text(cube: Any) -> str:
    if not isinstance(cube, dict):
        return str(cube)

    parts = [
        cube.get("name"),
        cube.get("title"),
        cube.get("description"),
    ]

    for key in ("measures", "dimensions", "segments"):
        members = cube.get(key)

        if not isinstance(members, list):
            continue

        for member in members:
            if isinstance(member, dict):
                parts.extend(
                    [
                        member.get("name"),
                        member.get("title"),
                        member.get("shortTitle"),
                        member.get("description"),
                    ]
                )

    return " ".join(str(part) for part in parts if part)


def _search_score(normalized_query: str, cube: dict[str, Any]) -> int:
    normalized_name = _normalize_search_text(str(cube.get("name") or ""))
    normalized_title = _normalize_search_text(str(cube.get("title") or ""))
    normalized_text = _normalize_search_text(_cube_search_text(cube))

    if normalized_query == normalized_name:
        return 1000
    if normalized_query in normalized_name:
        return 900
    if normalized_query in normalized_title:
        return 800
    if normalized_query in normalized_text:
        return 700

    query_tokens = _search_query_tokens(normalized_query)
    name_tokens = set(normalized_name.split())
    title_tokens = set(normalized_title.split())
    text_tokens = set(normalized_text.split())

    if not query_tokens:
        return 0

    score = 100
    matched_count = 0

    for token in query_tokens:
        if _token_matches(token, name_tokens):
            score += 80
            matched_count += 1
        elif _token_matches(token, title_tokens):
            score += 50
            matched_count += 1
        elif _token_matches(token, text_tokens):
            score += 20
            matched_count += 1

    if matched_count == 0:
        return 0

    score += int(100 * matched_count / len(query_tokens))

    if matched_count == len(query_tokens):
        score += 100

    return score


def _search_query_tokens(normalized_query: str) -> list[str]:
    tokens = [
        token
        for token in normalized_query.split()
        if token not in SEARCH_STOP_WORDS and (len(token) > 1 or token.isdigit())
    ]

    return tokens or normalized_query.split()


def _token_matches(token: str, text_tokens: set[str]) -> bool:
    if token in text_tokens:
        return True

    variants = {token}

    if token.endswith("s") and len(token) > 3:
        variants.add(token[:-1])
    else:
        variants.add(f"{token}s")

    return any(variant in text_tokens for variant in variants)


def _normalize_search_text(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower())

    return " ".join(normalized.split())
