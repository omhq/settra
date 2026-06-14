import re
import logging

from typing import Any

from app.agent.connector_context import (
    google_sheets_table_score_adjustment,
    is_dynamic_google_sheets_table,
)
from app.agent.llm import AgentLLM, AgentLLMError
from app.agent.prompts import render_prompt_messages
from app.agent.schema_context import all_table_names, table_summary
from app.agent.schemas import TableSelection
from app.agent.state import format_history

logger = logging.getLogger(__name__)

MAX_TABLE_SELECTOR_CANDIDATES = 60


async def identify_relevant_tables(
    question: str,
    history: list[dict[str, Any]],
    raw_schema: list[dict[str, Any]],
    semantic: dict[str, Any],
    plugin: str,
    llm: AgentLLM,
) -> list[str]:
    table_names = all_table_names(raw_schema, semantic)

    if not table_names:
        return []

    if _is_catalog_question(question, history):
        return table_names[:20]

    fallback = _keyword_table_match(question, raw_schema, semantic, plugin)

    if not llm.configured:
        return fallback

    selector_table_names = _table_selector_table_names(
        question,
        raw_schema,
        semantic,
        table_names,
        plugin,
    )

    if len(selector_table_names) < len(table_names):
        logger.info(
            f"Table selector context reduced tables={len(table_names)} "
            f"candidates={len(selector_table_names)}"
        )

    table_summaries = "\n".join(
        f"- {name}: {table_summary(name, raw_schema, semantic, plugin)}"
        for name in selector_table_names
    )

    try:
        messages = await render_prompt_messages(
            "table_selector",
            {
                "question": question,
                "history": format_history(history),
                "table_summaries": table_summaries,
                "tables_json": selector_table_names,
                "connector_plugins": [plugin],
            },
        )
        payload = await llm.structured_model(
            messages,
            TableSelection,
            operation="table_selector",
        )
    except AgentLLMError as exc:
        logger.warning(
            f"Table selection LLM failed; using keyword fallback "
            f"operation={exc.operation} error={exc.original_summary} "
            f"user_message={exc.user_message}"
        )
        return fallback
    except Exception as exc:
        logger.warning(
            f"Table selection failed; using keyword fallback error={exc}",
            exc_info=True,
        )
        return fallback

    allowed = set(selector_table_names)
    relevant = [table for table in payload.tables if table in allowed]

    return _with_required_companion_tables(
        relevant[:8] or fallback,
        table_names,
        raw_schema,
        semantic,
    )


def _keyword_table_match(
    question: str,
    raw_schema: list[dict[str, Any]],
    semantic: dict[str, Any],
    plugin: str,
) -> list[str]:
    scored = _scored_table_names(
        question,
        raw_schema,
        semantic,
        all_table_names(raw_schema, semantic),
        plugin,
    )
    matches = [table for score, table in scored if score > 0]

    return _with_required_companion_tables(
        (matches or [table for _, table in scored])[:5],
        all_table_names(raw_schema, semantic),
        raw_schema,
        semantic,
    )


def _with_required_companion_tables(
    relevant: list[str],
    table_names: list[str],
    raw_schema: list[dict[str, Any]],
    semantic: dict[str, Any],
) -> list[str]:
    if not relevant:
        return relevant

    has_google_sheets_dynamic_table = any(
        is_dynamic_google_sheets_table(table, raw_schema, semantic)
        for table in relevant
    )

    if not has_google_sheets_dynamic_table:
        return relevant

    expanded = list(relevant)

    for companion in ("googlesheets_cell", "googlesheets_sheet"):
        if companion in table_names and companion not in expanded:
            expanded.append(companion)

    return expanded[:10]


def _table_selector_table_names(
    question: str,
    raw_schema: list[dict[str, Any]],
    semantic: dict[str, Any],
    table_names: list[str],
    plugin: str,
) -> list[str]:
    if len(table_names) <= MAX_TABLE_SELECTOR_CANDIDATES:
        return table_names

    scored = _scored_table_names(question, raw_schema, semantic, table_names, plugin)

    return [table for _, table in scored[:MAX_TABLE_SELECTOR_CANDIDATES]]


def _scored_table_names(
    question: str,
    raw_schema: list[dict[str, Any]],
    semantic: dict[str, Any],
    table_names: list[str],
    plugin: str,
) -> list[tuple[int, str]]:
    words = set(re.findall(r"[a-z0-9]+", question.lower()))
    scored: list[tuple[int, str]] = []

    for table_name in table_names:
        summary = (
            f"{table_name} {table_summary(table_name, raw_schema, semantic, plugin)}"
        )
        summary_words = set(re.findall(r"[a-z0-9]+", summary.lower()))
        score = len(words & summary_words)
        score += google_sheets_table_score_adjustment(
            table_name,
            raw_schema,
            semantic,
            words,
        )

        scored.append((score, table_name))

    scored.sort(key=lambda item: (-item[0], item[1]))

    return scored


def _is_catalog_question(
    question: str,
    history: list[dict[str, Any]],
) -> bool:
    catalog_words = {
        "table",
        "tables",
        "schema",
        "schemas",
        "column",
        "columns",
        "fields",
        "available",
        "metadata",
        "catalog",
    }

    current_words = set(re.findall(r"[a-z0-9]+", question.lower()))

    if current_words & catalog_words:
        return True

    pronoun_followup = current_words & {"they", "them", "those", "these"}

    if not pronoun_followup:
        return False

    recent_user_text = " ".join(
        str(message.get("content", ""))
        for message in history[-4:]
        if message.get("role") == "user"
    ).lower()
    recent_user_words = set(re.findall(r"[a-z0-9]+", recent_user_text))

    return bool(recent_user_words & catalog_words)
