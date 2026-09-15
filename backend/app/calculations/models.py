import math

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.calculations.constants import (
    MAX_AGGREGATE_FILTERS,
    MAX_AGGREGATE_FILTER_VALUES,
    MAX_AGGREGATE_GROUP_COLUMNS,
    MAX_AGGREGATE_MEASURES,
    MAX_CALCULATION_OUTPUTS,
    MAX_CALCULATION_PARAMETERS,
)

NodeId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"),
]
InputName = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"),
]
SourceName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
AggregateMeasureName = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$"),
]


class CalculationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CalculationParameter(CalculationModel):
    id: InputName
    member: str = Field(min_length=3, max_length=255)

    @field_validator("member")
    @classmethod
    def validate_member_name(cls, value: str) -> str:
        cube_name, separator, member_name = value.partition(".")

        if not separator or not cube_name.strip() or not member_name.strip():
            raise ValueError("member must be a qualified Cube dimension")
        if value != value.strip() or any(
            part != part.strip() for part in value.split(".")
        ):
            raise ValueError("member must not contain surrounding whitespace")
        return value


class QueryResult(CalculationModel):
    kind: Literal["table", "scalar"] = "table"
    member: str | None = None

    @model_validator(mode="after")
    def validate_member(self):
        if self.kind == "scalar" and not self.member:
            raise ValueError("member is required when result kind is scalar")
        if self.kind == "table" and self.member is not None:
            raise ValueError("member is only allowed when result kind is scalar")
        return self


class CubeQueryNode(CalculationModel):
    id: NodeId
    type: Literal["cube_query"]
    query: dict[str, Any]
    result: QueryResult = Field(default_factory=QueryResult)


class AggregateQuerySource(CalculationModel):
    connection: SourceName
    table: SourceName


class AggregateMeasure(CalculationModel):
    name: AggregateMeasureName
    function: Literal[
        "sum",
        "average",
        "min",
        "max",
        "count",
        "count_distinct",
    ]
    column: SourceName | None = None

    @model_validator(mode="after")
    def validate_column(self):
        if self.function != "count" and self.column is None:
            raise ValueError(f"column is required for {self.function}")
        return self


class AggregateFilter(CalculationModel):
    column: SourceName
    operator: Literal[
        "equals",
        "not_equals",
        "greater_than",
        "greater_than_or_equal",
        "less_than",
        "less_than_or_equal",
        "in",
        "not_in",
        "is_null",
        "not_null",
    ]
    value: Any = None
    values: list[Any] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_AGGREGATE_FILTER_VALUES,
    )

    @model_validator(mode="after")
    def validate_values(self):
        single_value_operators = {
            "equals",
            "not_equals",
            "greater_than",
            "greater_than_or_equal",
            "less_than",
            "less_than_or_equal",
        }
        list_value_operators = {"in", "not_in"}

        if self.operator in single_value_operators:
            if self.value is None or self.values is not None:
                raise ValueError(f"value is required for {self.operator}")

            _validate_filter_value(self.value)
        elif self.operator in list_value_operators:
            if self.value is not None or self.values is None:
                raise ValueError(f"values is required for {self.operator}")
            for value in self.values:
                _validate_filter_value(value)
        elif self.value is not None or self.values is not None:
            raise ValueError(f"{self.operator} does not accept value or values")

        return self


class AggregateQueryNode(CalculationModel):
    id: NodeId
    type: Literal["aggregate_query"]
    source: AggregateQuerySource
    measures: list[AggregateMeasure] = Field(
        min_length=1,
        max_length=MAX_AGGREGATE_MEASURES,
    )
    group_by: list[SourceName] = Field(
        default_factory=list,
        max_length=MAX_AGGREGATE_GROUP_COLUMNS,
    )
    filters: list[AggregateFilter] = Field(
        default_factory=list,
        max_length=MAX_AGGREGATE_FILTERS,
    )
    limit: int | None = None
    result: QueryResult = Field(default_factory=QueryResult)

    @model_validator(mode="after")
    def validate_shape(self):
        measure_names = [measure.name for measure in self.measures]
        duplicate_measures = sorted(
            name for name in set(measure_names) if measure_names.count(name) > 1
        )

        if duplicate_measures:
            raise ValueError(
                "measure names must be unique: " + ", ".join(duplicate_measures)
            )

        duplicate_groups = sorted(
            name for name in set(self.group_by) if self.group_by.count(name) > 1
        )

        if duplicate_groups:
            raise ValueError(
                "group_by columns must be unique: " + ", ".join(duplicate_groups)
            )

        collisions = sorted(set(measure_names) & set(self.group_by))

        if collisions:
            raise ValueError(
                "measure names cannot match group_by columns: " + ", ".join(collisions)
            )

        if self.result.kind == "scalar":
            if self.group_by:
                raise ValueError("scalar aggregate queries cannot use group_by")
            if self.limit is not None:
                raise ValueError("scalar aggregate queries cannot set limit")
            if self.result.member not in measure_names:
                raise ValueError(
                    "scalar result member must match an aggregate measure name"
                )

        return self


class ValueNode(CalculationModel):
    id: NodeId
    type: Literal["value"]
    value: Decimal

    @field_validator("value", mode="before")
    @classmethod
    def validate_number_type(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise ValueError("value must be a YAML number")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("value must be finite")
        return value

    @field_validator("value")
    @classmethod
    def validate_number_range(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or abs(value) > Decimal("1e100"):
            raise ValueError("value must be finite and no larger than 1e100")
        return value


class FormulaNode(CalculationModel):
    id: NodeId
    type: Literal["formula"]
    inputs: dict[InputName, NodeId] = Field(min_length=1, max_length=50)
    expression: str = Field(min_length=1, max_length=512)


CalculationNode = Annotated[
    CubeQueryNode | AggregateQueryNode | ValueNode | FormulaNode,
    Field(discriminator="type"),
]


class CalculationDefinition(CalculationModel):
    version: Literal[1]
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    parameters: list[CalculationParameter] = Field(
        default_factory=list,
        max_length=MAX_CALCULATION_PARAMETERS,
    )
    nodes: list[CalculationNode] = Field(min_length=1, max_length=50)
    outputs: dict[NodeId, NodeId] = Field(
        min_length=1,
        max_length=MAX_CALCULATION_OUTPUTS,
    )

    @model_validator(mode="after")
    def validate_parameter_ids(self):
        parameter_ids = [parameter.id for parameter in self.parameters]
        duplicates = sorted(
            parameter_id
            for parameter_id in set(parameter_ids)
            if parameter_ids.count(parameter_id) > 1
        )

        if duplicates:
            raise ValueError("parameter ids must be unique: " + ", ".join(duplicates))

        return self


def _validate_filter_value(value: Any) -> None:
    if isinstance(value, (str, int, float, bool, Decimal, date, datetime)):
        if isinstance(value, str) and len(value) > 1000:
            raise ValueError("filter strings must be 1000 characters or shorter")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("filter values must be finite")
        if isinstance(value, Decimal) and not value.is_finite():
            raise ValueError("filter values must be finite")
        return

    raise ValueError("filter values must be scalar YAML values")
