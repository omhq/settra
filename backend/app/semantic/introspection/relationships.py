import logging
from typing import Any

import aiosqlite

from app.agent.llm import AgentLLM
from app.semantic.introspection.context import (
    columns_by_table,
    connection_for_id,
    label_from_identifier,
    load_ai_context,
    prune_blocked_relationship_suggestions,
)
from app.semantic.introspection.prompts import render_prompt_messages
from app.semantic.schemas import AIRelationshipCandidate, AISemanticSuggestions

logger = logging.getLogger(__name__)


async def run_relationship_introspection(
    db: aiosqlite.Connection,
    *,
    context: dict[str, Any],
    connection_ids: list[int],
    semantic_table_ids: list[int],
    llm: AgentLLM,
) -> dict[str, Any]:
    blocked_relationships_pruned = await prune_blocked_relationship_suggestions(
        db,
        context,
    )
    if blocked_relationships_pruned:
        context = await load_ai_context(db, connection_ids, semantic_table_ids)

    messages = _messages(context)

    logger.info(
        f"AI relationship introspection context "
        f"connections={len(context['connections'])} "
        f"tables={len(context['tables'])} "
        f"columns={len(context['columns'])} "
        f"sampled_tables={context['sampled_table_count']} "
        f"existing_relationships={len(context['existing_relationships'])} "
        f"chars={sum(len(message.get('content', '')) for message in messages)}"
    )

    suggestions = await llm.structured_model(
        messages,
        AISemanticSuggestions,
        operation="semantic_ai_relationship_introspection",
    )
    result = await _save_relationship_suggestions(db, context, suggestions)
    result["relationship_candidates_pruned"] = blocked_relationships_pruned

    return result


def empty_relationship_result(warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "relationship_candidates_returned": 0,
        "relationship_candidates_suggested": 0,
        "relationship_candidates_existing": 0,
        "relationship_candidates_with_notes": 0,
        "relationship_candidates_skipped": 0,
        "relationship_candidates_pruned": 0,
        "skipped": [],
        "warnings": warnings or [],
    }


def _messages(context: dict[str, Any]) -> list[dict[str, str]]:
    context_payload = {
        "connections": context["connections"],
        "tables": context["table_context"],
        "existing_relationships": context["existing_relationships"],
    }

    return render_prompt_messages(
        "relationships",
        context_payload,
        connector_plugins=_context_plugins(context),
    )


async def _save_relationship_suggestions(
    db: aiosqlite.Connection,
    context: dict[str, Any],
    suggestions: AISemanticSuggestions,
) -> dict[str, Any]:
    table_by_key = {
        (int(table["connection_id"]), table["table_name"]): table
        for table in context["tables"]
    }
    columns_by_table_id = columns_by_table(context["columns"])
    existing_relationship_keys = context["existing_relationship_keys"]
    created_relationship_candidates = 0
    existing_relationship_candidates = 0
    relationship_candidates_with_notes = 0
    skipped_relationship_candidates: list[dict[str, str]] = []

    for candidate in suggestions.relationship_candidates:
        resolved, validation_note = await _resolve_relationship_candidate(
            db,
            candidate,
            context,
            table_by_key,
            columns_by_table_id,
        )
        skip_reason = _relationship_candidate_skip_reason(resolved, context)

        if skip_reason:
            skipped_relationship_candidates.append(
                {
                    "from": _relationship_endpoint_label(
                        resolved["from_table"],
                        resolved["from_column"],
                    ),
                    "to": _relationship_endpoint_label(
                        resolved["to_table"],
                        resolved["to_column"],
                    ),
                    "reason": skip_reason,
                }
            )
            continue

        if _resolved_relationship_key(resolved) in existing_relationship_keys:
            existing_relationship_candidates += 1
            continue

        inserted = await _insert_relationship_suggestion(
            db,
            candidate,
            resolved,
            source="ai_candidate",
            validation_note=validation_note,
        )

        if inserted:
            created_relationship_candidates += inserted
            existing_relationship_keys.add(_resolved_relationship_key(resolved))
            if validation_note:
                relationship_candidates_with_notes += 1
        else:
            existing_relationship_candidates += 1

    await db.commit()

    logger.info(
        f"AI relationship introspection "
        f"returned={len(suggestions.relationship_candidates)} "
        f"saved={created_relationship_candidates} "
        f"existing={existing_relationship_candidates} "
        f"with_notes={relationship_candidates_with_notes} "
        f"skipped={len(skipped_relationship_candidates)}"
    )

    return {
        "relationship_candidates_returned": len(suggestions.relationship_candidates),
        "relationship_candidates_suggested": created_relationship_candidates,
        "relationship_candidates_existing": existing_relationship_candidates,
        "relationship_candidates_with_notes": relationship_candidates_with_notes,
        "relationship_candidates_skipped": len(skipped_relationship_candidates),
        "skipped": skipped_relationship_candidates,
        "warnings": suggestions.warnings,
    }


