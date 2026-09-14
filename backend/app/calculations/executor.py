import time

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.calculations.constants import (
    DEFAULT_CALCULATION_ROW_LIMIT,
    MAX_CALCULATION_ROW_LIMIT,
)
from app.calculations.formula import evaluate_formula
from app.calculations.graph import dependency_order, validate_graph
from app.calculations.models import (
    CalculationDefinition,
    CubeQueryNode,
    FormulaNode,
    ValueNode,
)
from app.cube.client import CubeAPIError
from app.cube.projection import QueryResultProjectionInput, semantic_response_projector
from app.cube.query import execute_cube_query_payload
from app.errors import ApplicationError, InvalidInputError, InvalidOperationError


@dataclass(frozen=True)
class ScalarResult:
    value: Decimal


@dataclass(frozen=True)
class TableResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    has_more: bool
    limit: int


CalculationResult = ScalarResult | TableResult


async def execute_definition(
    definition: CalculationDefinition,
    *,
    allowed_cube_names: set[str],
    target_node_id: str | None = None,
) -> dict[str, Any]:
    validate_graph(definition)
    target = target_node_id or definition.output
    order = dependency_order(definition, target)
    nodes = {node.id: node for node in definition.nodes}
    results: dict[str, CalculationResult] = {}
    execution_records: list[dict[str, Any]] = []
    started = time.perf_counter()

    for node_id in order:
        node = nodes[node_id]
        node_started = time.perf_counter()

        try:
            if isinstance(node, ValueNode):
                result: CalculationResult = ScalarResult(node.value)
            elif isinstance(node, FormulaNode):
                formula_inputs = {
                    name: _require_scalar(results[reference], node.id, reference)
                    for name, reference in node.inputs.items()
                }
                result = ScalarResult(evaluate_formula(node.expression, formula_inputs))
            elif isinstance(node, CubeQueryNode):
                result = await _execute_cube_query_node(node, allowed_cube_names)
            else:
                raise InvalidInputError(f"Unsupported node type for '{node_id}'")
        except CubeAPIError as exc:
            raise CubeAPIError(
                f"Node '{node_id}' could not run: {exc.message}",
                status_code=exc.status_code,
                payload=exc.payload,
            ) from exc
        except ApplicationError as exc:
            raise type(exc)(f"Node '{node_id}' could not run: {exc.message}") from exc

        results[node_id] = result
        execution_records.append(
            {
                "id": node_id,
                "type": node.type,
                "status": "succeeded",
                "duration_ms": _duration_ms(node_started),
                "result": _serialize_result_summary(result),
            }
        )

    return {
        "ok": True,
        "target_node_id": target,
        "duration_ms": _duration_ms(started),
        "execution_order": order,
        "result": _serialize_result(results[target]),
        "nodes": execution_records,
    }


async def _execute_cube_query_node(
    node: CubeQueryNode,
    allowed_cube_names: set[str],
) -> CalculationResult:
    query = dict(node.query)

    if node.result.kind == "scalar":
        requested_limit = 1
    else:
        requested_limit = _requested_table_limit(query.get("limit"))

    offset = query.get("offset", 0)

    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise InvalidInputError("Cube query offset must be a non-negative integer")

    query["limit"] = requested_limit + 1
    response = await execute_cube_query_payload(
        {"query": query},
        allowed_names=allowed_cube_names,
    )
    projected = semantic_response_projector.query_result(
        QueryResultProjectionInput(
            response=response,
            limit=requested_limit,
            offset=offset,
        )
    )
    projected_rows = projected["data"]

    if any(not isinstance(row, dict) for row in projected_rows):
        raise InvalidOperationError("Cube query returned an unsupported row shape")

    rows = list(projected_rows)

    if node.result.kind == "scalar":
        if projected["row_count"] != 1 or projected["has_more"]:
            raise InvalidOperationError(
                "Scalar Cube query must return exactly one row",
            )
        member = node.result.member

        if member is None:
            raise InvalidInputError("Scalar Cube query result requires a member")
        if member not in rows[0]:
            raise InvalidOperationError(
                f"Scalar Cube query result does not contain member '{member}'",
            )
        return ScalarResult(_numeric_decimal(rows[0][member], member))

    columns = list(dict.fromkeys(key for row in rows for key in row))

    return TableResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        has_more=bool(projected["has_more"]),
        limit=requested_limit,
    )


def _requested_table_limit(value: Any) -> int:
    if value is None:
        return DEFAULT_CALCULATION_ROW_LIMIT
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= MAX_CALCULATION_ROW_LIMIT
    ):
        raise InvalidInputError(
            f"Cube query limit must be between 1 and {MAX_CALCULATION_ROW_LIMIT}",
        )
    return value


def _numeric_decimal(value: Any, member: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise InvalidOperationError(f"Scalar member '{member}' must contain a number")

    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise InvalidOperationError(
            f"Scalar member '{member}' must contain a number",
        ) from exc

    if not decimal.is_finite() or abs(decimal) > Decimal("1e100"):
        raise InvalidOperationError(
            f"Scalar member '{member}' is outside the supported numeric range",
        )
    return decimal


def _require_scalar(
    result: CalculationResult,
    formula_node_id: str,
    input_node_id: str,
) -> Decimal:
    if not isinstance(result, ScalarResult):
        raise InvalidOperationError(
            f"Formula node '{formula_node_id}' requires scalar input '{input_node_id}'",
        )
    return result.value


def _serialize_result(result: CalculationResult) -> dict[str, Any]:
    if isinstance(result, ScalarResult):
        return {"kind": "scalar", "value": _serialize_decimal(result.value)}
    return {
        "kind": "table",
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "has_more": result.has_more,
        "limit": result.limit,
    }


def _serialize_result_summary(result: CalculationResult) -> dict[str, Any]:
    if isinstance(result, ScalarResult):
        return _serialize_result(result)
    return {
        "kind": "table",
        "columns": result.columns,
        "row_count": result.row_count,
        "has_more": result.has_more,
        "limit": result.limit,
    }


def _serialize_decimal(value: Decimal) -> int | float | str:
    if value == value.to_integral_value():
        return int(value)

    text = format(value.normalize(), "f")
    significant_digits = len(text.replace(".", "").replace("-", "").lstrip("0"))

    if significant_digits <= 15:
        return float(text)

    return text.rstrip("0").rstrip(".")


def _duration_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)
