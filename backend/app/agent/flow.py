import logging

from app.agent.llm import AgentLLM, AgentLLMError
from app.agent.prompts import PromptConfigError, render_prompt_messages
from app.agent.schemas import AnalyticsState, IntentDecision
from app.agent.state import format_history, state_connector_plugins

logger = logging.getLogger(__name__)


async def route_question_state(
    state: AnalyticsState,
    llm: AgentLLM,
) -> AnalyticsState:
    if not llm.configured:
        return {
            "workflow": "query",
            "route_reason": "No model is configured, so routing cannot be inferred.",
        }

    try:
        messages = await render_prompt_messages(
            "intent_router",
            {
                "question": state["question"],
                "history": format_history(state.get("history", [])),
                "connections": _connection_summary(state),
                "connector_plugins": state_connector_plugins(state),
            },
        )
        payload = await llm.structured_model(
            messages,
            IntentDecision,
            operation="intent_router",
        )
    except PromptConfigError as exc:
        return {"error": str(exc), "needs_retry": False}
    except AgentLLMError as exc:
        logger.warning(
            f"Intent routing LLM failed; defaulting to query workflow "
            f"operation={exc.operation} error={exc.original_summary} "
            f"user_message={exc.user_message}"
        )
        return {
            "workflow": "query",
            "route_reason": (
                "Routing model failed; defaulting to a focused SQL query."
            ),
        }
    except Exception as exc:
        logger.warning(
            f"Intent routing failed; defaulting to query workflow error={exc}",
            exc_info=True,
        )
        return {
            "workflow": "query",
            "route_reason": "Routing failed; defaulting to a focused SQL query.",
        }

    return {
        "workflow": payload.workflow,
        "route_reason": payload.reason,
        "direct_answer": payload.direct_answer,
        "response_type": payload.response_type,
    }


def _connection_summary(state: AnalyticsState) -> str:
    connections = state.get("connections") or []

    if not connections:
        return "No active connections are selected."

    return "\n".join(
        (
            f"- {connection.get('name', 'Connection')}: "
            f"plugin={connection.get('plugin', 'unknown')}, "
            f"schema={connection.get('schema', 'unknown')}"
        )
        for connection in connections
    )
