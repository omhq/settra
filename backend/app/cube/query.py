from typing import Any

from fastapi import HTTPException

from app.cube.client import CubeAPIError, load_cube_meta, load_cube_query

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
    normalized_search = (search or "").strip().lower()

    if normalized_search:
        cubes = [
            cube
            for cube in cubes
            if normalized_search in _cube_search_text(cube).lower()
        ]

    return {
        "cubes": [_cube_summary(cube) for cube in cubes if isinstance(cube, dict)],
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

    for cube in cubes if isinstance(cubes, list) else []:
        if isinstance(cube, dict) and cube.get("name") == name:
            return cube

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


def _cube_summary(cube: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": cube.get("name"),
        "title": cube.get("title"),
        "type": cube.get("type"),
        "description": cube.get("description"),
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
        "title": member.get("title") or member.get("shortTitle"),
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
