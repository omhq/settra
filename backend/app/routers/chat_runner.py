import time
import logging

from typing import Any, AsyncIterator

from fastapi import HTTPException

from app.agent.consts import MAX_QUERY_ATTEMPTS
from app.agent.graph import build_graph
from app.agent.llm import AgentLLMError
from app.model_configs import build_llm
from app.routers.chat_diagnostics import (
    request_diagnostics,
    run_diagnostics,
    state_update_summary,
    utc_now,
)
from app.routers.chat_store import (
    attach_request_thread,
    ensure_thread,
    finish_request,
    get_connections,
    get_history,
    insert_message,
    normalise_connection_ids,
    reserve_request,
    set_thread_title,
)
from app.schemas import ChatRequest

logger = logging.getLogger(__name__)


async def prepare_chat_run(body: ChatRequest) -> dict[str, Any]:
    question = (body.question or body.message or "").strip()

    if not question:
        raise HTTPException(400, "Message is required")

    requested_connection_ids = normalise_connection_ids(body)

    await reserve_request(body.request_id)

    try:
        if body.thread_id is None:
            await get_connections(requested_connection_ids)

        thread = await ensure_thread(
            requested_connection_ids,
            body.model_config_id,
            body.thread_id,
            question,
        )
        thread_id = thread["id"]
        connections = await get_connections(thread["connection_ids"])

        await attach_request_thread(body.request_id, thread_id)

        history = await get_history(thread_id)

        if not history:
            await set_thread_title(thread_id, question)

        await insert_message(
            thread_id,
            "user",
            question,
            request_id=body.request_id,
            diagnostics={
                "status": "submitted",
                "request": request_diagnostics(
                    request_id=body.request_id,
                    thread_id=thread_id,
                    question=question,
                    connections=connections,
                    model=thread["model"],
                ),
                "timing": {"created_at": utc_now()},
            },
        )
    except HTTPException:
        await finish_request(body.request_id, "failed")
        raise

    return {
        "question": question,
        "thread": thread,
        "thread_id": thread_id,
        "connections": connections,
        "history": history,
    }


