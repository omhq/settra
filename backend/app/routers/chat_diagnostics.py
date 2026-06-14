import time

from typing import Any
from datetime import datetime, timezone


def state_update_summary(values: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}

    for key, value in values.items():
        if key == "results" and isinstance(value, dict):
            summary[key] = {
                "columns": value.get("columns", []),
                "row_count": value.get("row_count", 0),
                "truncated": value.get("truncated", False),
            }
        elif key in {
            "context",
            "raw_schema",
            "semantic_meta",
            "semantic_contract",
            "semantic_contract_text",
        }:
            summary[key] = f"<{type(value).__name__}>"
        elif key == "query_workspace" and isinstance(value, list):
            summary[key] = [
                {
                    "attempt": item.get("attempt"),
                    "name": item.get("name"),
                    "row_count": item.get("row_count"),
                    "error": item.get("error"),
                }
                for item in value
            ]
        elif key == "semantic_workspace" and isinstance(value, list):
            summary[key] = [
                {
                    "attempt": item.get("attempt"),
                    "query": item.get("query"),
                    "result_count": item.get("result_count"),
                }
                for item in value
            ]
        elif key == "sql":
            summary[key] = f"{len(str(value))} chars"
        elif key in {"answer", "direct_answer"}:
            summary[key] = f"{len(str(value))} chars"
        else:
            summary[key] = value

    return summary


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


def request_diagnostics(
    *,
    request_id: str | None,
    thread_id: int,
    question: str,
    connections: list[dict[str, Any]],
    model: dict[str, Any],
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "thread_id": thread_id,
        "question_chars": len(question),
        "connection_ids": [connection["id"] for connection in connections],
        "connections": connection_diagnostics(connections),
        "model": model_diagnostics(model),
    }


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


def run_diagnostics(
    *,
    request_id: str | None,
    thread_id: int,
    question: str,
    connections: list[dict[str, Any]],
    model: dict[str, Any],
    started_at: str,
    started_perf: float,
    step_logs: list[dict[str, Any]],
    llm_calls: list[dict[str, Any]],
    final_state: dict[str, Any],
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    finished_at = utc_now()

    return {
        "status": status,
        "request": request_diagnostics(
            request_id=request_id,
            thread_id=thread_id,
            question=question,
            connections=connections,
            model=model,
        ),
        "timing": {
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": round((time.perf_counter() - started_perf) * 1000, 2),
        },
        "steps": step_logs,
        "llm_calls": llm_calls,
        "token_usage": token_usage_summary(llm_calls),
        "final_state": state_update_summary(final_state),
        "error": error,
    }
