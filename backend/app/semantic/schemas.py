from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class AIRelationshipCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_connection_id: int
    from_table: str
    from_column: str
    to_connection_id: int
    to_table: str
    to_column: str
    relationship_type: Literal["one_to_one", "many_to_one"]
    match_type: str
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(min_length=12, max_length=600)
    rationale: str = Field(min_length=12, max_length=600)


class AISemanticSuggestions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relationship_candidates: list[AIRelationshipCandidate] = Field(max_length=500)
    warnings: list[str] = Field(max_length=10)


class AIMetricCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: int
    table: str
    name: str = Field(min_length=1, max_length=120)
    label: str | None = Field(max_length=180)
    expression: str = Field(min_length=2, max_length=1000)
    filters: list[str] = Field(max_length=20)
    time_column: str | None = Field(max_length=180)
    unit: str | None = Field(max_length=80)
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=12, max_length=600)


class AIMetricSuggestions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_candidates: list[AIMetricCandidate] = Field(max_length=500)
    warnings: list[str] = Field(max_length=10)


class UpdateSemanticTableRequest(BaseModel):
    label: str | None = None
    description: str | None = None
    table_type: Literal["fact", "dimension", "bridge"] | None = None
    grain: str | None = None
    primary_time_column: str | None = None
    metadata: dict[str, Any] | None = None
    hidden: bool | None = None
    status: Literal["draft", "confirmed", "published", "disabled"] | None = None


class UpdateSemanticColumnRequest(BaseModel):
    label: str | None = None
    description: str | None = None
    semantic_type: str | None = None
    expression: str | None = None
    unit: str | None = None
    is_dimension: bool | None = None
    is_measure: bool | None = None
    is_time: bool | None = None
    is_id: bool | None = None
    is_foreign_key: bool | None = None
    hidden: bool | None = None
    status: Literal["draft", "confirmed", "published", "disabled"] | None = None


class CreateRelationshipRequest(BaseModel):
    from_connection_id: int
    to_connection_id: int
    from_table_id: int
    from_column_id: int
    to_table_id: int
    to_column_id: int
    relationship_type: str = "many_to_one"
    match_type: str = "manual"
    confidence: float = 1
    status: Literal["suggested", "confirmed", "ignored", "disabled", "hidden"] = (
        "confirmed"
    )


class UpdateRelationshipRequest(BaseModel):
    relationship_type: str | None = None
    match_type: str | None = None
    confidence: float | None = None
    status: (
        Literal["suggested", "confirmed", "ignored", "disabled", "hidden"] | None
    ) = None


class CreateMetricRequest(BaseModel):
    connection_id: int
    semantic_table_id: int
    name: str
    label: str | None = None
    expression: str
    filters: list[str] = Field(default_factory=list)
    time_column: str | None = None
    unit: str | None = None
    status: Literal["draft", "confirmed", "published"] = "draft"


class UpdateMetricRequest(BaseModel):
    label: str | None = None
    expression: str | None = None
    filters: list[str] | None = None
    time_column: str | None = None
    unit: str | None = None
    status: Literal["draft", "confirmed", "published", "disabled", "hidden"] | None = (
        None
    )


class AiIntrospectRequest(BaseModel):
    connection_ids: list[int] = Field(min_length=1, max_length=12)
    model_config_id: int
    approved: bool = False
    semantic_table_ids: list[int] = Field(default_factory=list, max_length=80)
    flows: list[Literal["relationships", "metrics"]] = Field(
        min_length=1,
        max_length=2,
    )
