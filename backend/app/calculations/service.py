from dataclasses import dataclass
from typing import Any

from app.auth import current_organization_id
from app.calculation_service import get_calculation, get_calculation_in_collection
from app.calculations.aggregate import validate_aggregate_query
from app.calculations.constants import (
    MAX_CALCULATION_PARAMETER_OPTIONS,
    MAX_CALCULATION_QUERY_NODES,
    MAX_CALCULATION_REFERENCE_DEPTH,
    MAX_CALCULATION_ROW_LIMIT,
)
from app.calculations.executor import (
    CalculationResult,
    calculation_result_from_payload,
    execute_definition,
)
from app.calculations.graph import (
    dependency_order,
    dependency_order_for_targets,
    node_dependencies,
    validate_graph,
)
from app.calculations.models import (
    AggregateQueryNode,
    CalculationDefinition,
    CalculationOutputNode,
    CubeQueryNode,
    FormulaNode,
    ValueNode,
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


async def validate_calculation(
    calculation_id: int,
    *,
    content: str | None = None,
) -> dict[str, Any]:
    document, collection = await _load_definition(
        calculation_id,
        content=content,
    )
    definition = document.definition
    allowed_names = set(collection["cube_names"])
    resolver = _CalculationReferenceResolver(
        collection_id=int(collection["id"]),
        allowed_names=allowed_names,
    )
    parameter_specs = await _validate_definition_tree(
        document,
        collection=collection,
        resolver=resolver,
        node_ids=None,
        path=(document.slug,),
        require_all_declarations=True,
    )
    aggregate_nodes = _aggregate_nodes(definition)
    output_orders = {
        name: dependency_order(definition, node_id)
        for name, node_id in definition.outputs.items()
    }
    execution_order = dependency_order_for_targets(
        definition,
        definition.outputs.values(),
    )

    return {
        "valid": True,
        "outputs": dict(definition.outputs),
        "execution_order": execution_order,
        "nodes": [
            _node_validation_projection(node, output_orders=output_orders)
            for node in definition.nodes
        ],
        "available_cube_count": len(allowed_names),
        "aggregate_query_count": len(aggregate_nodes),
        "parameters": [
            parameter_specs[parameter.id].descriptor()
            for parameter in definition.parameters
        ],
    }


async def execute_calculation(
    calculation_id: int,
    *,
    content: str | None = None,
    target_node_id: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document, collection = await _load_definition(
        calculation_id,
        content=content,
    )
    resolver = _CalculationReferenceResolver(
        collection_id=int(collection["id"]),
        allowed_names=set(collection["cube_names"]),
    )

    return await _execute_definition_tree(
        document,
        collection=collection,
        resolver=resolver,
        target_node_id=target_node_id,
        parameter_values=parameters or {},
        path=(document.slug,),
    )


async def calculation_parameter_options(
    calculation_id: int,
    parameter_id: str,
    *,
    content: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    document, collection = await _load_definition(
        calculation_id,
        content=content,
    )
    definition = document.definition
    declaration_ids = {parameter.id for parameter in definition.parameters}

    if parameter_id not in declaration_ids:
        raise ResourceNotFoundError(f"Calculation parameter '{parameter_id}' not found")

    allowed_names = set(collection["cube_names"])
    resolver = _CalculationReferenceResolver(
        collection_id=int(collection["id"]),
        allowed_names=allowed_names,
    )
    parameter_specs = await resolver.resolve_parameters(
        document,
        node_ids=None,
        path=(document.slug,),
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


async def _load_definition(
    calculation_id: int,
    *,
    content: str | None,
) -> tuple["_CalculationDocument", dict[str, Any]]:
    calculation = await get_calculation(calculation_id)
    collection_id = calculation.get("collection_id")

    if collection_id is None:
        raise InvalidOperationError(
            "Assign this calculation to an App before validating or running it"
        )

    source = content if content is not None else str(calculation["content"])
    definition = parse_calculation(source)

    validate_graph(definition)

    collection = await get_collection(int(collection_id))

    return (
        _CalculationDocument(calculation=calculation, definition=definition),
        collection,
    )


@dataclass(frozen=True)
class _CalculationDocument:
    calculation: dict[str, Any]
    definition: CalculationDefinition

    @property
    def slug(self) -> str:
        slug = self.calculation.get("slug")

        if isinstance(slug, str) and slug:
            return slug

        return f"calculation_{self.calculation.get('id', 'draft')}"


class _CalculationReferenceResolver:
    def __init__(self, *, collection_id: int, allowed_names: set[str]) -> None:
        self.collection_id = collection_id
        self.allowed_names = allowed_names
        self._documents: dict[str, _CalculationDocument] = {}

    async def reference(
        self,
        node: CalculationOutputNode,
        *,
        path: tuple[str, ...],
    ) -> tuple[_CalculationDocument, str]:
        if node.calculation in path:
            cycle_start = path.index(node.calculation)
            cycle = (*path[cycle_start:], node.calculation)
            raise InvalidInputError(
                "App calculations contain a dependency cycle: " + " -> ".join(cycle)
            )
        if len(path) >= MAX_CALCULATION_REFERENCE_DEPTH:
            raise InvalidInputError(
                "App calculation dependencies may be at most "
                f"{MAX_CALCULATION_REFERENCE_DEPTH} calculations deep"
            )

        document = self._documents.get(node.calculation)

        if document is None:
            calculation = await get_calculation_in_collection(
                self.collection_id,
                node.calculation,
            )
            definition = parse_calculation(str(calculation["content"]))

            validate_graph(definition)

            document = _CalculationDocument(
                calculation=calculation,
                definition=definition,
            )
            self._documents[node.calculation] = document

        target_node_id = document.definition.outputs.get(node.output)

        if target_node_id is None:
            raise InvalidInputError(
                f"Calculation output node '{node.id}' references missing output "
                f"'{node.output}' on calculation '{node.calculation}'"
            )

        actual_kind = _node_result_kind(document.definition, target_node_id)

        if actual_kind != node.result.kind:
            raise InvalidInputError(
                f"Calculation output node '{node.id}' declares a {node.result.kind} "
                f"result but '{node.calculation}.{node.output}' is {actual_kind}"
            )

        return document, target_node_id

    async def resolve_parameters(
        self,
        document: _CalculationDocument,
        *,
        node_ids: set[str] | None,
        path: tuple[str, ...],
        require_all_declarations: bool,
    ) -> dict[str, ResolvedParameter]:
        definition = document.definition
        resolved = await _resolve_parameter_specs(
            definition,
            allowed_names=self.allowed_names,
            node_ids=node_ids,
            require_all_declarations=False,
        )
        declarations = {parameter.id: parameter for parameter in definition.parameters}

        for node in _calculation_output_nodes(definition, node_ids=node_ids):
            referenced, target_node_id = await self.reference(node, path=path)
            child_node_ids = set(
                dependency_order(referenced.definition, target_node_id)
            )
            child_specs = await self.resolve_parameters(
                referenced,
                node_ids=child_node_ids,
                path=(*path, referenced.slug),
                require_all_declarations=False,
            )
            missing_arguments = sorted(child_specs.keys() - node.arguments.keys())
            unknown_arguments = sorted(node.arguments.keys() - child_specs.keys())

            if missing_arguments:
                raise InvalidInputError(
                    f"Calculation output node '{node.id}' must provide arguments for: "
                    + ", ".join(missing_arguments)
                )
            if unknown_arguments:
                raise InvalidInputError(
                    f"Calculation output node '{node.id}' provides unknown arguments: "
                    + ", ".join(unknown_arguments)
                )

            for child_parameter_id, child_spec in child_specs.items():
                parent_parameter_id = node.arguments[child_parameter_id]
                declaration = declarations.get(parent_parameter_id)

                if declaration is None:
                    raise InvalidInputError(
                        f"Calculation output node '{node.id}' maps "
                        f"'{child_parameter_id}' to undeclared parameter "
                        f"'{parent_parameter_id}'"
                    )
                if declaration.member != child_spec.member:
                    raise InvalidInputError(
                        f"Calculation output node '{node.id}' maps parameter "
                        f"'{parent_parameter_id}' for '{declaration.member}' to "
                        f"'{child_parameter_id}' for '{child_spec.member}'"
                    )

                forwarded = ResolvedParameter(
                    id=parent_parameter_id,
                    member=child_spec.member,
                    title=child_spec.title,
                    type=child_spec.type,
                    operators=child_spec.operators,
                )
                resolved[parent_parameter_id] = _merge_parameter_spec(
                    resolved.get(parent_parameter_id),
                    forwarded,
                )

        if require_all_declarations:
            unused = sorted(declarations.keys() - resolved.keys())

            if unused:
                raise InvalidInputError(
                    "Calculation parameters are not bound to Cube filters or "
                    "calculation arguments: " + ", ".join(unused)
                )

        return resolved


async def _validate_definition_tree(
    document: _CalculationDocument,
    *,
    collection: dict[str, Any],
    resolver: _CalculationReferenceResolver,
    node_ids: set[str] | None,
    path: tuple[str, ...],
    require_all_declarations: bool,
) -> dict[str, ResolvedParameter]:
    definition = document.definition
    _validate_query_node_count(definition, node_ids=node_ids)
    _validate_cube_nodes(
        definition,
        allowed_names=resolver.allowed_names,
        node_ids=node_ids,
    )
    aggregate_nodes = _aggregate_nodes(definition, node_ids=node_ids)

    if aggregate_nodes:
        await _validate_aggregate_nodes(
            aggregate_nodes,
            organization_id=current_organization_id(),
            allowed_connection_ids=set(collection["pipe_ids"]),
        )

    parameter_specs = await resolver.resolve_parameters(
        document,
        node_ids=node_ids,
        path=path,
        require_all_declarations=require_all_declarations,
    )

    for node in _calculation_output_nodes(definition, node_ids=node_ids):
        referenced, target_node_id = await resolver.reference(node, path=path)

        await _validate_definition_tree(
            referenced,
            collection=collection,
            resolver=resolver,
            node_ids=set(dependency_order(referenced.definition, target_node_id)),
            path=(*path, referenced.slug),
            require_all_declarations=False,
        )

    return parameter_specs


async def _execute_definition_tree(
    document: _CalculationDocument,
    *,
    collection: dict[str, Any],
    resolver: _CalculationReferenceResolver,
    target_node_id: str | None,
    parameter_values: dict[str, Any],
    path: tuple[str, ...],
) -> dict[str, Any]:
    definition = document.definition
    target_ids = (
        [target_node_id]
        if target_node_id is not None
        else list(definition.outputs.values())
    )
    reachable = set(dependency_order_for_targets(definition, target_ids))

    _validate_query_node_count(definition, node_ids=reachable)
    _validate_cube_nodes(
        definition,
        allowed_names=resolver.allowed_names,
        node_ids=reachable,
    )

    parameter_specs = await resolver.resolve_parameters(
        document,
        node_ids=reachable,
        path=path,
        require_all_declarations=False,
    )

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

    async def execute_calculation_output(
        node: CalculationOutputNode,
    ) -> CalculationResult:
        referenced, referenced_target = await resolver.reference(node, path=path)
        child_values = {
            child_parameter_id: parameter_values[parent_parameter_id]
            for child_parameter_id, parent_parameter_id in node.arguments.items()
            if parent_parameter_id in parameter_values
        }
        response = await _execute_definition_tree(
            referenced,
            collection=collection,
            resolver=resolver,
            target_node_id=referenced_target,
            parameter_values=child_values,
            path=(*path, referenced.slug),
        )

        return calculation_result_from_payload(response["result"])

    return await execute_definition(
        definition,
        allowed_cube_names=resolver.allowed_names,
        target_node_id=target_node_id,
        organization_id=organization_id,
        allowed_connection_ids=set(collection["pipe_ids"]),
        parameter_values=parameter_values,
        resolved_parameters=parameter_specs,
        calculation_output_executor=execute_calculation_output,
    )


def _calculation_output_nodes(
    definition: CalculationDefinition,
    *,
    node_ids: set[str] | None,
) -> list[CalculationOutputNode]:
    return [
        node
        for node in definition.nodes
        if isinstance(node, CalculationOutputNode)
        and (node_ids is None or node.id in node_ids)
    ]


def _node_result_kind(
    definition: CalculationDefinition,
    node_id: str,
) -> str:
    node = next(node for node in definition.nodes if node.id == node_id)

    if isinstance(node, (ValueNode, FormulaNode)):
        return "scalar"

    return node.result.kind


def _merge_parameter_spec(
    current: ResolvedParameter | None,
    forwarded: ResolvedParameter,
) -> ResolvedParameter:
    if current is None:
        return forwarded

    if current.member != forwarded.member or current.type != forwarded.type:
        raise InvalidInputError(
            f"Calculation parameter '{forwarded.id}' has incompatible bindings"
        )

    current_cardinality = current.descriptor()["cardinality"]
    forwarded_cardinality = forwarded.descriptor()["cardinality"]

    if current_cardinality != forwarded_cardinality:
        raise InvalidInputError(
            f"Calculation parameter '{forwarded.id}' has incompatible input shapes"
        )

    return ResolvedParameter(
        id=current.id,
        member=current.member,
        title=current.title,
        type=current.type,
        operators=tuple(dict.fromkeys((*current.operators, *forwarded.operators))),
    )


def _node_validation_projection(
    node,
    *,
    output_orders: dict[str, list[str]],
) -> dict[str, Any]:
    projection = {
        "id": node.id,
        "type": node.type,
        "dependencies": node_dependencies(node),
        "used_by_outputs": [
            name for name, order in output_orders.items() if node.id in order
        ],
    }

    if isinstance(node, CalculationOutputNode):
        projection.update(
            {
                "calculation": node.calculation,
                "output": node.output,
                "arguments": dict(node.arguments),
                "result_kind": node.result.kind,
            }
        )

    return projection


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
