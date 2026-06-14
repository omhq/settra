import logging

from typing import Any

import aiosqlite

from app.agent.connector_context import plugin_context_notes
from app.agent.llm import AgentLLM
from app.agent.metadata import get_schema_with_descriptions, get_semantic_metadata
from app.agent.schema_context import format_context
from app.agent.schemas import AnalyticsState
from app.agent.semantic_contract_prompt import format_semantic_contract_for_prompt
from app.agent.state import (
    format_history,
    schema_instruction,
    state_connections,
    state_connector_plugins,
)
from app.agent.table_selection import identify_relevant_tables
from app.common.config import DB_PATH
from app.semantic.loader import build_semantic_contract

logger = logging.getLogger(__name__)

__all__ = [
    "format_context",
    "format_history",
    "format_semantic_contract_for_prompt",
    "identify_relevant_tables",
    "load_context_state",
    "schema_instruction",
    "state_connections",
    "state_connector_plugins",
]


async def load_context_state(
    state: AnalyticsState,
    llm: AgentLLM,
) -> AnalyticsState:
    raw_schema: list[dict[str, Any]] = []
    semantic_meta: dict[str, Any] = {}
    semantic_contract: dict[str, Any] = {}
    relevant_tables: list[str] = []
    context_chunks: list[str] = []
    schema_errors: list[str] = []

    for connection in state_connections(state):
        schema = str(connection.get("schema") or "")
        plugin = str(connection.get("plugin") or "")
        name = str(connection.get("name") or schema or "Connection")

        if not schema or not plugin:
            schema_errors.append(f"{name}: missing schema or plugin")
            continue

        try:
            connection_schema = await get_schema_with_descriptions(schema)
        except Exception as exc:
            connection_schema = []
            logger.warning(
                f"Could not read schema metadata connection={name} "
                f"schema={schema} plugin={plugin} error={exc}",
                exc_info=True,
            )
            schema_errors.append(f"{name}: {exc}")

        if not connection_schema:
            schema_errors.append(
                f"{name}: no live tables exposed for schema {schema!r}"
            )

        semantic = await get_semantic_metadata(plugin)
        relevant = await identify_relevant_tables(
            state["question"],
            state.get("history", []),
            connection_schema,
            semantic,
            plugin,
            llm,
        )

        raw_schema.extend(
            {**table, "schema": schema, "connection_name": name}
            for table in connection_schema
        )
        semantic_meta.update(
            {f"{schema}.{table_name}": meta for table_name, meta in semantic.items()}
        )
        relevant_tables.extend(f"{schema}.{table_name}" for table_name in relevant)
        context_chunks.append(
            "\n".join(
                [
                    f"Connection: {name}",
                    f"Plugin: {plugin}",
                    *plugin_context_notes(plugin),
                    format_context(
                        relevant,
                        connection_schema,
                        semantic,
                        schema,
                        plugin=plugin,
                    ),
                ]
            )
        )

    selected_connection_ids = [
        int(connection["id"])
        for connection in state_connections(state)
        if connection.get("id") is not None
    ]

    if selected_connection_ids:
        async with aiosqlite.connect(DB_PATH) as db:
            semantic_contract = await build_semantic_contract(
                db,
                selected_connection_ids=selected_connection_ids,
                relevant_table_names=[
                    table.split(".", 1)[1] if "." in table else table
                    for table in relevant_tables
                ],
            )

    semantic_contract_text = format_semantic_contract_for_prompt(semantic_contract)
    context_text = "\n\n".join(context_chunks)

    logger.info(
        f"Chat context loaded connections={len(state_connections(state))} "
        f"relevant_tables={len(relevant_tables)} context_chars={len(context_text)} "
        f"semantic_contract_chars={len(semantic_contract_text)}"
    )

    return {
        "raw_schema": raw_schema,
        "semantic_meta": semantic_meta,
        "relevant_tables": relevant_tables,
        "context": context_text,
        "semantic_contract": semantic_contract,
        "semantic_contract_text": semantic_contract_text,
        "schema_error": "\n".join(schema_errors),
    }
