from typing import Any

from app.calculation_service import get_calculation
from app.calculations.constants import (
    MAX_CALCULATION_CUBE_QUERY_NODES,
    MAX_CALCULATION_ROW_LIMIT,
)
from app.calculations.executor import execute_definition
from app.calculations.graph import dependency_order, node_dependencies, validate_graph
from app.calculations.models import CalculationDefinition, CubeQueryNode
from app.calculations.parser import parse_calculation
from app.cube.query import normalize_cube_query_payload
from app.errors import ApplicationError, InvalidInputError
from app.semantic.catalog import organization_cube_names
from app.semantic.query import validate_cube_query_names


async def validate_calculation(
    calculation_id: int,
    *,
    content: str | None = None,
) -> dict[str, Any]:
    definition = await _load_definition(
        calculation_id,
        content=content,
    )
    allowed_names = await _validate_cube_nodes(definition)
    execution_order = dependency_order(definition, definition.output)
    reachable = set(execution_order)

    return {
        "valid": True,
        "output": definition.output,
        "execution_order": execution_order,
        "nodes": [
            {
                "id": node.id,
                "type": node.type,
                "dependencies": node_dependencies(node),
                "in_output": node.id in reachable,
            }
            for node in definition.nodes
        ],
        "available_cube_count": len(allowed_names),
    }


async def execute_calculation(
    calculation_id: int,
    *,
    content: str | None = None,
    target_node_id: str | None = None,
) -> dict[str, Any]:
    definition = await _load_definition(
        calculation_id,
        content=content,
    )
    target = target_node_id or definition.output
    execution_order = dependency_order(definition, target)
    allowed_names = await _validate_cube_nodes(
        definition,
        node_ids=set(execution_order),
    )

    return await execute_definition(
        definition,
        allowed_cube_names=allowed_names,
        target_node_id=target,
    )


async def _load_definition(
    calculation_id: int,
    *,
    content: str | None,
) -> CalculationDefinition:
    calculation = await get_calculation(calculation_id)
    source = content if content is not None else str(calculation["content"])
    definition = parse_calculation(source)
    validate_graph(definition)
    return definition


async def _validate_cube_nodes(
    definition: CalculationDefinition,
    *,
    node_ids: set[str] | None = None,
) -> set[str]:
    cube_nodes = [
        node
        for node in definition.nodes
        if isinstance(node, CubeQueryNode) and (node_ids is None or node.id in node_ids)
    ]

    if len(cube_nodes) > MAX_CALCULATION_CUBE_QUERY_NODES:
        raise InvalidInputError(
            "A calculation can run at most "
            f"{MAX_CALCULATION_CUBE_QUERY_NODES} Cube query nodes at once",
        )
    allowed_names = await organization_cube_names() if cube_nodes else set()

    for node in cube_nodes:
        try:
            _validate_cube_query_node(node, allowed_names)
        except ApplicationError as exc:
            raise type(exc)(f"Cube query node '{node.id}': {exc.message}") from exc

    return allowed_names


def _validate_cube_query_node(node: CubeQueryNode, allowed_names: set[str]) -> None:
    if "sql" in node.query:
        raise InvalidInputError("Raw SQL is not supported")

    query = normalize_cube_query_payload(node.query)

    if not isinstance(query, dict):
        raise InvalidInputError("Calculation Cube nodes require one query object")

    validate_cube_query_names(query, allowed_names)

    offset = query.get("offset", 0)

    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise InvalidInputError("query offset must be a non-negative integer")

    limit = query.get("limit")

    if node.result.kind == "table" and limit is not None:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_CALCULATION_ROW_LIMIT
        ):
            raise InvalidInputError(
                f"query limit must be between 1 and {MAX_CALCULATION_ROW_LIMIT}",
            )

    if node.result.kind == "scalar" and node.result.member not in _query_members(query):
        raise InvalidInputError(
            f"scalar result member '{node.result.member}' is not selected by the query",
        )


def _query_members(query: dict[str, Any]) -> set[str]:
    members = {
        value
        for key in ("measures", "dimensions")
        for value in query.get(key, [])
        if isinstance(value, str)
    }

    time_dimensions = query.get("timeDimensions")

    for item in time_dimensions if isinstance(time_dimensions, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("dimension"), str):
            continue
        dimension = item["dimension"]
        granularity = item.get("granularity")

        if isinstance(granularity, str) and granularity:
            members.add(f"{dimension}.{granularity}")
        else:
            members.add(dimension)

    return members
