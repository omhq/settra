import json
import logging
import time
from collections.abc import Awaitable, Callable
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
    CalculationNode,
    CalculationOutputNode,
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

logger = logging.getLogger(__name__)


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
CalculationOutputExecutor = Callable[
    [CalculationOutputNode],
    Awaitable[CalculationResult],
]


async def execute_definition(
    definition: CalculationDefinition,
    *,
    allowed_cube_names: set[str],
    target_node_id: str | None = None,
    organization_id: int | None = None,
    allowed_connection_ids: set[int] | None = None,
    parameter_values: dict[str, Any] | None = None,
    resolved_parameters: dict[str, ResolvedParameter] | None = None,
    calculation_output_executor: CalculationOutputExecutor | None = None,
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
            elif isinstance(node, CalculationOutputNode):
                if calculation_output_executor is None:
                    raise InvalidOperationError(
                        "Calculation output execution requires an App calculation resolver"
                    )
                result = await calculation_output_executor(node)
            else:
                raise InvalidInputError(f"Unsupported node type for '{node_id}'")
        except CubeAPIError as exc:
            _log_node_failure(definition.name, node, exc)
            raise CubeAPIError(
                f"Node '{node_id}' could not run: {exc.message}",
                status_code=exc.status_code,
                payload=exc.payload,
            ) from exc
        except ApplicationError as exc:
            _log_node_failure(definition.name, node, exc)
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
    if value is None:
        raise InvalidOperationError(
            f"Scalar member '{member}' returned no value; the selected filter "
            "combination may match no rows"
        )
    if isinstance(value, bool):
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


def _log_node_failure(
    calculation_name: str,
    node: CalculationNode,
    exc: ApplicationError | CubeAPIError,
) -> None:
    context: dict[str, Any] = {
        "calculation": calculation_name,
        "node_id": node.id,
        "node_type": node.type,
        "error_type": type(exc).__name__,
    }

    if isinstance(exc, ApplicationError):
        context["error_code"] = exc.code
        context["error_message"] = exc.message
    else:
        context["upstream_status"] = exc.status_code
        context["retryable"] = exc.retryable

    if isinstance(node, CubeQueryNode):
        context.update(_cube_query_log_context(node))
    elif isinstance(node, AggregateQueryNode):
        context.update(
            {
                "source": {
                    "connection": node.source.connection,
                    "table": node.source.table,
                },
                "measures": [
                    {
                        "name": measure.name,
                        "function": measure.function,
                        "column": measure.column,
                    }
                    for measure in node.measures
                ],
                "filters": [
                    {"column": item.column, "operator": item.operator}
                    for item in node.filters
                ],
                "result_kind": node.result.kind,
                "result_member": node.result.member,
            }
        )
    elif isinstance(node, FormulaNode):
        context["dependencies"] = sorted(node.inputs.values())
    elif isinstance(node, CalculationOutputNode):
        context.update(
            {
                "referenced_calculation": node.calculation,
                "referenced_output": node.output,
            }
        )

    logger.warning(
        "Calculation node failed context=%s",
        json.dumps(context, separators=(",", ":"), sort_keys=True),
    )


def _cube_query_log_context(node: CubeQueryNode) -> dict[str, Any]:
    query = node.query
    members = [
        member
        for collection in ("measures", "dimensions")
        for member in query.get(collection, [])
        if isinstance(member, str)
    ]
    time_dimensions = query.get("timeDimensions")

    for item in time_dimensions if isinstance(time_dimensions, list) else []:
        if isinstance(item, dict) and isinstance(item.get("dimension"), str):
            members.append(item["dimension"])

    filters = query.get("filters")

    return {
        "query_members": sorted(set(members)),
        "filters": [
            shape
            for item in (filters if isinstance(filters, list) else [])
            if (shape := _cube_filter_log_shape(item)) is not None
        ],
        "result_kind": node.result.kind,
        "result_member": node.result.member,
    }


def _cube_filter_log_shape(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    for group_key in ("and", "or"):
        group = item.get(group_key)

        if isinstance(group, list):
            return {
                group_key: [
                    shape
                    for child in group
                    if (shape := _cube_filter_log_shape(child)) is not None
                ]
            }

    shape = {
        key: item[key]
        for key in ("member", "operator", "parameter")
        if isinstance(item.get(key), str)
    }

    return shape or None


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


def calculation_result_from_payload(payload: dict[str, Any]) -> CalculationResult:
    kind = payload.get("kind")

    if kind == "scalar":
        return ScalarResult(
            _numeric_decimal(payload.get("value"), "calculation output")
        )
    if kind != "table":
        raise InvalidOperationError("Calculation output returned an unsupported result")

    columns = payload.get("columns")
    rows = payload.get("rows")
    row_count = payload.get("row_count")
    has_more = payload.get("has_more")
    limit = payload.get("limit")

    if (
        not isinstance(columns, list)
        or any(not isinstance(column, str) for column in columns)
        or not isinstance(rows, list)
        or any(not isinstance(row, dict) for row in rows)
        or isinstance(row_count, bool)
        or not isinstance(row_count, int)
        or not isinstance(has_more, bool)
        or isinstance(limit, bool)
        or not isinstance(limit, int)
    ):
        raise InvalidOperationError(
            "Calculation output returned an invalid table result"
        )

    return TableResult(
        columns=columns,
        rows=rows,
        row_count=row_count,
        has_more=has_more,
        limit=limit,
    )


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
