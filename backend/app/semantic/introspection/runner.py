from typing import Any, Literal

import aiosqlite

from app.agent.llm import AgentLLM
from app.semantic.introspection.context import load_ai_context
from app.semantic.introspection.metrics import (
    empty_metric_result,
    run_metric_introspection,
)
from app.semantic.introspection.relationships import (
    empty_relationship_result,
    run_relationship_introspection,
)

AIIntrospectionFlow = Literal["relationships", "metrics"]


async def run_ai_semantic_introspection(
    db: aiosqlite.Connection,
    *,
    connection_ids: list[int],
    semantic_table_ids: list[int] | None = None,
    flows: list[AIIntrospectionFlow] | None = None,
    llm: AgentLLM,
) -> dict[str, Any]:
    selected_flows = _selected_flows(flows)
    context = await load_ai_context(db, connection_ids, semantic_table_ids or [])
    result = _empty_result()

    if not context["connections"]:
        result["warnings"] = ["No selected connections have semantic tables."]
        return result

    warnings: list[str] = []

    if "relationships" in selected_flows:
        relationship_result = await run_relationship_introspection(
            db,
            context=context,
            connection_ids=connection_ids,
            semantic_table_ids=semantic_table_ids or [],
            llm=llm,
        )

        warnings.extend(relationship_result.pop("warnings", []))
        result.update(relationship_result)

    if "metrics" in selected_flows:
        metric_result = await run_metric_introspection(
            db,
            context=context,
            llm=llm,
        )
        warnings.extend(metric_result.pop("warnings", []))
        result.update(metric_result)

    result["warnings"] = warnings

    return result


def _selected_flows(
    flows: list[AIIntrospectionFlow] | None,
) -> list[AIIntrospectionFlow]:
    requested = flows or ["relationships"]
    selected: list[AIIntrospectionFlow] = []

    for flow in ("relationships", "metrics"):
        if flow in requested:
            selected.append(flow)

    if not selected:
        raise ValueError("At least one AI introspection flow is required.")

    return selected


def _empty_result() -> dict[str, Any]:
    return {
        **empty_relationship_result(),
        **empty_metric_result(),
        "warnings": [],
    }
