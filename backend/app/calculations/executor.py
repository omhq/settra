import time

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.calculations.aggregate import AggregateExecution, execute_aggregate_query
from app.calculations.constants import (
    DEFAULT_CALCULATION_ROW_LIMIT,
    MAX_CALCULATION_ROW_LIMIT,
)
from app.calculations.formula import evaluate_formula
from app.calculations.graph import dependency_order_for_targets, validate_graph
from app.calculations.models import (
    AggregateQueryNode,
    CalculationDefinition,
    CubeQueryNode,
    FormulaNode,
    ValueNode,
)
from app.calculations.parameters import (
    ResolvedParameter,
    bind_cube_query_parameters,
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
    organization_id: int | None = None,
    allowed_connection_ids: set[int] | None = None,
    parameter_values: dict[str, Any] | None = None,
    resolved_parameters: dict[str, ResolvedParameter] | None = None,
) -> dict[str, Any]:
    validate_graph(definition)

    target_ids = (
        [target_node_id]
        if target_node_id is not None
        else list(definition.outputs.values())
    )
    order = dependency_order_for_targets(definition, target_ids)
    nodes = {node.id: node for node in definition.nodes}
    results: dict[str, CalculationResult] = {}
    execution_records: list[dict[str, Any]] = []
    supplied_parameter_values = parameter_values or {}
    parameter_specs = resolved_parameters or {}
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
                result = await _execute_cube_query_node(
                    node,
                    allowed_cube_names,
                    parameter_values=supplied_parameter_values,
                    resolved_parameters=parameter_specs,
                )
            elif isinstance(node, AggregateQueryNode):
                if organization_id is None:
                    raise InvalidInputError(
                        "Aggregate query execution requires an organization"
                    )
                aggregate = await execute_aggregate_query(
                    node,
                    organization_id=organization_id,
                    allowed_connection_ids=allowed_connection_ids or set(),
                )
                result = _aggregate_result(node, aggregate)
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

    response: dict[str, Any] = {
        "ok": True,
        "target_node_id": target_node_id,
        "duration_ms": _duration_ms(started),
        "execution_order": order,
        "nodes": execution_records,
    }
    if target_node_id is not None:
        response["result"] = _serialize_result(results[target_node_id])
    else:
        response["outputs"] = {
            name: {
                "node_id": node_id,
                "result": _serialize_result(results[node_id]),
            }
            for name, node_id in definition.outputs.items()
        }
    return response


async def _execute_cube_query_node(
    node: CubeQueryNode,
    allowed_cube_names: set[str],
    *,
    parameter_values: dict[str, Any],
    resolved_parameters: dict[str, ResolvedParameter],
) -> CalculationResult:
    query = bind_cube_query_parameters(
        node.query,
        resolved_parameters,
        parameter_values,
    )

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


def _aggregate_result(
    node: AggregateQueryNode,
    aggregate: AggregateExecution,
) -> CalculationResult:
    if node.result.kind == "scalar":
        if aggregate.row_count != 1:
            raise InvalidOperationError(
                "Scalar aggregate query must return exactly one row"
            )

        member = node.result.member

        if member is None:
            raise InvalidInputError("Scalar aggregate query requires a result member")
        if member not in aggregate.rows[0]:
            raise InvalidOperationError(
                f"Scalar aggregate result does not contain member '{member}'"
            )

        return ScalarResult(_numeric_decimal(aggregate.rows[0][member], member))

    return TableResult(
        columns=aggregate.columns,
        rows=aggregate.rows,
        row_count=aggregate.row_count,
        has_more=aggregate.has_more,
        limit=aggregate.limit or DEFAULT_CALCULATION_ROW_LIMIT,
    )


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
