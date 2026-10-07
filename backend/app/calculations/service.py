from typing import Any

from app.auth import current_organization_id
from app.calculations.aggregate import validate_aggregate_query
from app.calculations.constants import (
    MAX_CALCULATION_PARAMETER_OPTIONS,
    MAX_CALCULATION_QUERY_NODES,
    MAX_CALCULATION_ROW_LIMIT,
)
from app.calculations.executor import execute_definition
from app.calculations.graph import (
    dependency_order,
    dependency_order_for_targets,
    node_dependencies,
    validate_graph,
)
from app.calculations.models import (
    AggregateQueryNode,
    CalculationDefinition,
    CubeQueryNode,
)
from app.calculations.parser import parse_calculation
from app.calculations.parameters import (
    ResolvedParameter,
    calculation_parameter_bindings,
    parameter_options_query,
    resolve_calculation_parameters,
    serialize_parameter_option,
    validate_parameter_values,
)
from app.collection_service import get_collection
from app.cube.query import execute_cube_query_payload, normalize_cube_query_payload
from app.errors import (
    ApplicationError,
    InvalidInputError,
    InvalidOperationError,
    ResourceNotFoundError,
)
from app.semantic.catalog import semantic_catalog_service
from app.semantic.query import validate_cube_query_names


async def validate_collection_graph(
    collection_id: int,
    *,
    content: str,
    target_node_id: str | None = None,
) -> dict[str, Any]:
    definition, collection = await _load_collection_definition(
        collection_id,
        content=content,
    )
    return await _validate_loaded_definition(
        definition,
        collection,
        target_node_id=target_node_id,
    )


async def _validate_loaded_definition(
    definition: CalculationDefinition,
    collection: dict[str, Any],
    *,
    target_node_id: str | None,
) -> dict[str, Any]:
    execution_order = (
        dependency_order(definition, target_node_id)
        if target_node_id is not None
        else dependency_order_for_targets(
            definition,
            definition.outputs.values(),
        )
    )
    reachable_node_ids = set(execution_order) if target_node_id is not None else None
    allowed_names = set(collection["cube_names"])
    _validate_query_node_count(definition, node_ids=reachable_node_ids)
    _validate_cube_nodes(
        definition,
        allowed_names=allowed_names,
        node_ids=reachable_node_ids,
    )
    aggregate_nodes = _aggregate_nodes(definition, node_ids=reachable_node_ids)
    if aggregate_nodes:
        await _validate_aggregate_nodes(
            aggregate_nodes,
            organization_id=current_organization_id(),
            allowed_connection_ids=set(collection["pipe_ids"]),
        )
    parameter_specs = await _resolve_parameter_specs(
        definition,
        allowed_names=allowed_names,
        node_ids=None,
        require_all_declarations=True,
    )
    output_orders = {
        name: dependency_order(definition, node_id)
        for name, node_id in definition.outputs.items()
    }

    return {
        "valid": True,
        "outputs": dict(definition.outputs),
        "execution_order": execution_order,
        "nodes": [
            _node_validation_projection(node, output_orders=output_orders)
            for node in definition.nodes
            if reachable_node_ids is None or node.id in reachable_node_ids
        ],
        "available_cube_count": len(allowed_names),
        "aggregate_query_count": len(aggregate_nodes),
        "parameters": [
            parameter_specs[parameter.id].descriptor()
            for parameter in definition.parameters
            if parameter.id in parameter_specs
        ],
    }


