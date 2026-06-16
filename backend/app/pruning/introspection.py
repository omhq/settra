from typing import Any, Literal

from app.pruning.consts import (
    METRIC_INTROSPECTION_COLUMN_LIMIT,
    METRIC_NAME_HINTS,
    METRIC_SAMPLE_FIELD_LIMIT,
    RELATIONSHIP_INTROSPECTION_COLUMN_LIMIT,
    RELATIONSHIP_NAME_HINTS,
)
from app.pruning.schemas import (
    MetricIntrospectionPayload,
    PrunedConnection,
    PrunedExistingMetric,
    PrunedExistingRelationship,
    PrunedIntrospectionColumn,
    PrunedIntrospectionTable,
    RelationshipIntrospectionPayload,
)
from app.pruning.utils import (
    column_flags,
    compact_dict,
    compact_label,
    compact_list,
    compact_text,
    compact_value,
    model_to_prompt_dict,
    tokens,
)

IntrospectionFlow = Literal["relationships", "metrics"]


def relationship_introspection_payload(context: dict[str, Any]) -> dict[str, Any]:
    return IntrospectionPruner(context).relationship_payload()


def metric_introspection_payload(context: dict[str, Any]) -> dict[str, Any]:
    return IntrospectionPruner(context).metric_payload()


