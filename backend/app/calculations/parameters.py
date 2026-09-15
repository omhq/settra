import copy
import math

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.calculations.constants import MAX_CALCULATION_PARAMETER_VALUES
from app.calculations.models import CalculationDefinition, CubeQueryNode
from app.errors import InvalidInputError, ResourceNotFoundError

FILTER_OPERATORS_BY_TYPE = {
    "string": (
        "equals",
        "notEquals",
        "contains",
        "notContains",
        "startsWith",
        "notStartsWith",
        "endsWith",
        "notEndsWith",
    ),
    "number": (
        "equals",
        "notEquals",
        "gt",
        "gte",
        "lt",
        "lte",
    ),
    "time": (
        "equals",
        "notEquals",
        "beforeDate",
        "beforeOrOnDate",
        "afterDate",
        "afterOrOnDate",
        "inDateRange",
        "notInDateRange",
    ),
    "boolean": (
        "equals",
        "notEquals",
    ),
}
MULTI_VALUE_OPERATORS = {
    "equals",
    "notEquals",
    "contains",
    "notContains",
    "startsWith",
    "notStartsWith",
    "endsWith",
    "notEndsWith",
}
DATE_RANGE_OPERATORS = {"inDateRange", "notInDateRange"}
PARAMETER_INPUT_BY_TYPE = {
    "string": "select",
    "number": "number",
    "time": "date",
    "boolean": "boolean",
}


@dataclass(frozen=True)
class ParameterBinding:
    node_id: str
    parameter_id: str
    member: str
    operator: str


@dataclass(frozen=True)
class ResolvedParameter:
    id: str
    member: str
    title: str
    type: str
    operators: tuple[str, ...]

    def descriptor(self) -> dict[str, Any]:
        cardinality = (
            "range"
            if any(operator in DATE_RANGE_OPERATORS for operator in self.operators)
            else (
                "one_or_more"
                if self.operators
                and all(
                    operator in MULTI_VALUE_OPERATORS for operator in self.operators
                )
                else "single"
            )
        )

        return {
            "id": self.id,
            "member": self.member,
            "title": self.title,
            "type": self.type,
            "input": PARAMETER_INPUT_BY_TYPE[self.type],
            "cardinality": cardinality,
            "required": True,
            "operators": list(self.operators),
            "options_available": self.type in {"string", "boolean"},
        }


def calculation_parameter_bindings(
    definition: CalculationDefinition,
    *,
    node_ids: set[str] | None = None,
) -> list[ParameterBinding]:
    bindings: list[ParameterBinding] = []

    for node in definition.nodes:
        if not isinstance(node, CubeQueryNode):
            continue
        if node_ids is not None and node.id not in node_ids:
            continue

        query_parameter_count = _count_parameter_keys(node.query)
        filters = node.query.get("filters")
        node_bindings: list[ParameterBinding] = []

        if filters is not None:
            if not isinstance(filters, list):
                if query_parameter_count:
                    raise InvalidInputError(
                        f"Cube query node '{node.id}': filters must be a list"
                    )
            else:
                for item in filters:
                    _collect_filter_bindings(item, node.id, node_bindings)

        if query_parameter_count != len(node_bindings):
            raise InvalidInputError(
                f"Cube query node '{node.id}': parameter is only allowed on a filter"
            )

        bindings.extend(node_bindings)

    return bindings


def parameter_node_ids(
    definition: CalculationDefinition,
    parameter_id: str,
) -> set[str]:
    return {
        binding.node_id
        for binding in calculation_parameter_bindings(definition)
        if binding.parameter_id == parameter_id
    }


