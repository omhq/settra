from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PrunedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PrunedConnection(PrunedPayload):
    id: int | None = None
    name: str | None = None
    slug: str | None = None
    plugin: str | None = None


class PrunedIntrospectionColumn(PrunedPayload):
    name: str
    label: str | None = None
    data_type: str | None = None
    semantic_type: str | None = None
    flags: list[str] = Field(default_factory=list)
    description: str | None = None
    expression: str | None = None
    unit: str | None = None
    relationship_use: str | None = None
    relationship_block_reason: str | None = None


class PrunedIntrospectionTable(PrunedPayload):
    connection_id: int | None = None
    connection_plugin: str | None = None
    schema_: str | None = Field(default=None, alias="schema")
    table: str
    label: str | None = None
    description: str | None = None
    type: str | None = None
    grain: str | None = None
    primary_time_column: str | None = None
    column_count: int
    included_column_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    columns: list[PrunedIntrospectionColumn] = Field(default_factory=list)
    sheet_structure: dict[str, Any] = Field(default_factory=dict)
    relationship_use: str | None = None
    relationship_block_reason: str | None = None
    metric_use: str | None = None
    metric_block_reason: str | None = None
    data_samples: list[dict[str, Any]] = Field(default_factory=list)


class PrunedExistingRelationship(PrunedPayload):
    from_connection_id: int | None = None
    from_table: str | None = None
    from_column: str | None = None
    to_connection_id: int | None = None
    to_table: str | None = None
    to_column: str | None = None
    relationship_type: str | None = None
    match_type: str | None = None
    status: str | None = None


class PrunedExistingMetric(PrunedPayload):
    connection_id: int | None = None
    table: str | None = None
    name: str | None = None
    expression: str | None = None
    filters: Any = None
    time_column: str | None = None
    unit: str | None = None
    status: str | None = None


class RelationshipIntrospectionPayload(PrunedPayload):
    connections: list[PrunedConnection] = Field(default_factory=list)
    tables: list[PrunedIntrospectionTable] = Field(default_factory=list)
    existing_relationships: list[PrunedExistingRelationship] = Field(
        default_factory=list
    )


class MetricIntrospectionPayload(PrunedPayload):
    connections: list[PrunedConnection] = Field(default_factory=list)
    tables: list[PrunedIntrospectionTable] = Field(default_factory=list)
    existing_metrics: list[PrunedExistingMetric] = Field(default_factory=list)


class SemanticPromptPayload(PrunedPayload):
    tables: dict[str, Any] = Field(default_factory=dict)
    confirmed_relationships: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    rules: list[Any] = Field(default_factory=list)
