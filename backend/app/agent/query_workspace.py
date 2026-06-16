import json

from typing import Any

from app.agent.consts import MAX_RESULT_ROWS
from app.agent.schemas import AnalyticsState, QueryWorkspaceItem
from app.pruning import prune_query_workspace_item_for_prompt


def format_query_workspace_for_prompt(workspace: list[dict[str, Any]]) -> str:
    if not workspace:
        return "No query steps have run yet."

    chunks = []

    for item in workspace:
        prompt_item = prune_query_workspace_item_for_prompt(item)
        lines = [
            (
                f"Step {prompt_item.get('attempt')}/"
                f"{prompt_item.get('max_attempts')}: "
                f"{prompt_item.get('name') or 'Query'}"
            ),
            f"Purpose: {prompt_item.get('purpose') or 'No purpose recorded'}",
            f"SQL: {prompt_item.get('sql') or ''}",
        ]

        if prompt_item.get("error"):
            lines.append(f"Error: {prompt_item['error']}")
        else:
            lines.extend(
                [
                    "Columns shown: "
                    f"{', '.join(map(str, prompt_item.get('columns') or []))}",
                    "Omitted columns: " f"{prompt_item.get('omitted_column_count', 0)}",
                    f"Rows returned: {prompt_item.get('row_count', 0)}",
                    f"Truncated: {bool(prompt_item.get('truncated'))}",
                    "Sample rows:",
                    json.dumps(prompt_item.get("rows") or [], indent=2, default=str),
                ]
            )

        chunks.append("\n".join(lines))

    return "\n\n".join(chunks)


def build_query_workspace_item(
    state: AnalyticsState,
    *,
    attempt: int,
    max_attempts: int,
    sql: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    error: str,
) -> dict[str, Any]:
    item = QueryWorkspaceItem(
        attempt=attempt,
        max_attempts=max_attempts,
        name=state.get("current_step_name") or f"Query {attempt}",
        purpose=state.get("current_step_purpose") or state.get("query_plan") or "",
        query_plan=state.get("query_plan", ""),
        sql=sql,
        used_tables=state.get("used_tables") or [],
        used_relationships=state.get("used_relationships") or [],
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=len(rows) >= MAX_RESULT_ROWS,
        error=error,
    )

    return item.model_dump()
