import json

from typing import Any


def format_semantic_contract_for_prompt(contract: dict[str, Any]) -> str:
    prompt_contract = {
        "tables": _compact_contract_tables(contract.get("tables") or {}),
        "confirmed_relationships": [
            _compact_dict(relationship)
            for relationship in contract.get("confirmed_relationships") or []
        ],
        "metrics": _compact_contract_metrics(contract.get("metrics") or {}),
        "rules": contract.get("rules") or [],
    }

    return json.dumps(prompt_contract, separators=(",", ":"), default=str)


def _compact_contract_tables(tables: dict[str, Any]) -> dict[str, Any]:
    compact_tables: dict[str, Any] = {}

    for table_name, table in tables.items():
        if not isinstance(table, dict):
            continue

        compact_tables[table_name] = _compact_dict(
            {
                "label": table.get("label"),
                "type": table.get("type"),
                "grain": table.get("grain"),
                "primary_time_column": table.get("primary_time_column"),
                "metadata": _compact_contract_metadata(table.get("metadata")),
                "columns": [
                    _compact_contract_column(column_name, column)
                    for column_name, column in (table.get("columns") or {}).items()
                    if isinstance(column, dict)
                ],
            }
        )

    return compact_tables


def _compact_contract_metadata(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}

    useful_keys = (
        "header_row",
        "sheet_name",
        "sheet_title",
        "configured_header_row",
    )

    compact = {
        key: metadata[key]
        for key in useful_keys
        if metadata.get(key) not in (None, "", [], {})
    }

    sheet_structure = metadata.get("sheet_structure")

    if isinstance(sheet_structure, dict):
        compact["sheet_structure"] = _compact_dict(
            {
                "header_status": sheet_structure.get("header_status"),
                "configured_header_row": sheet_structure.get("configured_header_row"),
                "relationship_use": sheet_structure.get("relationship_use"),
            }
        )

    return compact


def _compact_contract_column(column_name: str, column: dict[str, Any]) -> str:
    details = []
    label = column.get("label")

    if label and str(label).lower() != column_name.replace("_", " ").lower():
        details.append(f"label={label}")
    if column.get("data_type"):
        details.append(f"data_type={column['data_type']}")
    if column.get("type"):
        details.append(f"semantic_type={column['type']}")

    roles = [
        role
        for key, role in (
            ("is_dimension", "dimension"),
            ("is_measure", "measure"),
            ("is_time", "time"),
            ("is_id", "id"),
            ("is_foreign_key", "foreign_key"),
        )
        if column.get(key)
    ]

    if roles:
        details.append(f"roles={','.join(roles)}")
    if column.get("expression"):
        details.append(f"expression={column['expression']}")
    if column.get("unit"):
        details.append(f"unit={column['unit']}")

    if not details:
        return column_name

    return f"{column_name} ({'; '.join(map(str, details))})"


def _compact_contract_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    compact_metrics: dict[str, Any] = {}

    for metric_name, metric in metrics.items():
        if isinstance(metric, dict):
            compact_metrics[metric_name] = _compact_dict(metric)

    return compact_metrics


def _compact_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in (None, "", [], {})}
