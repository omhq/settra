from typing import Any

from app.pruning.consts import (
    METRIC_NAME_HINTS,
    RELATIONSHIP_NAME_HINTS,
    SEMANTIC_PROMPT_COLUMN_LIMIT,
)
from app.pruning.schemas import SemanticPromptPayload
from app.pruning.utils import (
    compact_dict,
    compact_label,
    compact_text,
    model_to_prompt_dict,
    tokens,
)


def prune_semantics_for_prompt(semantics: dict[str, Any]) -> dict[str, Any]:
    return SemanticPromptPruner(semantics).payload()


class SemanticPromptPruner:
    def __init__(self, semantics: dict[str, Any]) -> None:
        self.semantics = semantics

    def payload(self) -> dict[str, Any]:
        payload = SemanticPromptPayload(
            tables=self._compact_tables(self.semantics.get("tables") or {}),
            confirmed_relationships=[
                compact_dict(relationship)
                for relationship in self.semantics.get("confirmed_relationships") or []
                if isinstance(relationship, dict)
            ],
            metrics=self._compact_metrics(self.semantics.get("metrics") or {}),
            rules=self.semantics.get("rules") or [],
        )
        return model_to_prompt_dict(payload)

    def _compact_tables(self, tables: dict[str, Any]) -> dict[str, Any]:
        compact_tables: dict[str, Any] = {}

        for table_name, table in tables.items():
            if not isinstance(table, dict):
                continue

            compact_tables[table_name] = compact_dict(
                {
                    "label": table.get("label"),
                    "type": table.get("type"),
                    "grain": table.get("grain"),
                    "primary_time_column": table.get("primary_time_column"),
                    "metadata": self._compact_metadata(table.get("metadata")),
                    "columns": [
                        self._compact_column(column_name, column)
                        for column_name, column in self._select_columns(
                            table.get("columns") or {},
                            primary_time_column=str(
                                table.get("primary_time_column") or ""
                            ),
                        )
                        if isinstance(column, dict)
                    ],
                }
            )

        return compact_tables

    def _select_columns(
        self,
        columns: dict[str, Any],
        *,
        primary_time_column: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        items = [
            (name, column)
            for name, column in columns.items()
            if isinstance(column, dict)
        ]

        if len(items) <= SEMANTIC_PROMPT_COLUMN_LIMIT:
            return items

        scored = [
            (
                self._column_score(name, column, primary_time_column),
                index,
                name,
                column,
            )
            for index, (name, column) in enumerate(items)
        ]
        selected = sorted(scored, key=lambda item: (-item[0], item[1]))[
            :SEMANTIC_PROMPT_COLUMN_LIMIT
        ]
        selected_indices = {index for _, index, _, _ in selected}

        return [
            (name, column)
            for index, (name, column) in enumerate(items)
            if index in selected_indices
        ]

    def _column_score(
        self,
        name: str,
        column: dict[str, Any],
        primary_time_column: str,
    ) -> int:
        column_tokens = tokens(name)
        semantic_type = str(column.get("type") or "").lower()
        score = 0

        if name == primary_time_column:
            score += 100
        if column.get("is_measure"):
            score += 90
        if column.get("is_time"):
            score += 85
        if column.get("is_id") or column.get("is_foreign_key"):
            score += 65
        if semantic_type in {
            "money",
            "money_minor_units",
            "number",
            "timestamp",
            "date",
            "email",
            "domain",
            "id",
            "foreign_key",
        }:
            score += 45
        if column.get("expression"):
            score += 40
        if column_tokens & (METRIC_NAME_HINTS | RELATIONSHIP_NAME_HINTS):
            score += 25

        return score

    def _compact_metadata(self, metadata: Any) -> dict[str, Any]:
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
            compact["sheet_structure"] = compact_dict(
                {
                    "header_status": sheet_structure.get("header_status"),
                    "configured_header_row": sheet_structure.get(
                        "configured_header_row"
                    ),
                    "relationship_use": sheet_structure.get("relationship_use"),
                }
            )

        return compact

    def _compact_column(self, column_name: str, column: dict[str, Any]) -> str:
        details = []
        label = compact_label(column_name, column.get("label"))
        semantic_type = column.get("type")

        if label:
            details.append(f"label={label}")
        if semantic_type:
            details.append(f"semantic_type={semantic_type}")
        elif column.get("data_type"):
            details.append(f"data_type={column['data_type']}")

        roles = [
            role
            for key, role in (
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
            details.append(f"expression={compact_text(column['expression'], 180)}")
        if column.get("unit"):
            details.append(f"unit={column['unit']}")

        if not details:
            return column_name

        return f"{column_name} ({'; '.join(map(str, details))})"

    def _compact_metrics(self, metrics: dict[str, Any]) -> dict[str, Any]:
        compact_metrics: dict[str, Any] = {}

        for metric_name, metric in metrics.items():
            if isinstance(metric, dict):
                compact_metrics[metric_name] = compact_dict(
                    {
                        "label": metric.get("label"),
                        "table": metric.get("table"),
                        "expression": compact_text(metric.get("expression"), 220),
                        "filters": metric.get("filters"),
                        "time_column": metric.get("time_column"),
                        "unit": metric.get("unit"),
                    }
                )

        return compact_metrics
