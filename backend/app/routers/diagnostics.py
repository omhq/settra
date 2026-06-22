from typing import Any
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_diagnostics(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": model.get("id"),
        "name": model.get("name"),
        "provider": model.get("provider"),
        "model": model.get("model"),
        "config": model.get("config") or {},
    }


def connection_diagnostics(
    connections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "id": connection.get("id"),
            "name": connection.get("name"),
            "schema": connection.get("slug") or connection.get("schema"),
            "plugin": connection.get("plugin"),
            "status": connection.get("status"),
        }
        for connection in connections
    ]


def token_usage_summary(llm_calls: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "calls_with_usage": 0,
        "calls": len(llm_calls),
    }

    for call in llm_calls:
        usage = call.get("token_usage")

        if not isinstance(usage, dict):
            continue

        summary["calls_with_usage"] += 1
        summary["input_tokens"] += int(usage.get("input_tokens") or 0)
        summary["output_tokens"] += int(usage.get("output_tokens") or 0)
        summary["total_tokens"] += int(usage.get("total_tokens") or 0)

    if not summary["calls_with_usage"]:
        return {"calls": len(llm_calls), "calls_with_usage": 0}

    return summary
