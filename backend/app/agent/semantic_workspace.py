import json

from typing import Any

from app.agent.schemas import SemanticSearchWorkspaceEntry


def build_semantic_workspace_entry(
    *,
    attempt: int,
    max_attempts: int,
    query: str,
    types: list[str],
    connection_ids: list[int],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    entry = SemanticSearchWorkspaceEntry(
        attempt=attempt,
        max_attempts=max_attempts,
        query=query,
        types=types,
        connection_ids=connection_ids,
        result_count=len(results),
        results=results,
    )

    return entry.model_dump()


def format_semantic_workspace_for_prompt(workspace: list[dict[str, Any]]) -> str:
    if not workspace:
        return "No semantic searches have run yet."

    chunks = []

    for search in workspace:
        lines = [
            (
                f"Semantic search {search.get('attempt')}/"
                f"{search.get('max_attempts')}: {search.get('query')}"
            ),
            f"Types: {', '.join(map(str, search.get('types') or []))}",
            f"Results returned: {search.get('result_count', 0)}",
        ]

        for result in search.get("results", [])[:12]:
            lines.append(_format_result_for_prompt(result))

        chunks.append("\n".join(lines))

    return "\n\n".join(chunks)


def _format_result_for_prompt(result: dict[str, Any]) -> str:
    result_type = result.get("type", "semantic")
    title = result.get("title") or result.get("table") or result.get("name")
    details = {
        key: value
        for key, value in result.items()
        if key not in {"type", "title"} and value not in (None, "", [], {})
    }
    detail_text = json.dumps(details, separators=(",", ":"), default=str)

    return f"- [{result_type}] {title}: {detail_text}"