def resolve_calculation_parameters(
    definition: CalculationDefinition,
    meta: dict[str, Any],
    *,
    node_ids: set[str] | None = None,
    require_all_declarations: bool = True,
) -> dict[str, ResolvedParameter]:
    declarations = {parameter.id: parameter for parameter in definition.parameters}
    bindings = calculation_parameter_bindings(definition, node_ids=node_ids)
    bound_ids = {binding.parameter_id for binding in bindings}
    unknown = sorted(bound_ids - declarations.keys())

    if unknown:
        raise InvalidInputError(
            "Cube filters reference undeclared parameters: " + ", ".join(unknown)
        )

    if require_all_declarations:
        unused = sorted(declarations.keys() - bound_ids)

        if unused:
            raise InvalidInputError(
                "Calculation parameters are not bound to Cube filters: "
                + ", ".join(unused)
            )

    dimensions = _dimension_index(meta)
    resolved: dict[str, ResolvedParameter] = {}

    for parameter_id in sorted(bound_ids):
        declaration = declarations[parameter_id]
        dimension = dimensions.get(declaration.member)

        if dimension is None:
            raise ResourceNotFoundError(
                f"Calculation parameter '{parameter_id}' references unavailable "
                f"Cube dimension '{declaration.member}'"
            )

        dimension_type = dimension.get("type")

        if (
            not isinstance(dimension_type, str)
            or dimension_type not in FILTER_OPERATORS_BY_TYPE
        ):
            raise InvalidInputError(
                f"Calculation parameter '{parameter_id}' uses unsupported Cube "
                f"dimension type '{dimension_type}'"
            )

        parameter_bindings = [
            binding for binding in bindings if binding.parameter_id == parameter_id
        ]
        operators: list[str] = []

        for binding in parameter_bindings:
            if binding.member != declaration.member:
                raise InvalidInputError(
                    f"Calculation parameter '{parameter_id}' is declared for "
                    f"'{declaration.member}' but node '{binding.node_id}' binds it "
                    f"to '{binding.member}'"
                )
            if binding.operator not in FILTER_OPERATORS_BY_TYPE[dimension_type]:
                raise InvalidInputError(
                    f"Cube filter operator '{binding.operator}' is not valid for "
                    f"{dimension_type} parameter '{parameter_id}'"
                )
            if binding.operator not in operators:
                operators.append(binding.operator)

        title = dimension.get("title") or dimension.get("shortTitle")
        resolved[parameter_id] = ResolvedParameter(
            id=parameter_id,
            member=declaration.member,
            title=str(title or declaration.member),
            type=dimension_type,
            operators=tuple(operators),
        )

    return resolved


def validate_parameter_values(
    definition: CalculationDefinition,
    resolved: dict[str, ResolvedParameter],
    values: dict[str, Any],
) -> None:
    declared_ids = {parameter.id for parameter in definition.parameters}
    unknown = sorted(values.keys() - declared_ids)

    if unknown:
        raise InvalidInputError(
            "Execution supplied unknown calculation parameters: " + ", ".join(unknown)
        )

    missing = sorted(resolved.keys() - values)

    if missing:
        raise InvalidInputError(
            "Execution requires calculation parameters: " + ", ".join(missing)
        )

    for parameter_id, parameter in resolved.items():
        for operator in parameter.operators:
            _cube_filter_values(parameter, operator, values[parameter_id])


def bind_cube_query_parameters(
    query: dict[str, Any],
    resolved: dict[str, ResolvedParameter],
    values: dict[str, Any],
) -> dict[str, Any]:
    bound_query = copy.deepcopy(query)
    filters = bound_query.get("filters")

    if not isinstance(filters, list):
        return bound_query

    for item in filters:
        _bind_filter_item(item, resolved, values)

    return bound_query


def parameter_options_query(
    parameter: ResolvedParameter,
    *,
    search: str | None,
    limit: int,
) -> dict[str, Any]:
    query: dict[str, Any] = {
        "dimensions": [parameter.member],
        "order": {parameter.member: "asc"},
        "limit": limit + 1,
    }

    if search is not None:
        if parameter.type != "string":
            raise InvalidInputError(
                f"Search is only supported for string parameter '{parameter.id}'"
            )

        query["filters"] = [
            {
                "member": parameter.member,
                "operator": "contains",
                "values": [search],
            }
        ]

    return query


def serialize_parameter_option(parameter: ResolvedParameter, value: Any) -> Any:
    if value is None:
        return None
    if parameter.type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            return value.lower() == "true"
    if parameter.type == "number":
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            return value
        if number.is_finite() and number == number.to_integral_value():
            return int(number)
        if number.is_finite():
            return float(number)

    return str(value)


def _collect_filter_bindings(
    item: Any,
    node_id: str,
    bindings: list[ParameterBinding],
) -> None:
    if not isinstance(item, dict):
        return

    if "parameter" in item:
        if "and" in item or "or" in item:
            raise InvalidInputError(
                f"Cube query node '{node_id}': parameter cannot be set on a filter group"
            )
        if "values" in item or "value" in item:
            raise InvalidInputError(
                f"Cube query node '{node_id}': a parameter filter cannot also set values"
            )

        parameter_id = item.get("parameter")
        member = item.get("member")
        operator = item.get("operator")

        if not all(
            isinstance(value, str) and value
            for value in (parameter_id, member, operator)
        ):
            raise InvalidInputError(
                f"Cube query node '{node_id}': parameter filters require string "
                "parameter, member, and operator values"
            )

        bindings.append(
            ParameterBinding(
                node_id=node_id,
                parameter_id=parameter_id,
                member=member,
                operator=operator,
            )
        )

    for group_key in ("and", "or"):
        if group_key not in item:
            continue

        group = item[group_key]

        if not isinstance(group, list):
            if _count_parameter_keys(group):
                raise InvalidInputError(
                    f"Cube query node '{node_id}': filter '{group_key}' must be a list"
                )

            continue

        for child in group:
            _collect_filter_bindings(child, node_id, bindings)


