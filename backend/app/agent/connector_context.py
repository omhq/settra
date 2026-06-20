import re

from typing import Any

from app.connector_prompts import connector_prompt_snippets


def plugin_context_notes(plugin: str) -> list[str]:
    return connector_prompt_lines(plugin, "context")


def connector_table_summary_note(
    plugin: str,
    table_name: str,
    raw_schema: list[dict[str, Any]],
    semantic: dict[str, Any],
) -> str:
    kind = connector_table_prompt_kind(plugin, table_name, raw_schema, semantic)
    if not kind:
        return ""

    note = connector_prompt_text(
        plugin,
        "context",
        f"table_summary_{kind}",
        {
            "table_name": table_name,
        },
    )

    return f" {note}" if note else ""


def connector_table_context_notes(
    plugin: str,
    table_name: str,
    raw_schema: list[dict[str, Any]],
    semantic: dict[str, Any],
    schema: str,
) -> list[str]:
    kind = connector_table_prompt_kind(plugin, table_name, raw_schema, semantic)
    if not kind:
        return []

    return connector_prompt_lines(
        plugin,
        "context",
        f"table_notes_{kind}",
        {
            "schema": schema,
            "table_name": table_name,
        },
    )


def connector_table_context_warning(
    plugin: str,
    table_name: str,
    schema: str,
    columns: list[dict[str, Any]],
) -> str:
    if not google_sheets_dynamic_table_is_suspicious(
        plugin,
        table_name,
        columns,
    ):
        return ""

    return connector_prompt_text(
        plugin,
        "context",
        "dynamic_table_warning",
        {
            "schema": schema,
            "table_name": table_name,
        },
    )


def connector_table_prompt_kind(
    plugin: str,
    table_name: str,
    raw_schema: list[dict[str, Any]],
    semantic: dict[str, Any],
) -> str:
    if plugin == "googlesheets":
        if is_virtual_google_sheets_table(table_name, raw_schema):
            return ""
        if is_dynamic_google_sheets_table(table_name, raw_schema, semantic):
            return "dynamic"
        if table_name in {"googlesheets_cell", "googlesheets_sheet"}:
            return table_name

    return ""


def connector_prompt_text(
    plugin: str,
    scope: str,
    name: str,
    variables: dict[str, Any] | None = None,
) -> str:
    return "\n".join(
        connector_prompt_snippets(
            [plugin],
            scope,
            name,
            variables=variables,
            include_common=False,
            include_headers=False,
        )
    ).strip()


def connector_prompt_lines(
    plugin: str,
    scope: str,
    name: str | None = None,
    variables: dict[str, Any] | None = None,
) -> list[str]:
    lines: list[str] = []

    for snippet in connector_prompt_snippets(
        [plugin],
        scope,
        name,
        variables=variables,
        include_common=name is None,
        include_headers=False,
    ):
        lines.extend(line.strip() for line in snippet.splitlines() if line.strip())

    return lines


def is_dynamic_google_sheets_table(
    table_name: str,
    raw_schema: list[dict[str, Any]],
    semantic: dict[str, Any],
) -> bool:
    if table_name.startswith("googlesheets_"):
        return False

    fixed_tables = {
        table.get("name")
        for table in raw_schema
        if str(table.get("name") or "").startswith("googlesheets_")
    }

    return bool(fixed_tables or semantic.get("googlesheets_cell"))


def is_virtual_google_sheets_table(
    table_name: str,
    raw_schema: list[dict[str, Any]],
) -> bool:
    for table in raw_schema:
        if table.get("name") != table_name:
            continue

        metadata = table.get("metadata")

        return bool(
            isinstance(metadata, dict)
            and metadata.get("virtual")
            and metadata.get("source") == "googlesheets_cell"
        )

    return False


def google_sheets_dynamic_table_is_suspicious(
    plugin: str,
    table_name: str,
    columns: list[dict[str, Any]],
) -> bool:
    if plugin != "googlesheets" or table_name.startswith("googlesheets_"):
        return False

    names = [
        str(column.get("name") or "").strip()
        for column in columns
        if str(column.get("name") or "").strip()
        and str(column.get("name") or "").strip()
        not in {"sp_connection_name", "sp_ctx", "_ctx"}
    ]

    if not names:
        return False

    value_like = [
        name for name in names[:8] if looks_like_spreadsheet_value_not_header(name)
    ]

    return len(value_like) >= 2 or any(is_numeric_text(name) for name in names[:8])


def google_sheets_table_score_adjustment(
    table_name: str,
    raw_schema: list[dict[str, Any]],
    semantic: dict[str, Any],
    question_words: set[str],
) -> int:
    raw_cell_words = {
        "a1",
        "cell",
        "cells",
        "coordinate",
        "coordinates",
        "formula",
        "formulas",
        "hyperlink",
        "hyperlinks",
        "note",
        "notes",
        "range",
        "ranges",
        "raw",
    }
    record_words = {
        "aggregation",
        "aggregations",
        "count",
        "counts",
        "customer",
        "customers",
        "data",
        "join",
        "joins",
        "list",
        "lists",
        "many",
        "order",
        "orders",
        "record",
        "records",
        "row",
        "rows",
        "total",
        "totals",
    }

    if question_words & raw_cell_words:
        if table_name == "googlesheets_cell":
            return 3
        return 0

    if not question_words & record_words:
        return 0

    if is_dynamic_google_sheets_table(table_name, raw_schema, semantic):
        return 4

    if table_name == "googlesheets_cell":
        return -4

    return 0


def looks_like_spreadsheet_value_not_header(name: str) -> bool:
    if is_numeric_text(name):
        return True
    if len(name) >= 12 and re.search(r"[A-Za-z]", name) and re.search(r"\d", name):
        return True
    if len(name) <= 30 and " " not in name and "_" not in name and name.istitle():
        return True

    return False


def is_numeric_text(value: str) -> bool:
    return bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?", value.strip()))
