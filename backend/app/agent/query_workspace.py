import json

from typing import Any

from app.agent.consts import MAX_RESULT_ROWS
from app.agent.schemas import AnalyticsState, QueryWorkspaceItem


def format_query_workspace_for_prompt(workspace: list[dict[str, Any]]) -> str:
    if not workspace:
        return "No query steps have run yet."

    chunks = []

    for item in workspace:
        sample_rows = item.get("rows", [])[:20]
        lines = [
            (
                f"Step {item.get('attempt')}/{item.get('max_attempts')}: "
                f"{item.get('name') or 'Query'}"
            ),
            f"Purpose: {item.get('purpose') or 'No purpose recorded'}",
            f"SQL: {item.get('sql') or ''}",
        ]

        if item.get("error"):
            lines.append(f"Error: {item['error']}")
        else:
            lines.extend(
                [
                    f"Columns: {', '.join(map(str, item.get('columns') or []))}",
                    f"Rows returned: {item.get('row_count', 0)}",
                    f"Truncated: {bool(item.get('truncated'))}",
                    "Sample rows:",
                    json.dumps(sample_rows, indent=2, default=str),
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