class IntrospectionPruner:
    def __init__(self, context: dict[str, Any]) -> None:
        self.context = context
        self.tables = context.get("table_context") or []

    def relationship_payload(self) -> dict[str, Any]:
        payload = RelationshipIntrospectionPayload(
            connections=self._compact_connections(),
            tables=self._prune_tables(flow="relationships"),
            existing_relationships=self._compact_existing_relationships(),
        )
        return model_to_prompt_dict(payload)

    def metric_payload(self) -> dict[str, Any]:
        payload = MetricIntrospectionPayload(
            connections=self._compact_connections(),
            tables=self._prune_tables(flow="metrics"),
            existing_metrics=self._compact_existing_metrics(),
        )
        return model_to_prompt_dict(payload)

    def _prune_tables(
        self,
        *,
        flow: IntrospectionFlow,
    ) -> list[PrunedIntrospectionTable]:
        all_table_tokens = set()
        table_tokens_by_index = []

        for table in self.tables:
            current_tokens = self._table_entity_tokens(table)
            table_tokens_by_index.append(current_tokens)
            all_table_tokens.update(current_tokens)

        pruned = []

        for index, table in enumerate(self.tables):
            peer_tokens = all_table_tokens - table_tokens_by_index[index]
            pruned.append(
                self._prune_table(
                    table,
                    flow=flow,
                    peer_tokens=peer_tokens,
                )
            )

        return pruned

    def _prune_table(
        self,
        table: dict[str, Any],
        *,
        flow: IntrospectionFlow,
        peer_tokens: set[str],
    ) -> PrunedIntrospectionTable:
        columns = [
            column
            for column in table.get("columns") or []
            if isinstance(column, dict) and column.get("name")
        ]
        selected_columns = self._select_columns(
            columns,
            flow=flow,
            peer_tokens=peer_tokens,
            primary_time_column=str(table.get("primary_time_column") or ""),
        )
        selected_column_names = [
            str(column.get("name")) for column in selected_columns if column.get("name")
        ]
        samples = []

        if flow == "metrics":
            samples = self._prune_data_samples(
                table.get("data_samples") or [],
                selected_column_names=selected_column_names,
            )

        return PrunedIntrospectionTable(
            connection_id=table.get("connection_id"),
            connection_plugin=table.get("connection_plugin"),
            schema=table.get("schema"),
            table=str(table.get("table") or ""),
            label=compact_text(table.get("label"), 80),
            description=(
                compact_text(table.get("description"), 180)
                if flow == "metrics"
                else None
            ),
            type=table.get("type"),
            grain=compact_text(table.get("grain"), 120),
            primary_time_column=table.get("primary_time_column"),
            column_count=len(columns),
            included_column_count=len(selected_columns),
            metadata=self._compact_metadata(table.get("metadata")),
            columns=[
                self._compact_column(column, flow=flow) for column in selected_columns
            ],
            sheet_structure=self._compact_sheet_structure(table.get("sheet_structure")),
            relationship_use=compact_text(table.get("relationship_use"), 240),
            relationship_block_reason=compact_text(
                table.get("relationship_block_reason"),
                240,
            ),
            metric_use=(
                compact_text(table.get("metric_use"), 240)
                if flow == "metrics"
                else None
            ),
            metric_block_reason=(
                compact_text(table.get("metric_block_reason"), 240)
                if flow == "metrics"
                else None
            ),
            data_samples=samples,
        )

    def _select_columns(
        self,
        columns: list[dict[str, Any]],
        *,
        flow: IntrospectionFlow,
        peer_tokens: set[str],
        primary_time_column: str,
    ) -> list[dict[str, Any]]:
        limit = (
            RELATIONSHIP_INTROSPECTION_COLUMN_LIMIT
            if flow == "relationships"
            else METRIC_INTROSPECTION_COLUMN_LIMIT
        )

        if len(columns) <= limit:
            return columns

        scored = []

        for index, column in enumerate(columns):
            score = (
                self._relationship_column_score(column, peer_tokens)
                if flow == "relationships"
                else self._metric_column_score(column, primary_time_column)
            )

            scored.append((score, index, column))

        positive = [item for item in scored if item[0] > 0]
        selected = sorted(positive or scored, key=lambda item: (-item[0], item[1]))[
            :limit
        ]
        selected_indices = {index for _, index, _ in selected}

        return [
            column for index, column in enumerate(columns) if index in selected_indices
        ]

    def _relationship_column_score(
        self,
        column: dict[str, Any],
        peer_tokens: set[str],
    ) -> int:
        name = str(column.get("name") or "")
        column_tokens = tokens(name)
        flags = column_flags(column)
        semantic_type = str(column.get("semantic_type") or "").lower()
        score = 0

        if "id" in flags:
            score += 90
        if "foreign_key" in flags:
            score += 80
        if semantic_type in {"id", "foreign_key"}:
            score += 80
        if semantic_type in {"email", "domain"}:
            score += 75
        if name == "id" or name.endswith("_id"):
            score += 85
        if {"id", "uuid", "guid", "key"} & column_tokens:
            score += 65
        if {"email", "domain"} & column_tokens:
            score += 70
        if column_tokens & peer_tokens:
            score += 55
        if column_tokens & RELATIONSHIP_NAME_HINTS:
            score += 25
        if column.get("relationship_use") == "blocked":
            score += 20

        return score

    def _metric_column_score(
        self,
        column: dict[str, Any],
        primary_time_column: str,
    ) -> int:
        name = str(column.get("name") or "")
        column_tokens = tokens(name)
        flags = column_flags(column)
        semantic_type = str(column.get("semantic_type") or "").lower()
        score = 0

        if name and name == primary_time_column:
            score += 100
        if "measure" in flags:
            score += 90
        if "time" in flags:
            score += 85
        if semantic_type in {"money", "money_minor_units", "number"}:
            score += 80
        if semantic_type in {"date", "timestamp", "time"}:
            score += 75
        if "id" in flags or "foreign_key" in flags:
            score += 35
        if semantic_type in {"boolean", "category", "text", "email", "domain"}:
            score += 20
        if column_tokens & METRIC_NAME_HINTS:
            score += 35
        if column.get("expression"):
            score += 20

        return score

    def _compact_column(
        self,
        column: dict[str, Any],
        *,
        flow: IntrospectionFlow,
    ) -> PrunedIntrospectionColumn:
        flags = [flag for flag in column_flags(column) if flag != "dimension"]

        return PrunedIntrospectionColumn(
            name=str(column.get("name") or ""),
            label=compact_label(column.get("name"), column.get("label")),
            data_type=column.get("data_type"),
            semantic_type=column.get("semantic_type"),
            flags=flags,
            description=(
                compact_text(column.get("description"), 100)
                if flow == "metrics"
                else None
            ),
            expression=(
                compact_text(column.get("expression"), 140)
                if flow == "metrics"
                else None
            ),
            unit=column.get("unit") if flow == "metrics" else None,
            relationship_use=compact_text(column.get("relationship_use"), 240),
            relationship_block_reason=compact_text(
                column.get("relationship_block_reason"),
                240,
            ),
        )

    def _compact_connections(self) -> list[PrunedConnection]:
        return [
            PrunedConnection(
                id=connection.get("id"),
                name=connection.get("name"),
                slug=connection.get("slug"),
                plugin=connection.get("plugin"),
            )
            for connection in self.context.get("connections") or []
            if isinstance(connection, dict)
        ]

    def _compact_existing_relationships(self) -> list[PrunedExistingRelationship]:
        return [
            PrunedExistingRelationship(
                from_connection_id=item.get("from_connection_id"),
                from_table=item.get("from_table"),
                from_column=item.get("from_column"),
                to_connection_id=item.get("to_connection_id"),
                to_table=item.get("to_table"),
                to_column=item.get("to_column"),
                relationship_type=item.get("relationship_type"),
                match_type=item.get("match_type"),
                status=item.get("status"),
            )
            for item in self.context.get("existing_relationships") or []
            if isinstance(item, dict)
        ]

    def _compact_existing_metrics(self) -> list[PrunedExistingMetric]:
        return [
            PrunedExistingMetric(
                connection_id=item.get("connection_id"),
                table=item.get("table"),
                name=item.get("name"),
                expression=item.get("expression"),
                filters=item.get("filters"),
                time_column=item.get("time_column"),
                unit=item.get("unit"),
                status=item.get("status"),
            )
            for item in self.context.get("existing_metrics") or []
            if isinstance(item, dict)
        ]

    def _compact_metadata(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}

        useful_keys = (
            "header_row",
            "sheet_name",
            "sheet_title",
            "configured_header_row",
        )

        return compact_dict(
            {key: value.get(key) for key in useful_keys if key in value}
        )

    def _compact_sheet_structure(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}

        return compact_dict(
            {
                "header_status": value.get("header_status"),
                "relationship_use": value.get("relationship_use"),
                "relationship_block_reason": compact_text(
                    value.get("relationship_block_reason"),
                    240,
                ),
                "configured_header_row": value.get("configured_header_row"),
                "exposed_columns": compact_list(value.get("exposed_columns"), 18),
                "configured_header_columns": compact_list(
                    value.get("configured_header_columns"),
                    18,
                ),
            }
        )

    def _prune_data_samples(
        self,
        samples: list[Any],
        *,
        selected_column_names: list[str],
    ) -> list[dict[str, Any]]:
        pruned = []

        for sample in samples[:2]:
            if not isinstance(sample, dict):
                continue

            kept: dict[str, Any] = {}
            field_count = 0

            for key, value in sample.items():
                if not str(key).startswith("_"):
                    continue

                compacted = compact_value(value, max_chars=70)

                if compacted not in (None, "", [], {}):
                    kept[key] = compacted

            for key in selected_column_names:
                if field_count >= METRIC_SAMPLE_FIELD_LIMIT:
                    break
                if key not in sample or key in kept:
                    continue

                compacted = compact_value(sample[key], max_chars=70)

                if compacted not in (None, "", [], {}):
                    kept[key] = compacted
                    field_count += 1

            fallback_limit = min(8, METRIC_SAMPLE_FIELD_LIMIT)

            if field_count < fallback_limit:
                for key, value in sample.items():
                    if field_count >= fallback_limit:
                        break
                    if key in kept or str(key).startswith("_"):
                        continue

                    compacted = compact_value(value, max_chars=70)

                    if compacted not in (None, "", [], {}):
                        kept[key] = compacted
                        field_count += 1

            if kept:
                pruned.append(kept)

        return pruned

    def _table_entity_tokens(self, table: dict[str, Any]) -> set[str]:
        return tokens(
            " ".join(
                str(table.get(key) or "")
                for key in ("table", "label", "description", "grain")
            )
        )