def _relationship_candidate_skip_reason(
    resolved: dict[str, Any],
    context: dict[str, Any],
) -> str | None:
    if int(resolved["from_table"]["id"]) == int(resolved["to_table"]["id"]):
        return "AI candidate links a table to itself."

    blocked_tables = context.get("relationship_blocked_tables") or {}

    for table_key in ("from_table", "to_table"):
        table = resolved[table_key]
        table_id = int(table["id"])
        reason = blocked_tables.get(table_id) or blocked_tables.get(str(table_id))

        if reason:
            return str(reason)

    return None


def _relationship_endpoint_label(
    table: dict[str, Any],
    column: dict[str, Any],
) -> str:
    return f"{table['schema_name']}.{table['table_name']}.{column['column_name']}"


async def _resolve_relationship_candidate(
    db: aiosqlite.Connection,
    relationship: AIRelationshipCandidate,
    context: dict[str, Any],
    table_by_key: dict[tuple[int, str], dict[str, Any]],
    columns_by_table_id: dict[int, dict[str, dict[str, Any]]],
) -> tuple[dict[str, Any], str | None]:
    validation_notes: list[str] = []

    from_table = table_by_key.get(
        (relationship.from_connection_id, relationship.from_table)
    )

    if not from_table:
        from_table = await _ensure_ai_table(
            db,
            context,
            table_by_key,
            relationship.from_connection_id,
            relationship.from_table,
            validation_notes,
            role="source",
        )

    to_table = table_by_key.get((relationship.to_connection_id, relationship.to_table))

    if not to_table:
        to_table = await _ensure_ai_table(
            db,
            context,
            table_by_key,
            relationship.to_connection_id,
            relationship.to_table,
            validation_notes,
            role="target",
        )

    from_column = columns_by_table_id.get(int(from_table["id"]), {}).get(
        relationship.from_column
    )

    if not from_column:
        from_column = await _ensure_ai_column(
            db,
            columns_by_table_id,
            from_table,
            relationship.from_column,
            validation_notes,
            role="source",
        )

    to_column = columns_by_table_id.get(int(to_table["id"]), {}).get(
        relationship.to_column
    )

    if not to_column:
        to_column = await _ensure_ai_column(
            db,
            columns_by_table_id,
            to_table,
            relationship.to_column,
            validation_notes,
            role="target",
        )

    if int(from_table["id"]) == int(to_table["id"]):
        validation_notes.append("AI candidate links a table to itself.")

    return {
        "from_table": from_table,
        "to_table": to_table,
        "from_column": from_column,
        "to_column": to_column,
    }, " ".join(validation_notes) or None


async def _ensure_ai_table(
    db: aiosqlite.Connection,
    context: dict[str, Any],
    table_by_key: dict[tuple[int, str], dict[str, Any]],
    connection_id: int,
    table_name: str,
    validation_notes: list[str],
    *,
    role: str,
) -> dict[str, Any]:
    connection = connection_for_id(context, connection_id)
    resolved_connection_id = int(connection["id"])
    schema_name = str(connection.get("slug") or f"connection_{resolved_connection_id}")

    if resolved_connection_id != connection_id:
        validation_notes.append(
            f"AI referenced unknown {role} connection id {connection_id}; "
            f"attached this candidate to connection {resolved_connection_id} for review."
        )

    async with db.execute(
        """
        SELECT *
        FROM semantic_tables
        WHERE connection_id = ?
          AND table_name = ?
        ORDER BY id
        LIMIT 1
        """,
        (resolved_connection_id, table_name),
    ) as cur:
        row = await cur.fetchone()

    if row:
        table = dict(row)
        table_by_key[(resolved_connection_id, table_name)] = table
        return table

    validation_notes.append(
        f"AI referenced unknown {role} table {table_name}; "
        f"a review-only semantic table placeholder was created."
    )

    cursor = await db.execute(
        """
        INSERT INTO semantic_tables (
            connection_id,
            source_name,
            schema_name,
            table_name,
            label,
            description,
            table_type,
            grain,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, 'dimension', ?, 'suggested')
        """,
        (
            resolved_connection_id,
            connection.get("plugin") or "ai",
            schema_name,
            table_name,
            label_from_identifier(table_name),
            "AI relationship candidate referenced this table before it was confirmed in the semantic layer.",
            f"Review-only placeholder for {table_name}",
        ),
    )

    table = {
        "id": cursor.lastrowid,
        "connection_id": resolved_connection_id,
        "source_name": connection.get("plugin") or "ai",
        "schema_name": schema_name,
        "table_name": table_name,
        "label": label_from_identifier(table_name),
        "description": "AI relationship candidate referenced this table before it was confirmed in the semantic layer.",
        "table_type": "dimension",
        "grain": f"Review-only placeholder for {table_name}",
        "primary_time_column": None,
        "metadata": {},
        "hidden": 0,
        "status": "suggested",
    }
    table_by_key[(resolved_connection_id, table_name)] = table
    return table


