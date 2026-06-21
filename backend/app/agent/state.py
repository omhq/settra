import json

from typing import Any

from app.pruning import prune_query_result_rows_for_prompt
from app.agent.schemas import AnalyticsState
from app.agent.consts import HISTORY_MESSAGE_LIMIT, HISTORY_RESULT_CONTEXT_LIMIT


def state_connections(state: AnalyticsState) -> list[dict[str, Any]]:
    connections = state.get("connections") or []
    if connections:
        return connections

    return [
        {
            "id": state.get("connection_id"),
            "name": state.get("connection_name") or "Connection",
            "schema": state.get("schema"),
            "plugin": state.get("plugin"),
        }
    ]


def state_connector_plugins(state: AnalyticsState) -> list[str]:
    plugins: list[str] = []

    for connection in state_connections(state):
        plugin = str(connection.get("plugin") or "").strip()
        if plugin and plugin not in plugins:
            plugins.append(plugin)

    return plugins


def schema_instruction(state: AnalyticsState) -> str:
    schemas = [
        str(connection.get("schema"))
        for connection in state_connections(state)
        if connection.get("schema")
    ]

    if len(schemas) <= 1:
        schema = schemas[0] if schemas else state.get("schema", "")
        return f"Always use schema-qualified tables from schema {schema!r}. "

    return (
        "Always use schema-qualified tables. Available schemas are "
        f"{', '.join(repr(schema) for schema in schemas)}. "
        "Use the schema that matches the relevant connection in the context. "
    )


def format_history(messages: list[dict[str, Any]]) -> str:
    if not messages:
        return "No prior messages."

    chunks = []

    recent_messages = messages[-HISTORY_MESSAGE_LIMIT:]
    result_context_indexes = _result_context_indexes(recent_messages)

    for index, message in enumerate(recent_messages):
        chunks.append(f"{message.get('role', 'user')}: {message.get('content', '')}")

        if index not in result_context_indexes:
            continue

        payload_summary = _history_payload_summary(message.get("payload"))

        if payload_summary:
            chunks.append(payload_summary)

    return "\n".join(chunks)


def _result_context_indexes(messages: list[dict[str, Any]]) -> set[int]:
    indexes = [
        index
        for index, message in enumerate(messages)
        if message.get("role") == "assistant"
        and _is_result_payload(message.get("payload"))
    ]

    return set(indexes[-HISTORY_RESULT_CONTEXT_LIMIT:])


def _history_payload_summary(raw_payload: Any) -> str:
    payload = _parse_payload(raw_payload)

    if not isinstance(payload, dict) or payload.get("type") != "result":
        return ""

    parts = ["assistant_result_context:"]
    workflow = str(payload.get("workflow") or "").strip()
    query_plan = str(payload.get("query_plan") or "").strip()
    sql = str(payload.get("sql") or "").strip()
    results = payload.get("results") if isinstance(payload.get("results"), dict) else {}
    row_count = results.get("row_count", 0)
    truncated = bool(results.get("truncated"))
    columns = results.get("columns") or []
    rows = prune_query_result_rows_for_prompt(results)

    if workflow:
        parts.append(f"- workflow: {workflow}")
    if query_plan:
        parts.append(f"- query_plan: {query_plan}")
    if sql:
        parts.append(f"- sql: {sql}")

    parts.append(f"- result_rows: {row_count}")
    parts.append(f"- result_truncated: {truncated}")

    if columns:
        parts.append(f"- result_columns: {', '.join(map(str, columns[:24]))}")
    if rows:
        parts.append("- result_sample_rows: " + json.dumps(rows, default=str))

    return "\n".join(parts)


def _parse_payload(raw_payload: Any) -> Any:
    if isinstance(raw_payload, dict):
        return raw_payload

    if not isinstance(raw_payload, str) or not raw_payload.strip():
        return None

    try:
        return json.loads(raw_payload)
    except json.JSONDecodeError:
        return None


def _is_result_payload(raw_payload: Any) -> bool:
    payload = _parse_payload(raw_payload)

    return isinstance(payload, dict) and payload.get("type") == "result"
