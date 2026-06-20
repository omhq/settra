from typing import Any

from app.agent.connector_context import (
    connector_table_context_notes,
    connector_table_context_warning,
    connector_table_summary_note,
)
from app.agent.metadata.google_sheets import google_sheets_virtual_table_context_lines


def format_context(
    relevant_tables: list[str],
    raw_schema: list[dict[str, Any]],
    semantic: dict[str, Any],
    schema: str,
    *,
    plugin: str = "",
) -> str:
    raw_by_name = {table.get("name"): table for table in raw_schema}
    chunks = [f"Steampipe schema: {schema}", "Use schema-qualified table names."]

    for table_name in relevant_tables:
        raw = raw_by_name.get(table_name, {})
        sem = semantic.get(table_name, {})
        columns = raw.get("columns") or []
        semantic_columns = (
            sem.get("columns") if isinstance(sem.get("columns"), dict) else {}
        )

        if not columns and semantic_columns:
            columns = [
                {"name": name, "type": "unknown", **meta}
                for name, meta in semantic_columns.items()
            ]

        lines = [
            "",
            f"Table: {table_name}",
            f"Description: {table_description(raw, sem)}",
        ]

        if sem.get("label"):
            lines.append(f"Label: {sem['label']}")
        if sem.get("type"):
            lines.append(f"Table type: {sem['type']}")
        if sem.get("grain"):
            lines.append(f"Grain: {sem['grain']}")
        if sem.get("primary_time_column"):
            lines.append(f"Primary time column: {sem['primary_time_column']}")
        if sem.get("notes"):
            lines.append(f"Notes: {sem['notes']}")

        metadata = raw.get("metadata")

        if plugin == "googlesheets" and isinstance(metadata, dict):
            lines.extend(google_sheets_virtual_table_context_lines(metadata, schema))

        lines.extend(
            connector_table_context_notes(
                plugin,
                table_name,
                raw_schema,
                semantic,
                schema,
            )
        )

        warning = connector_table_context_warning(
            plugin,
            table_name,
            schema,
            columns,
        )

        if warning:
            lines.append(warning)

        lines.append("Columns:")

        for col in columns[:80]:
            lines.append(_format_column(col, semantic_columns))

        joins = as_list(sem.get("common_joins"))

        if joins:
            lines.append(f"Common joins: {_format_semantic_list(joins)}")

        relationships = as_list(sem.get("relationships"))

        if relationships:
            lines.append(f"Relationships: {_format_semantic_list(relationships)}")

        metrics = sem.get("metrics") or {}

        if isinstance(metrics, dict) and metrics:
            lines.append("Metrics:")
            lines.extend(_format_semantic_mapping(metrics, indent="  "))

        dimensions = sem.get("dimensions") or {}

        if isinstance(dimensions, dict) and dimensions:
            lines.append("Dimensions:")
            lines.extend(_format_semantic_mapping(dimensions, indent="  "))

        common_filters = as_list(sem.get("common_filters"))

        if common_filters:
            lines.append("Common filters:")
            lines.extend(_format_common_filters(common_filters, indent="  "))

        caveats = as_list(sem.get("caveats"))

        if caveats:
            lines.append(f"Caveats: {_format_semantic_list(caveats)}")

        chunks.append("\n".join(lines))

    return "\n".join(chunks)


def all_table_names(
    raw_schema: list[dict[str, Any]],
    semantic: dict[str, Any],
) -> list[str]:
    return sorted({table["name"] for table in raw_schema if table.get("name")})