def _bind_filter_item(
    item: Any,
    resolved: dict[str, ResolvedParameter],
    values: dict[str, Any],
) -> None:
    if not isinstance(item, dict):
        return

    parameter_id = item.get("parameter")

    if isinstance(parameter_id, str):
        parameter = resolved.get(parameter_id)

        if parameter is None or parameter_id not in values:
            raise InvalidInputError(
                f"Cube filter could not resolve calculation parameter '{parameter_id}'"
            )

        operator = item.get("operator")

        if not isinstance(operator, str):
            raise InvalidInputError(
                f"Cube filter for parameter '{parameter_id}' requires an operator"
            )

        item.pop("parameter")

        item["values"] = _cube_filter_values(
            parameter,
            operator,
            values[parameter_id],
        )

    for group_key in ("and", "or"):
        group = item.get(group_key)

        for child in group if isinstance(group, list) else []:
            _bind_filter_item(child, resolved, values)


def _cube_filter_values(
    parameter: ResolvedParameter,
    operator: str,
    value: Any,
) -> list[str]:
    if operator in DATE_RANGE_OPERATORS:
        if not isinstance(value, list) or len(value) != 2:
            raise InvalidInputError(
                f"Calculation parameter '{parameter.id}' requires a two-value date range"
            )

        raw_values = value
    elif operator in MULTI_VALUE_OPERATORS:
        raw_values = value if isinstance(value, list) else [value]

        if not raw_values or len(raw_values) > MAX_CALCULATION_PARAMETER_VALUES:
            raise InvalidInputError(
                f"Calculation parameter '{parameter.id}' accepts between 1 and "
                f"{MAX_CALCULATION_PARAMETER_VALUES} values"
            )
    else:
        if isinstance(value, list):
            raise InvalidInputError(
                f"Calculation parameter '{parameter.id}' requires one value"
            )

        raw_values = [value]

    return [_serialize_typed_value(parameter, item) for item in raw_values]


def _serialize_typed_value(parameter: ResolvedParameter, value: Any) -> str:
    if parameter.type == "string":
        if not isinstance(value, str):
            raise InvalidInputError(
                f"Calculation parameter '{parameter.id}' requires string values"
            )
        if len(value) > 1000:
            raise InvalidInputError(
                f"Calculation parameter '{parameter.id}' values must be 1000 "
                "characters or shorter"
            )
        return value

    if parameter.type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise InvalidInputError(
                f"Calculation parameter '{parameter.id}' requires numeric values"
            )
        if isinstance(value, float) and not math.isfinite(value):
            raise InvalidInputError(
                f"Calculation parameter '{parameter.id}' requires finite values"
            )

        number = Decimal(str(value))

        if not number.is_finite() or abs(number) > Decimal("1e100"):
            raise InvalidInputError(
                f"Calculation parameter '{parameter.id}' is outside the supported "
                "numeric range"
            )

        return str(value)

    if parameter.type == "time":
        if not isinstance(value, str) or not _is_iso_date_or_datetime(value):
            raise InvalidInputError(
                f"Calculation parameter '{parameter.id}' requires ISO date or "
                "datetime values"
            )

        return value

    if parameter.type == "boolean":
        if not isinstance(value, bool):
            raise InvalidInputError(
                f"Calculation parameter '{parameter.id}' requires boolean values"
            )

        return "true" if value else "false"

    raise InvalidInputError(
        f"Calculation parameter '{parameter.id}' has unsupported type '{parameter.type}'"
    )


def _is_iso_date_or_datetime(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        pass

    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _dimension_index(meta: dict[str, Any]) -> dict[str, dict[str, Any]]:
    dimensions: dict[str, dict[str, Any]] = {}
    cubes = meta.get("cubes") if isinstance(meta, dict) else None

    for cube in cubes if isinstance(cubes, list) else []:
        if not isinstance(cube, dict):
            continue

        members = cube.get("dimensions")

        for member in members if isinstance(members, list) else []:
            if isinstance(member, dict) and isinstance(member.get("name"), str):
                dimensions[member["name"]] = member

    return dimensions


def _count_parameter_keys(value: Any) -> int:
    if isinstance(value, dict):
        return sum(
            (1 if key == "parameter" else 0) + _count_parameter_keys(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return sum(_count_parameter_keys(item) for item in value)

    return 0
