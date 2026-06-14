from typing import Any

import aiosqlite

from app.agent.schemas import SemanticSearchRequest
from app.agent.semantic_search_candidates import (
    column_candidates,
    metric_candidates,
    relationship_candidates,
    table_candidates,
    warning_candidates,
)
from app.agent.semantic_search_text import (
    semantic_search_score,
    semantic_search_tokens,
)
from app.agent.semantic_workspace import (
    build_semantic_workspace_entry,
    format_semantic_workspace_for_prompt,
)
from app.common.config import DB_PATH

SEMANTIC_SEARCH_TYPES = {
    "table",
    "column",
    "relationship",
    "metric",
    "warning",
}

__all__ = [
    "SEMANTIC_SEARCH_TYPES",
    "format_semantic_workspace_for_prompt",
    "search_semantics",
    "search_semantics_state",
]


async def search_semantics_state(state: dict[str, Any]) -> dict[str, Any]:
    attempt = int(state.get("query_attempts") or 0) + 1
    max_attempts = int(state.get("max_query_attempts") or 5)
    request = _search_request_from_state(state)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        results = await search_semantics(
            db,
            query=request.query,
            connection_ids=request.connection_ids,
            types=request.types,
            limit=request.limit,
        )

    workspace = list(state.get("semantic_workspace", []))

    workspace.append(
        build_semantic_workspace_entry(
            attempt=attempt,
            max_attempts=max_attempts,
            query=request.query,
            types=request.types or sorted(SEMANTIC_SEARCH_TYPES),
            connection_ids=request.connection_ids,
            results=results,
        )
    )

    return {
        "query_attempts": attempt,
        "semantic_workspace": workspace,
        "semantic_search_query": "",
        "semantic_search_types": [],
        "semantic_search_connection_ids": [],
        "semantic_search_limit": 12,
        "error": "",
        "needs_retry": False,
    }


async def search_semantics(
    db: aiosqlite.Connection,
    *,
    query: str,
    connection_ids: list[int],
    types: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    selected_types = set(types) & SEMANTIC_SEARCH_TYPES or SEMANTIC_SEARCH_TYPES
    candidates: list[tuple[dict[str, Any], str]] = []

    if "table" in selected_types:
        candidates.extend(await table_candidates(db, connection_ids))
    if "column" in selected_types:
        candidates.extend(await column_candidates(db, connection_ids))
    if "relationship" in selected_types:
        candidates.extend(await relationship_candidates(db, connection_ids))
    if "metric" in selected_types:
        candidates.extend(await metric_candidates(db, connection_ids))
    if "warning" in selected_types:
        candidates.extend(await warning_candidates(db, connection_ids))

    tokens = semantic_search_tokens(query)
    scored = []

    for item, text in candidates:
        score = semantic_search_score(query, tokens, text)
        if score > 0 or not tokens:
            scored.append((score, item))

    scored.sort(
        key=lambda pair: (
            -pair[0],
            str(pair[1].get("type", "")),
            str(pair[1].get("title", "")),
        )
    )

    return [item for _, item in scored[:limit]]


def _search_request_from_state(state: dict[str, Any]) -> SemanticSearchRequest:
    requested_types = [
        str(item)
        for item in state.get("semantic_search_types", [])
        if str(item) in SEMANTIC_SEARCH_TYPES
    ]
    connection_ids = [
        int(connection_id)
        for connection_id in state.get("semantic_search_connection_ids", [])
        if connection_id is not None
    ] or [
        int(connection_id)
        for connection_id in state.get("connection_ids", [])
        if connection_id is not None
    ]
    limit = int(state.get("semantic_search_limit") or 12)

    return SemanticSearchRequest(
        query=str(state.get("semantic_search_query") or "").strip(),
        types=requested_types,
        connection_ids=connection_ids,
        limit=max(1, min(limit, 20)),
    )
