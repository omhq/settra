from collections.abc import Iterable

from app.calculations.formula import validate_formula
from app.calculations.models import CalculationDefinition, FormulaNode
from app.errors import InvalidInputError


def validate_graph(definition: CalculationDefinition) -> None:
    node_by_id = {}
    duplicate_ids: set[str] = set()

    for node in definition.nodes:
        if node.id in node_by_id:
            duplicate_ids.add(node.id)

        node_by_id[node.id] = node

    if duplicate_ids:
        raise InvalidInputError(
            "Calculation contains duplicate node IDs: "
            + ", ".join(sorted(duplicate_ids)),
        )

    missing_outputs = {
        name: node_id
        for name, node_id in definition.outputs.items()
        if node_id not in node_by_id
    }

    if missing_outputs:
        references = ", ".join(
            f"{name} -> {node_id}" for name, node_id in missing_outputs.items()
        )

        raise InvalidInputError(
            f"Calculation outputs reference missing nodes: {references}",
        )

    for node in definition.nodes:
        if not isinstance(node, FormulaNode):
            continue

        missing = sorted(set(node.inputs.values()) - node_by_id.keys())

        if missing:
            raise InvalidInputError(
                f"Formula node '{node.id}' references missing nodes: {', '.join(missing)}",
            )

        table_inputs = sorted(
            reference
            for reference in node.inputs.values()
            if getattr(node_by_id[reference], "result", None) is not None
            and node_by_id[reference].result.kind == "table"
        )

        if table_inputs:
            raise InvalidInputError(
                f"Formula node '{node.id}' requires scalar inputs; table nodes: "
                + ", ".join(table_inputs),
            )

        try:
            validate_formula(node.expression, set(node.inputs))
        except InvalidInputError as exc:
            raise InvalidInputError(f"Formula node '{node.id}': {exc.message}") from exc

    dependency_order_for_targets(definition, definition.outputs.values())

    for node in definition.nodes:
        dependency_order(definition, node.id)


def node_dependencies(node) -> list[str]:
    if isinstance(node, FormulaNode):
        return list(dict.fromkeys(node.inputs.values()))

    return []


def dependency_order(
    definition: CalculationDefinition,
    target_node_id: str,
) -> list[str]:
    return dependency_order_for_targets(definition, [target_node_id])


def dependency_order_for_targets(
    definition: CalculationDefinition,
    target_node_ids: Iterable[str],
) -> list[str]:
    node_by_id = {node.id: node for node in definition.nodes}
    targets = list(dict.fromkeys(target_node_ids))

    missing_targets = [node_id for node_id in targets if node_id not in node_by_id]

    if missing_targets:
        raise InvalidInputError(
            "Calculation has no nodes named: " + ", ".join(missing_targets)
        )

    order: list[str] = []
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visited:
            return
        if node_id in visiting:
            cycle_start = visiting.index(node_id)
            cycle = visiting[cycle_start:] + [node_id]
            raise InvalidInputError(
                "Calculation contains a dependency cycle: " + " -> ".join(cycle),
            )

        visiting.append(node_id)

        for dependency_id in node_dependencies(node_by_id[node_id]):
            if dependency_id not in node_by_id:
                raise InvalidInputError(
                    f"Node '{node_id}' references missing node '{dependency_id}'",
                )
            visit(dependency_id)

        visiting.pop()
        visited.add(node_id)
        order.append(node_id)

    for target_node_id in targets:
        visit(target_node_id)

    return order
