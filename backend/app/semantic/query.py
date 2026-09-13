from __future__ import annotations

from typing import Any

from fastapi import HTTPException

CubeQueryPayload = dict[str, Any] | list[dict[str, Any]]


def referenced_cube_names(query: CubeQueryPayload) -> set[str]:
    """Return every Cube model referenced anywhere in a Cube REST query."""

    referenced: set[str] = set()

    def walk(value: Any, *, join_hint: bool = False) -> None:
        if isinstance(value, str) and "." in value:
            name = value.split(".", 1)[0].strip()
            if name:
                referenced.add(name)
        elif join_hint and isinstance(value, str) and value.strip():
            referenced.add(value.strip())
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(key)
                if key in {"values", "dateRange", "compareDateRange"}:
                    continue
                walk(item, join_hint=key == "joinHints")
        elif isinstance(value, list):
            for item in value:
                walk(item, join_hint=join_hint)

    walk(query)
    return referenced


def validate_cube_query_names(
    query: CubeQueryPayload,
    allowed_names: set[str],
) -> None:
    unavailable = sorted(referenced_cube_names(query) - allowed_names)
    if unavailable:
        raise HTTPException(
            404,
            "Cube query references unavailable models: " + ", ".join(unavailable),
        )
