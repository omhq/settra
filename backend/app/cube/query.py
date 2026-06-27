import re

from typing import Any

from fastapi import HTTPException

from app.cube.client import CubeAPIError, load_cube_meta, load_cube_query
from app.cube.model import source_definition_index

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
        "operation": "cube_query",
        "error": f"{exc.__class__.__name__}: {exc.message}",
        "retryable": exc.status_code in {408, 429, 500, 502, 503, 504},
        "cube": exc.payload,
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


async def semantic_catalog(search: str | None = None) -> dict[str, Any]:
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

    source_definitions = source_definition_index()

    return {
        "cubes": [
            _cube_summary(cube, source_definitions.get(str(cube.get("name"))))
            for cube in cubes
            if isinstance(cube, dict)
        ],
        "cube_count": len(cubes),
        "compiler_id": meta.get("compilerId"),
    }


async def cube_by_name(name: str) -> dict[str, Any]:
    try:
        meta = await load_cube_meta()
    except CubeAPIError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=cube_api_error_detail(exc),
        ) from exc

    cubes = meta.get("cubes") if isinstance(meta, dict) else []
    source_definitions = source_definition_index()

    for cube in cubes if isinstance(cubes, list) else []:
        if isinstance(cube, dict) and cube.get("name") == name:
            return {
                **cube,
                "source_definition": source_definitions.get(name),
            }

    raise HTTPException(status_code=404, detail=f"Cube '{name}' not found")


def _normalize_cube_query(query: Any) -> CubeQueryPayload:
    if isinstance(query, list):
        if not query or not all(isinstance(item, dict) for item in query):
            raise HTTPException(
                status_code=422,
                detail="Cube data blending queries must be a non-empty list of objects.",
            )

        return query

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


def _cube_summary(
    cube: dict[str, Any],
    source_definition: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "name": cube.get("name"),
        "title": cube.get("title"),
        "type": cube.get("type"),
        "description": cube.get("description"),
        "source_path": (
            source_definition.get("path")
            if isinstance(source_definition, dict)
            else None
        ),
        "source_type": (
            source_definition.get("source_type")
            if isinstance(source_definition, dict)
            else None
        ),
        "measures": [_member_summary(member) for member in cube.get("measures", [])],
        "dimensions": [
            _member_summary(member) for member in cube.get("dimensions", [])
        ],
        "segments": [_member_summary(member) for member in cube.get("segments", [])],
        "joins": cube.get("joins") or [],
    }


def _member_summary(member: Any) -> dict[str, Any]:
    if not isinstance(member, dict):
        return {"name": str(member)}

    return {
        "name": member.get("name"),
        "title": member.get("shortTitle") or member.get("title"),
        "type": member.get("type"),
        "agg_type": member.get("aggType"),
        "description": member.get("description"),
    }


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

    query_tokens = normalized_query.split()
    name_tokens = set(normalized_name.split())
    title_tokens = set(normalized_title.split())
    text_tokens = set(normalized_text.split())

    if not all(_token_matches(token, text_tokens) for token in query_tokens):
        return 0

    score = 100

    for token in query_tokens:
        if _token_matches(token, name_tokens):
            score += 20
        elif _token_matches(token, title_tokens):
            score += 10
        else:
            score += 1

    return score


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