def table_summary(
    table_name: str,
    raw_schema: list[dict[str, Any]],
    semantic: dict[str, Any],
    plugin: str,
) -> str:
    raw_by_name = {table.get("name"): table for table in raw_schema}
    raw = raw_by_name.get(table_name, {})
    sem = semantic.get(table_name, {})
    columns = raw.get("columns") or []

    if not columns and isinstance(sem.get("columns"), dict):
        columns = [{"name": name, **meta} for name, meta in sem["columns"].items()]

    column_names = ", ".join(col.get("name", "") for col in columns[:12])
    label = f"{sem.get('label')}: " if sem.get("label") else ""
    table_type = f" Type: {sem.get('type')}." if sem.get("type") else ""
    grain = f" Grain: {sem.get('grain')}." if sem.get("grain") else ""
    metrics = summary_names(sem.get("metrics"))
    dimensions = summary_names(sem.get("dimensions"))
    metric_text = f" Metrics: {metrics}." if metrics else ""
    dimension_text = f" Dimensions: {dimensions}." if dimensions else ""
    table_note = connector_table_summary_note(
        plugin,
        table_name,
        raw_schema,
        semantic,
    )

    return (
        f"{label}{table_description(raw, sem)}."
        f"{table_type}{grain}{metric_text}{dimension_text}{table_note} "
        f"Columns: {column_names}"
    )


def table_description(raw: dict[str, Any], semantic: dict[str, Any]) -> str:
    return semantic.get("description") or raw.get("description") or "No description"


def as_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value

    return [value]


def json_like(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{key}={val}" for key, val in value.items())
    if isinstance(value, list):
        return ", ".join(map(str, value))

    return str(value)


def summary_names(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return ""

    return ", ".join(str(key) for key in list(value.keys())[:8])


def _format_column(
    column: dict[str, Any],
    semantic_columns: dict[str, Any],
) -> str:
    name = column.get("name", "")
    col_type = column.get("type") or column.get("data_type") or "unknown"
    col_sem = semantic_columns.get(name, {}) if semantic_columns else {}
    label = col_sem.get("label")
    semantic_type = col_sem.get("type")
    description = col_sem.get("description") or column.get("description") or ""
    values = col_sem.get("values")
    details = []

    if label:
        details.append(f"label={label}")
    if semantic_type:
        details.append(f"semantic_type={semantic_type}")
    for key in (
        "references",
        "transform",
        "unit",
        "currency_column",
        "grain",
    ):
        value = col_sem.get(key)
        if value not in ("", None, [], {}):
            details.append(f"{key}={value}")

    suffix = f": {description}" if description else ""

    if details:
        suffix += f" [{'; '.join(details)}]"

    if values:
        suffix += f" Values: {', '.join(map(str, values))}."

    return f"  - {name} ({col_type}){suffix}"


def _format_semantic_mapping(
    value: dict[str, Any],
    indent: str = "",
) -> list[str]:
    lines = []

    for key, meta in value.items():
        if isinstance(meta, dict):
            details = []
            label = meta.get("label")
            column = meta.get("column")
            expression = meta.get("sql") or meta.get("expression")
            description = meta.get("description")

            if label:
                details.append(f"label={label}")
            if column:
                details.append(f"column={column}")
            elif expression:
                details.append(f"sql={expression}")
            if description:
                details.append(str(description))

            extras = [
                f"{extra_key}={extra_value}"
                for extra_key, extra_value in meta.items()
                if extra_key
                not in {"label", "sql", "expression", "column", "description"}
                and extra_value not in ("", None, [], {})
            ]

            details.extend(extras)

            rendered = "; ".join(details) if details else json_like(meta)
        else:
            rendered = str(meta)

        lines.append(f"{indent}- {key}: {rendered}")

    return lines


def _format_common_filters(value: list[Any], indent: str = "") -> list[str]:
    lines = []

    for item in value:
        if isinstance(item, dict):
            label = item.get("label") or "Filter"
            sql = item.get("sql") or item.get("expression") or ""
            description = item.get("description")
            rendered = f"{label}: {sql}" if sql else str(label)

            if description:
                rendered += f"; {description}"
        else:
            rendered = str(item)

        lines.append(f"{indent}- {rendered}")

    return lines


def _format_semantic_list(value: list[Any]) -> str:
    rendered = []

    for item in value:
        if isinstance(item, dict):
            rendered.append(json_like(item))
        else:
            rendered.append(str(item))

    return "; ".join(rendered)