async def _ensure_ai_column(
    db: aiosqlite.Connection,
    columns_by_table_id: dict[int, dict[str, dict[str, Any]]],
    table: dict[str, Any],
    column_name: str,
    validation_notes: list[str],
    *,
    role: str,
) -> dict[str, Any]:
    table_id = int(table["id"])

    async with db.execute(
        """
        SELECT *
        FROM semantic_columns
        WHERE semantic_table_id = ?
          AND column_name = ?
        ORDER BY id
        LIMIT 1
        """,
        (table_id, column_name),
    ) as cur:
        row = await cur.fetchone()

    if row:
        column = dict(row)
        columns_by_table_id.setdefault(table_id, {})[column_name] = column
        return column

    validation_notes.append(
        f"AI referenced unknown {role} column "
        f"{table['table_name']}.{column_name}; "
        f"a review-only semantic column placeholder was created."
    )

    cursor = await db.execute(
        """
        INSERT INTO semantic_columns (
            semantic_table_id,
            column_name,
            label,
            description,
            semantic_type,
            status
        )
        VALUES (?, ?, ?, ?, 'text', 'suggested')
        """,
        (
            table_id,
            column_name,
            label_from_identifier(column_name),
            "AI relationship candidate referenced this column before it was confirmed in the semantic layer.",
        ),
    )

    column = {
        "id": cursor.lastrowid,
        "semantic_table_id": table_id,
        "column_name": column_name,
        "label": label_from_identifier(column_name),
        "description": "AI relationship candidate referenced this column before it was confirmed in the semantic layer.",
        "data_type": None,
        "semantic_type": "text",
        "expression": None,
        "unit": None,
        "is_dimension": 0,
        "is_measure": 0,
        "is_time": 0,
        "is_id": 0,
        "is_foreign_key": 0,
        "hidden": 0,
        "status": "suggested",
    }
    columns_by_table_id.setdefault(table_id, {})[column_name] = column

    return column


async def _insert_relationship_suggestion(
    db: aiosqlite.Connection,
    relationship: AIRelationshipCandidate,
    resolved: dict[str, Any],
    *,
    source: str,
    validation_note: str | None,
) -> int:
    from_table = resolved["from_table"]
    to_table = resolved["to_table"]
    from_column = resolved["from_column"]
    to_column = resolved["to_column"]
    cursor = await db.execute(
        """
        INSERT OR IGNORE INTO semantic_relationships (
            from_connection_id,
            to_connection_id,
            from_table_id,
            from_column_id,
            to_table_id,
            to_column_id,
            relationship_type,
            match_type,
            confidence,
            status,
            source,
            validation_status,
            validation_note,
            evidence,
            rationale
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'suggested', ?, ?, ?, ?, ?)
        """,
        (
            from_table["connection_id"],
            to_table["connection_id"],
            from_table["id"],
            from_column["id"],
            to_table["id"],
            to_column["id"],
            relationship.relationship_type,
            relationship.match_type,
            relationship.confidence,
            source,
            "needs_review" if validation_note else "valid",
            validation_note,
            relationship.evidence,
            relationship.rationale,
        ),
    )
    return max(cursor.rowcount, 0)


def _resolved_relationship_key(resolved: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        int(resolved["from_table"]["id"]),
        int(resolved["from_column"]["id"]),
        int(resolved["to_table"]["id"]),
        int(resolved["to_column"]["id"]),
    )


def _context_plugins(context: dict[str, Any]) -> list[str]:
    plugins: list[str] = []

    for connection in context["connections"]:
        plugin = str(connection.get("plugin") or "").strip()

        if plugin and plugin not in plugins:
            plugins.append(plugin)

    return plugins