async def execute_collection_graph(
    collection_id: int,
    *,
    content: str,
    target_node_id: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    definition, collection = await _load_collection_definition(
        collection_id,
        content=content,
    )
    return await _execute_loaded_definition(
        definition,
        collection,
        target_node_id=target_node_id,
        parameters=parameters,
    )


async def _execute_loaded_definition(
    definition: CalculationDefinition,
    collection: dict[str, Any],
    *,
    target_node_id: str | None,
    parameters: dict[str, Any] | None,
) -> dict[str, Any]:
    allowed_names = set(collection["cube_names"])
    target_ids = (
        [target_node_id]
        if target_node_id is not None
        else list(definition.outputs.values())
    )
    reachable = set(dependency_order_for_targets(definition, target_ids))
    _validate_query_node_count(definition, node_ids=reachable)
    _validate_cube_nodes(definition, allowed_names=allowed_names, node_ids=reachable)
    parameter_specs = await _resolve_parameter_specs(
        definition,
        allowed_names=allowed_names,
        node_ids=None,
        require_all_declarations=True,
    )
    parameter_values = parameters or {}
    validate_parameter_values(definition, parameter_specs, parameter_values)
    aggregate_nodes = _aggregate_nodes(definition, node_ids=reachable)
    organization_id = None
    if aggregate_nodes:
        organization_id = current_organization_id()
        await _validate_aggregate_nodes(
            aggregate_nodes,
            organization_id=organization_id,
            allowed_connection_ids=set(collection["pipe_ids"]),
        )

    return await execute_definition(
        definition,
        allowed_cube_names=allowed_names,
        target_node_id=target_node_id,
        organization_id=organization_id,
        allowed_connection_ids=set(collection["pipe_ids"]),
        parameter_values=parameter_values,
        resolved_parameters=parameter_specs,
    )


async def collection_graph_parameter_options(
    collection_id: int,
    parameter_id: str,
    *,
    content: str,
    search: str | None = None,
) -> dict[str, Any]:
    definition, collection = await _load_collection_definition(
        collection_id,
        content=content,
    )
    return await _loaded_definition_parameter_options(
        definition,
        collection,
        parameter_id=parameter_id,
        search=search,
    )


async def _loaded_definition_parameter_options(
    definition: CalculationDefinition,
    collection: dict[str, Any],
    *,
    parameter_id: str,
    search: str | None,
) -> dict[str, Any]:
    declaration_ids = {parameter.id for parameter in definition.parameters}

    if parameter_id not in declaration_ids:
        raise ResourceNotFoundError(f"Calculation parameter '{parameter_id}' not found")

    allowed_names = set(collection["cube_names"])
    parameter_specs = await _resolve_parameter_specs(
        definition,
        allowed_names=allowed_names,
        node_ids=None,
        require_all_declarations=True,
    )
    parameter = parameter_specs[parameter_id]

    if parameter.type not in {"string", "boolean"}:
        raise InvalidInputError(
            f"Calculation parameter '{parameter_id}' uses a typed "
            f"{parameter.type} input instead of Cube-derived options"
        )

    normalized_search = search.strip() if search is not None else None
    query = parameter_options_query(
        parameter,
        search=normalized_search or None,
        limit=MAX_CALCULATION_PARAMETER_OPTIONS,
    )
    response = await execute_cube_query_payload(
        {"query": query},
        allowed_names=allowed_names,
    )
    rows = response.get("data")

    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise InvalidOperationError(
            "Cube returned an unsupported parameter option shape"
        )

    options: list[Any] = []
    seen: set[tuple[type, Any]] = set()

    for row in rows[:MAX_CALCULATION_PARAMETER_OPTIONS]:
        raw_value = row.get(parameter.member)

        if raw_value is None:
            continue

        value = serialize_parameter_option(parameter, raw_value)
        identity = (type(value), value)

        if identity in seen:
            continue

        seen.add(identity)
        options.append(value)

    return {
        "parameter": parameter.descriptor(),
        "options": options,
        "has_more": len(rows) > MAX_CALCULATION_PARAMETER_OPTIONS,
        "limit": MAX_CALCULATION_PARAMETER_OPTIONS,
    }


async def _load_collection_definition(
    collection_id: int,
    *,
    content: str,
) -> tuple[CalculationDefinition, dict[str, Any]]:
    definition = parse_calculation(content)
    validate_graph(definition)
    collection = await get_collection(collection_id)
    return definition, collection


def _node_validation_projection(
    node,
    *,
    output_orders: dict[str, list[str]],
) -> dict[str, Any]:
    return {
        "id": node.id,
        "type": node.type,
        "dependencies": node_dependencies(node),
        "used_by_outputs": [
            name for name, order in output_orders.items() if node.id in order
        ],
    }


def _validate_cube_nodes(
    definition: CalculationDefinition,
    *,
    allowed_names: set[str],
    node_ids: set[str] | None = None,
) -> None:
    cube_nodes = [
        node
        for node in definition.nodes
        if isinstance(node, CubeQueryNode) and (node_ids is None or node.id in node_ids)
    ]

    for node in cube_nodes:
        try:
            _validate_cube_query_node(node, allowed_names)
        except ApplicationError as exc:
            raise type(exc)(f"Cube query node '{node.id}': {exc.message}") from exc


async def _validate_aggregate_nodes(
    nodes: list[AggregateQueryNode],
    *,
    organization_id: int,
    allowed_connection_ids: set[int],
) -> None:
    for node in nodes:
        try:
            await validate_aggregate_query(
                node,
                organization_id=organization_id,
                allowed_connection_ids=allowed_connection_ids,
            )
        except ApplicationError as exc:
            raise type(exc)(f"Aggregate query node '{node.id}': {exc.message}") from exc


def _aggregate_nodes(
    definition: CalculationDefinition,
    *,
    node_ids: set[str] | None = None,
) -> list[AggregateQueryNode]:
    return [
        node
        for node in definition.nodes
        if isinstance(node, AggregateQueryNode)
        and (node_ids is None or node.id in node_ids)
    ]


async def _resolve_parameter_specs(
    definition: CalculationDefinition,
    *,
    allowed_names: set[str],
    node_ids: set[str] | None = None,
    require_all_declarations: bool = True,
) -> dict[str, ResolvedParameter]:
    bindings = calculation_parameter_bindings(definition, node_ids=node_ids)

    if not bindings:
        return resolve_calculation_parameters(
            definition,
            {"cubes": []},
            node_ids=node_ids,
            require_all_declarations=require_all_declarations,
        )

    meta = await semantic_catalog_service().compiled_meta(
        allowed_names=allowed_names,
    )

    return resolve_calculation_parameters(
        definition,
        meta,
        node_ids=node_ids,
        require_all_declarations=require_all_declarations,
    )


def _validate_query_node_count(
    definition: CalculationDefinition,
    *,
    node_ids: set[str] | None = None,
) -> None:
    query_nodes = [
        node
        for node in definition.nodes
        if isinstance(node, (CubeQueryNode, AggregateQueryNode))
        and (node_ids is None or node.id in node_ids)
    ]

    if len(query_nodes) > MAX_CALCULATION_QUERY_NODES:
        raise InvalidInputError(
            "A calculation can run at most "
            f"{MAX_CALCULATION_QUERY_NODES} query nodes at once",
        )


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
