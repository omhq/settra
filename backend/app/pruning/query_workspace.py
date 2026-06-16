from typing import Any

from app.pruning.consts import (
    QUERY_WORKSPACE_COLUMN_HINTS,
    QUERY_WORKSPACE_COLUMN_LIMIT,
    QUERY_WORKSPACE_SAMPLE_ROW_LIMIT,
    QUERY_WORKSPACE_VALUE_LIMIT,
)
from app.pruning.utils import compact_value, tokens


def prune_query_workspace_item_for_prompt(item: dict[str, Any]) -> dict[str, Any]:
    columns = [str(column) for column in item.get("columns") or []]
    rows = [row for row in item.get("rows") or [] if isinstance(row, dict)]
    selected_columns = _select_columns(
        columns,
        rows,
        sql=str(item.get("sql") or ""),
    )

    return {
        "attempt": item.get("attempt"),
        "max_attempts": item.get("max_attempts"),
        "name": item.get("name"),
        "purpose": item.get("purpose"),
        "sql": item.get("sql"),
        "error": item.get("error"),
        "columns": selected_columns,
        "omitted_column_count": max(len(columns) - len(selected_columns), 0),
        "row_count": item.get("row_count", 0),
        "truncated": item.get("truncated", False),
        "rows": _prune_rows(rows, selected_columns),
    }


def prune_query_result_rows_for_prompt(
    results: dict[str, Any],
) -> list[dict[str, Any]]:
    columns = [str(column) for column in results.get("columns") or []]
    rows = [row for row in results.get("rows") or [] if isinstance(row, dict)]
    selected_columns = _select_columns(columns, rows, sql="")

    return _prune_rows(rows, selected_columns)


def _select_columns(
    columns: list[str],
    rows: list[dict[str, Any]],
    *,
    sql: str,
) -> list[str]:
    if len(columns) <= QUERY_WORKSPACE_COLUMN_LIMIT:
        return columns

    sql_lower = sql.lower()
    scored = []

    for index, column in enumerate(columns):
        score = 0
        column_lower = column.lower()
        column_tokens = tokens(column)

        if column_lower in sql_lower:
            score += 80
        if column_tokens & QUERY_WORKSPACE_COLUMN_HINTS:
            score += 70
        if _has_visible_value(rows, column):
            score += 50
        if column_lower.startswith("sp_") or column_lower in {"_ctx", "sp_ctx"}:
            score -= 80

        scored.append((score, index, column))

    selected = sorted(scored, key=lambda item: (-item[0], item[1]))[
        :QUERY_WORKSPACE_COLUMN_LIMIT
    ]
    selected_indices = {index for _, index, _ in selected}

    return [column for index, column in enumerate(columns) if index in selected_indices]


def _has_visible_value(rows: list[dict[str, Any]], column: str) -> bool:
    for row in rows[:QUERY_WORKSPACE_SAMPLE_ROW_LIMIT]:
        value = row.get(column)

        if value not in (None, "", [], {}):
            return True

    return False


def _prune_rows(
    rows: list[dict[str, Any]],
    selected_columns: list[str],
) -> list[dict[str, Any]]:
    pruned_rows = []

    for row in rows[:QUERY_WORKSPACE_SAMPLE_ROW_LIMIT]:
        pruned_row = {}

        for column in selected_columns:
            if column not in row:
                continue

            value = compact_value(
                row.get(column),
                max_chars=QUERY_WORKSPACE_VALUE_LIMIT,
            )

            if value not in (None, "", [], {}):
                pruned_row[column] = value

        pruned_rows.append(pruned_row)

    return pruned_rows
