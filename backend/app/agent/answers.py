import json

from app.agent.llm import AgentLLM, AgentLLMError
from app.agent.prompts import PromptConfigError, render_prompt_messages
from app.agent.query_workspace import format_query_workspace_for_prompt
from app.agent.semantic_workspace import format_semantic_workspace_for_prompt
from app.agent.schemas import AnalyticsState
from app.agent.state import state_connector_plugins
from app.pruning import prune_query_result_rows_for_prompt


async def answer_state(
    state: AnalyticsState,
    llm: AgentLLM,
) -> AnalyticsState:
    if state.get("workflow") == "direct":
        answer = state.get("direct_answer") or state.get("error") or ""

        if answer:
            return {"answer": answer}

        return {
            "answer": (
                "I can answer that without querying the data, "
                "but I need a little more detail."
            )
        }

    if state.get("direct_answer") and not state.get("sql"):
        return {"answer": state["direct_answer"]}

    if state.get("error"):
        return {"answer": state["error"]}

    if not llm.configured:
        count = state.get("results", {}).get("row_count", 0)
        return {"answer": f"The query ran and returned {count} rows."}

    rows = prune_query_result_rows_for_prompt(state.get("results", {}))
    workspace = state.get("query_workspace", [])
    semantic_workspace = state.get("semantic_workspace", [])

    try:
        messages = await render_prompt_messages(
            "answer_writer",
            {
                "question": state["question"],
                "sql": state.get("sql", ""),
                "query_plan": state.get("query_plan", ""),
                "workflow": state.get("workflow", "query"),
                "rows": rows,
                "rows_json": json.dumps(rows, indent=2),
                "row_count": state.get("results", {}).get("row_count", 0),
                "truncated": state.get("results", {}).get("truncated", False),
                "response_type": state.get("response_type", "insight"),
                "query_workspace": format_query_workspace_for_prompt(workspace),
                "semantic_workspace": format_semantic_workspace_for_prompt(
                    semantic_workspace
                ),
                "query_attempts": state.get("query_attempts", 0),
                "max_query_attempts": state.get("max_query_attempts", 0),
                "connector_plugins": state_connector_plugins(state),
            },
        )
    except PromptConfigError as exc:
        return {"answer": str(exc), "error": str(exc)}

    try:
        answer = await llm.text(messages, operation="answer_writer")
    except AgentLLMError as exc:
        return {
            "answer": exc.user_message,
            "error": exc.user_message,
            "needs_retry": exc.retryable,
        }

    return {"answer": answer.strip()}
