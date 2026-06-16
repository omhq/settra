import json
import logging
from typing import Any

import aiosqlite

from app.agent.llm import AgentLLM
from app.semantic.introspection.context import label_from_identifier
from app.semantic.introspection.prompts import render_prompt_messages
from app.pruning import metric_introspection_payload
from app.semantic.schemas import AIMetricCandidate, AIMetricSuggestions

logger = logging.getLogger(__name__)


async def run_metric_introspection(
    db: aiosqlite.Connection,
    *,
    context: dict[str, Any],
    llm: AgentLLM,
) -> dict[str, Any]:
    messages = _messages(context)
    logger.info(
        f"AI metric introspection context "
        f"connections={len(context['connections'])} "
        f"tables={len(context['tables'])} "
        f"columns={len(context['columns'])} "
        f"sampled_tables={context['sampled_table_count']} "
        f"existing_metrics={len(context['existing_metrics'])} "
        f"chars={sum(len(message.get('content', '')) for message in messages)}"
    )

    suggestions = await llm.structured_model(
        messages,
        AIMetricSuggestions,
        operation="semantic_ai_metric_introspection",
    )

    return await _save_metric_suggestions(db, context, suggestions)


def empty_metric_result(warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "metric_candidates_returned": 0,
        "metric_candidates_suggested": 0,
        "metric_candidates_existing": 0,
        "metric_candidates_skipped": 0,
        "metric_skipped": [],
        "warnings": warnings or [],
    }


def _messages(context: dict[str, Any]) -> list[dict[str, str]]:
    context_payload = metric_introspection_payload(context)
    return render_prompt_messages(
        "metrics",
        context_payload,
        connector_plugins=_context_plugins(context),
    )


async def _save_metric_suggestions(
    db: aiosqlite.Connection,
    context: dict[str, Any],
    suggestions: AIMetricSuggestions,
) -> dict[str, Any]:
    table_by_key = {
        (int(table["connection_id"]), table["table_name"]): table
        for table in context["tables"]
    }
    existing_metric_keys = context["existing_metric_keys"]
    blocked_tables = context.get("metric_blocked_tables") or {}

    created_metric_candidates = 0
    existing_metric_candidates = 0
    skipped_metric_candidates: list[dict[str, str]] = []

    for candidate in suggestions.metric_candidates:
        table = table_by_key.get((candidate.connection_id, candidate.table))
        metric_name = _metric_name(candidate.name)

        if not metric_name:
            skipped_metric_candidates.append(
                {
                    "metric": candidate.name,
                    "reason": "Metric name is empty after normalization.",
                }
            )
            continue

        if not table:
            skipped_metric_candidates.append(
                {
                    "metric": metric_name,
                    "reason": (
                        f"Unknown table for connection {candidate.connection_id}: "
                        f"{candidate.table}"
                    ),
                }
            )
            continue

        table_id = int(table["id"])
        block_reason = blocked_tables.get(table_id) or blocked_tables.get(str(table_id))
        if block_reason:
            skipped_metric_candidates.append(
                {
                    "metric": metric_name,
                    "reason": str(block_reason),
                }
            )
            continue

        metric_key = (int(table["connection_id"]), metric_name.lower())
        if metric_key in existing_metric_keys:
            existing_metric_candidates += 1
            continue

        inserted = await _insert_metric_suggestion(
            db,
            candidate,
            table,
            metric_name=metric_name,
        )
        if inserted:
            created_metric_candidates += inserted
            existing_metric_keys.add(metric_key)
        else:
            existing_metric_candidates += 1

    await db.commit()

    logger.info(
        f"AI metric introspection "
        f"returned={len(suggestions.metric_candidates)} "
        f"saved={created_metric_candidates} "
        f"existing={existing_metric_candidates} "
        f"skipped={len(skipped_metric_candidates)}"
    )

    return {
        "metric_candidates_returned": len(suggestions.metric_candidates),
        "metric_candidates_suggested": created_metric_candidates,
        "metric_candidates_existing": existing_metric_candidates,
        "metric_candidates_skipped": len(skipped_metric_candidates),
        "metric_skipped": skipped_metric_candidates,
        "warnings": suggestions.warnings,
    }


async def _insert_metric_suggestion(
    db: aiosqlite.Connection,
    candidate: AIMetricCandidate,
    table: dict[str, Any],
    *,
    metric_name: str,
) -> int:
    cursor = await db.execute(
        """
        INSERT OR IGNORE INTO semantic_metrics (
            connection_id,
            semantic_table_id,
            name,
            label,
            expression,
            filters_json,
            time_column,
            unit,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'suggested')
        """,
        (
            table["connection_id"],
            table["id"],
            metric_name,
            _optional_text(candidate.label) or label_from_identifier(metric_name),
            candidate.expression.strip(),
            json.dumps(candidate.filters),
            _optional_text(candidate.time_column),
            _optional_text(candidate.unit),
        ),
    )
    return max(cursor.rowcount, 0)


def _metric_name(value: str) -> str:
    tokens = [
        token
        for token in "".join(
            char.lower() if char.isalnum() else " " for char in value
        ).split()
        if token
    ]
    return "_".join(tokens)


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    stripped = value.strip()
    return stripped or None


def _context_plugins(context: dict[str, Any]) -> list[str]:
    plugins: list[str] = []

    for connection in context["connections"]:
        plugin = str(connection.get("plugin") or "").strip()
        if plugin and plugin not in plugins:
            plugins.append(plugin)

    return plugins