async def chat_events(
    body: ChatRequest,
    prepared: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    if prepared is None:
        prepared = await prepare_chat_run(body)

    question = prepared["question"]
    thread = prepared["thread"]
    thread_id = prepared["thread_id"]
    connections = prepared["connections"]
    history = prepared["history"]
    run_started_at = utc_now()
    run_started_perf = time.perf_counter()
    step_logs: list[dict[str, Any]] = []
    llm_calls: list[dict[str, Any]] = []
    first_connection = connections[0]
    final_state: dict[str, Any] = {
        "question": question,
        "connection_id": first_connection["id"],
        "connection_ids": [connection["id"] for connection in connections],
        "connection_name": first_connection["name"],
        "connections": [
            {
                "id": connection["id"],
                "name": connection["name"],
                "schema": connection["slug"],
                "plugin": connection["plugin"],
            }
            for connection in connections
        ],
        "model_config_id": thread["model"]["id"],
        "schema": first_connection["slug"],
        "plugin": first_connection["plugin"],
        "thread_id": thread_id,
        "history": history,
        "query_attempts": 0,
        "max_query_attempts": MAX_QUERY_ATTEMPTS,
        "query_workspace": [],
        "semantic_workspace": [],
    }

    yield {"type": "thread", "thread_id": thread_id}

    try:
        llm = build_llm(thread["model"])
        graph = build_graph(llm, diagnostics=llm_calls)
        labels = {
            "route": "Choosing analysis flow",
            "understand": "Reading schema and semantic layer",
            "generate_sql": "Choosing next query step",
            "search_semantics": "Searching semantic layer",
            "review_sql": "Reviewing analytical query",
            "execute_sql": "Running query step",
            "repair_sql": "Repairing SQL",
            "answer": "Writing answer",
        }

        logger.info(
            "Chat agent started thread_id=%s request_id=%s connections=%s "
            "model_config_id=%s question=%r",
            thread_id,
            body.request_id,
            final_state["connection_ids"],
            final_state["model_config_id"],
            question[:500],
        )

        async for update in graph.astream(final_state, stream_mode="updates"):
            for node_name, values in update.items():
                step_log: dict[str, Any] = {
                    "node": node_name,
                    "label": labels.get(node_name, node_name),
                    "completed_at": utc_now(),
                    "elapsed_ms": round(
                        (time.perf_counter() - run_started_perf) * 1000,
                        2,
                    ),
                }

                yield {
                    "type": "step",
                    "thread_id": thread_id,
                    "name": node_name,
                    "label": labels.get(node_name, node_name),
                }

                if isinstance(values, dict):
                    logger.info(
                        "Chat agent step completed thread_id=%s node=%s update=%s",
                        thread_id,
                        node_name,
                        state_update_summary(values),
                    )

                    step_log["update"] = state_update_summary(values)

                    if values.get("error"):
                        step_log["error"] = values.get("error")

                        logger.warning(
                            "Chat agent step error thread_id=%s node=%s error=%s",
                            thread_id,
                            node_name,
                            values.get("error"),
                        )

                    final_state.update(values)
                step_logs.append(step_log)

        diagnostics = run_diagnostics(
            request_id=body.request_id,
            thread_id=thread_id,
            question=question,
            connections=connections,
            model=thread["model"],
            started_at=run_started_at,
            started_perf=run_started_perf,
            step_logs=step_logs,
            llm_calls=llm_calls,
            final_state=final_state,
            status="completed",
            error=final_state.get("error"),
        )
        result_payload = {
            "type": "result",
            "thread_id": thread_id,
            "answer": final_state.get("answer") or final_state.get("error") or "",
            "sql": final_state.get("sql") or "",
            "results": final_state.get("results")
            or {"columns": [], "rows": [], "row_count": 0},
            "response_type": final_state.get("response_type") or "insight",
            "workflow": final_state.get("workflow") or "query",
            "query_plan": final_state.get("query_plan") or "",
            "route_reason": final_state.get("route_reason") or "",
            "query_workspace": final_state.get("query_workspace") or [],
            "semantic_workspace": final_state.get("semantic_workspace") or [],
            "query_attempts": final_state.get("query_attempts") or 0,
            "max_query_attempts": final_state.get("max_query_attempts")
            or MAX_QUERY_ATTEMPTS,
            "error": final_state.get("error") or None,
            "diagnostics": diagnostics,
        }

        await insert_message(
            thread_id,
            "assistant",
            result_payload["answer"],
            result_payload,
            diagnostics=diagnostics,
        )
        await finish_request(body.request_id, "completed")
        logger.info(
            "Chat agent completed thread_id=%s workflow=%s response_type=%s error=%s",
            thread_id,
            result_payload["workflow"],
            result_payload["response_type"],
            result_payload["error"],
        )
        yield result_payload
    except AgentLLMError as exc:
        message = exc.user_message
        diagnostics = run_diagnostics(
            request_id=body.request_id,
            thread_id=thread_id,
            question=question,
            connections=connections,
            model=thread["model"],
            started_at=run_started_at,
            started_perf=run_started_perf,
            step_logs=step_logs,
            llm_calls=llm_calls,
            final_state=final_state,
            status="failed",
            error=message,
        )

        logger.warning(
            "Chat agent model call failed thread_id=%s request_id=%s "
            "operation=%s error=%s user_message=%s",
            thread_id,
            body.request_id,
            exc.operation,
            exc.original_summary,
            message,
        )
        await insert_message(
            thread_id,
            "assistant",
            message,
            {"error": message, "diagnostics": diagnostics},
            diagnostics=diagnostics,
        )
        await finish_request(body.request_id, "failed")
        yield {
            "type": "error",
            "thread_id": thread_id,
            "message": message,
            "diagnostics": diagnostics,
        }
    except Exception as exc:
        message = f"Chat failed: {exc}"
        diagnostics = run_diagnostics(
            request_id=body.request_id,
            thread_id=thread_id,
            question=question,
            connections=connections,
            model=thread["model"],
            started_at=run_started_at,
            started_perf=run_started_perf,
            step_logs=step_logs,
            llm_calls=llm_calls,
            final_state=final_state,
            status="failed",
            error=message,
        )

        logger.exception(
            "Chat agent failed thread_id=%s request_id=%s error=%s",
            thread_id,
            body.request_id,
            exc,
        )
        await insert_message(
            thread_id,
            "assistant",
            message,
            {"error": message, "diagnostics": diagnostics},
            diagnostics=diagnostics,
        )
        await finish_request(body.request_id, "failed")
        yield {
            "type": "error",
            "thread_id": thread_id,
            "message": message,
            "diagnostics": diagnostics,
        }


async def run_chat_once(body: ChatRequest) -> dict[str, Any]:
    final_event: dict[str, Any] | None = None

    async for event in chat_events(body):
        if event.get("type") in {"result", "error"}:
            final_event = event

    if final_event is None:
        raise RuntimeError("Chat completed without a result")

    return final_event
