import math

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

NodeId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"),
]
InputName = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"),
]


class CalculationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CubeQueryResult(CalculationModel):
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
    result: CubeQueryResult = Field(default_factory=CubeQueryResult)


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
    CubeQueryNode | ValueNode | FormulaNode,
    Field(discriminator="type"),
]


class CalculationDefinition(CalculationModel):
    version: Literal[1]
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    nodes: list[CalculationNode] = Field(min_length=1, max_length=50)
    output: NodeId
