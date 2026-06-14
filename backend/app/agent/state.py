from typing import Any

from app.agent.schemas import AnalyticsState


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

    return "\n".join(
        f"{message.get('role', 'user')}: {message.get('content', '')}"
        for message in messages[-12:]
    )
