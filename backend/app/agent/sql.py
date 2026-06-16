import re
import logging

from app.agent.consts import MAX_QUERY_ATTEMPTS
from app.agent.query_execution import execute_sql_state
from app.agent.query_workspace import format_query_workspace_for_prompt
from app.agent.semantic_workspace import format_semantic_workspace_for_prompt
from app.agent.schemas import AnalyticsState, SQLAgentAction, SQLPlan, SQLReview
from app.agent.sql_safety import sanitize_sql
from app.agent.state import (
    format_history,
    schema_instruction,
    state_connector_plugins,
)
from app.agent.llm import AgentLLM, AgentLLMError
from app.agent.prompts import PromptConfigError, render_prompt_messages

logger = logging.getLogger(__name__)

__all__ = [
    "execute_sql_state",
    "format_query_workspace_for_prompt",
    "generate_sql_state",
    "repair_sql_state",
    "review_sql_state",
    "sanitize_sql",
]


async def generate_sql_state(
    state: AnalyticsState,
    llm: AgentLLM,
) -> AnalyticsState:
    if state.get("schema_error") and not state.get("raw_schema"):
        return {
            "error": f"Could not read Steampipe schema: {state['schema_error']}",
            "needs_retry": True,
        }

    if not llm.configured:
        return {
            "error": "No chat model is configured for this thread.",
            "needs_retry": False,
        }

    attempts = int(state.get("query_attempts") or 0)
    max_attempts = int(state.get("max_query_attempts") or MAX_QUERY_ATTEMPTS)

    if attempts >= max_attempts:
        return {
            "agent_action": "final_answer",
            "current_step_name": "Attempt limit reached",
            "current_step_purpose": "Answer from the available query workspace",
            "query_plan": (
                f"Tool attempt limit reached after {attempts} of {max_attempts}; "
                "answer from the workspace."
            ),
            "sql": "",
            "response_type": state.get("response_type", "insight"),
            "direct_answer": "",
            "error": "",
            "needs_retry": False,
        }

    try:
        messages = await render_prompt_messages(
            "sql_agent_step",
            {
                "context": state.get("context", ""),
                "semantic_contract": state.get("semantic_contract_text", "{}"),
                "history": format_history(state.get("history", [])),
                "question": state["question"],
                "schema_instruction": schema_instruction(state),
                "workflow": state.get("workflow", "query"),
                "route_reason": state.get("route_reason", ""),
                "query_workspace": format_query_workspace_for_prompt(
                    state.get("query_workspace", [])
                ),
                "semantic_workspace": format_semantic_workspace_for_prompt(
                    state.get("semantic_workspace", [])
                ),
                "query_attempts": attempts,
                "max_query_attempts": max_attempts,
                "next_query_attempt": attempts + 1,
                "attempts_remaining": max(max_attempts - attempts, 0),
                "attempt_budget_notice": _attempt_budget_notice(
                    attempts,
                    max_attempts,
                ),
                "connector_plugins": state_connector_plugins(state),
            },
        )
        payload = await llm.structured_model(
            messages,
            SQLAgentAction,
            operation="sql_agent_step",
        )
    except PromptConfigError as exc:
        return {"error": str(exc), "needs_retry": False}
    except AgentLLMError as exc:
        logger.warning(
            f"SQL planning LLM failed operation={exc.operation} "
            f"error={exc.original_summary} user_message={exc.user_message}"
        )
        return {
            "error": exc.user_message,
            "needs_retry": exc.retryable,
        }
    except Exception as exc:
        logger.exception(f"SQL planning failed error={exc}")
        return {
            "error": f"SQL planning failed: {exc}",
            "needs_retry": True,
        }

    action = payload.action
    sql = payload.sql.strip()

    if action == "final_answer":
        return {
            "agent_action": "final_answer",
            "current_step_name": payload.step_name or "Final answer",
            "current_step_purpose": payload.purpose,
            "query_plan": payload.query_plan,
            "sql": "",
            "response_type": payload.response_type,
            "direct_answer": payload.direct_answer,
            "used_tables": payload.used_tables,
            "used_relationships": payload.used_relationships,
            "error": "",
            "needs_retry": False,
        }

    if action == "search_semantics":
        return {
            "agent_action": "search_semantics",
            "current_step_name": payload.step_name or "Semantic search",
            "current_step_purpose": payload.purpose,
            "query_plan": payload.query_plan,
            "sql": "",
            "response_type": payload.response_type,
            "direct_answer": "",
            "used_tables": [],
            "used_relationships": [],
            "semantic_search_query": payload.search_query,
            "semantic_search_types": payload.search_types,
            "semantic_search_connection_ids": payload.search_connection_ids,
            "semantic_search_limit": payload.search_limit or 12,
            "repair_attempted": False,
            "error": "",
            "needs_retry": False,
        }

    try:
        safe_sql = sanitize_sql(sql) if sql else ""
    except ValueError as exc:
        return {"error": str(exc), "sql": sql, "needs_retry": True}

    if _successful_sql_has_run(state, safe_sql):
        return {
            "agent_action": "final_answer",
            "current_step_name": "Answer from existing results",
            "current_step_purpose": (
                "The proposed query already ran successfully; answer from "
                "the existing query workspace instead of repeating it."
            ),
            "query_plan": ("Use the successful query result already in the workspace."),
            "response_type": payload.response_type,
            "direct_answer": "",
            "used_tables": payload.used_tables,
            "used_relationships": payload.used_relationships,
            "repair_attempted": False,
            "error": "",
            "needs_retry": False,
        }

    return {
        "agent_action": "run_query",
        "current_step_name": payload.step_name or "Query step",
        "current_step_purpose": payload.purpose,
        "query_plan": payload.query_plan,
        "sql": safe_sql,
        "response_type": payload.response_type,
        "direct_answer": "",
        "used_tables": payload.used_tables,
        "used_relationships": payload.used_relationships,
        "repair_attempted": False,
        "error": "",
        "needs_retry": False,
    }


async def review_sql_state(
    state: AnalyticsState,
    llm: AgentLLM,
) -> AnalyticsState:
    if state.get("error") or not state.get("sql"):
        return {}

    if not llm.configured:
        return {}

    try:
        messages = await render_prompt_messages(
            "sql_reviewer",
            {
                "context": state.get("context", ""),
                "semantic_contract": state.get("semantic_contract_text", "{}"),
                "question": state["question"],
                "step_name": state.get("current_step_name", ""),
                "step_purpose": state.get("current_step_purpose", ""),
                "query_plan": state.get("query_plan", ""),
                "sql": state.get("sql", ""),
                "schema_instruction": schema_instruction(state),
                "query_attempts": state.get("query_attempts", 0),
                "max_query_attempts": state.get(
                    "max_query_attempts",
                    MAX_QUERY_ATTEMPTS,
                ),
                "connector_plugins": state_connector_plugins(state),
            },
        )
        payload = await llm.structured_model(
            messages,
            SQLReview,
            operation="sql_reviewer",
        )
    except PromptConfigError as exc:
        return {"error": str(exc), "needs_retry": False}
    except AgentLLMError as exc:
        logger.warning(
            f"SQL review LLM failed; proceeding with sanitized SQL "
            f"operation={exc.operation} error={exc.original_summary} "
            f"user_message={exc.user_message}"
        )
        return {}
    except Exception as exc:
        logger.warning(
            f"SQL review failed; proceeding with sanitized SQL error={exc}",
            exc_info=True,
        )
        return {}

    review = {
        "approved": payload.approved,
        "issues": payload.issues,
        "rewritten_sql": payload.rewritten_sql,
        "revised_query_plan": payload.revised_query_plan,
    }

    if review["approved"]:
        return {"sql_review": review}

    rewritten_sql = review["rewritten_sql"].strip()

    if not rewritten_sql:
        issues = "; ".join(map(str, review["issues"])) or "SQL was not approved."
        return {
            "sql_review": review,
            "error": f"Could not produce a safe analytical query: {issues}",
            "needs_retry": True,
        }

    try:
        safe_sql = sanitize_sql(rewritten_sql)
    except ValueError as exc:
        return {
            "sql_review": review,
            "error": f"SQL review produced unsafe SQL: {exc}",
            "needs_retry": True,
        }

    updates: AnalyticsState = {"sql_review": review, "sql": safe_sql}

    if review["revised_query_plan"]:
        updates["query_plan"] = review["revised_query_plan"]

    return updates


async def repair_sql_state(
    state: AnalyticsState,
    llm: AgentLLM,
) -> AnalyticsState:
    if state.get("repair_attempted"):
        return {}

    if not state.get("error") or not state.get("sql"):
        return {}

    if not llm.configured:
        return {"repair_attempted": True}

    try:
        messages = await render_prompt_messages(
            "sql_repairer",
            {
                "context": state.get("context", ""),
                "semantic_contract": state.get("semantic_contract_text", "{}"),
                "history": format_history(state.get("history", [])),
                "question": state["question"],
                "step_name": state.get("current_step_name", ""),
                "step_purpose": state.get("current_step_purpose", ""),
                "query_plan": state.get("query_plan", ""),
                "sql": state.get("sql", ""),
                "error": state.get("error", ""),
                "schema_instruction": schema_instruction(state),
                "query_workspace": format_query_workspace_for_prompt(
                    state.get("query_workspace", [])
                ),
                "semantic_workspace": format_semantic_workspace_for_prompt(
                    state.get("semantic_workspace", [])
                ),
                "query_attempts": state.get("query_attempts", 0),
                "max_query_attempts": state.get(
                    "max_query_attempts",
                    MAX_QUERY_ATTEMPTS,
                ),
                "connector_plugins": state_connector_plugins(state),
            },
        )
        payload = await llm.structured_model(
            messages,
            SQLPlan,
            operation="sql_repairer",
        )
    except PromptConfigError as exc:
        return {
            "repair_attempted": True,
            "error": str(exc),
            "needs_retry": False,
        }
    except AgentLLMError as exc:
        logger.warning(
            f"SQL repair LLM failed operation={exc.operation} "
            f"error={exc.original_summary} user_message={exc.user_message}"
        )
        return {
            "repair_attempted": True,
            "error": exc.user_message,
            "needs_retry": False,
        }
    except Exception as exc:
        logger.exception(f"SQL repair failed error={exc}")
        return {"repair_attempted": True, "needs_retry": False}

    sql = payload.sql.strip()

    try:
        safe_sql = sanitize_sql(sql) if sql else ""
    except ValueError as exc:
        return {
            "repair_attempted": True,
            "error": f"SQL repair produced unsafe SQL: {exc}",
            "sql": sql,
            "needs_retry": False,
        }

    return {
        "repair_attempted": True,
        "error": "",
        "needs_retry": False,
        "query_plan": payload.query_plan or state.get("query_plan") or "",
        "sql": safe_sql,
        "response_type": payload.response_type,
        "direct_answer": payload.direct_answer,
    }


def _attempt_budget_notice(attempts: int, max_attempts: int) -> str:
    remaining = max(max_attempts - attempts, 0)

    if remaining <= 0:
        return (
            f"No tool attempts remain. You used {attempts} of {max_attempts}; "
            "return final_answer from the workspace."
        )
    if remaining == 1:
        return (
            f"The next tool call will be attempt {attempts + 1} of {max_attempts}. "
            "This is the final tool attempt; use it only if needed, otherwise return final_answer."
        )

    return (
        f"The next tool call will be attempt {attempts + 1} of {max_attempts}. "
        f"{remaining} tool attempts remain."
    )


def _successful_sql_has_run(state: AnalyticsState, sql: str) -> bool:
    normalized = _normalize_sql(sql)

    if not normalized:
        return False

    for item in state.get("query_workspace", []):
        if item.get("error"):
            continue
        if _normalize_sql(str(item.get("sql") or "")) == normalized:
            return True

    return False


def _normalize_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.strip().rstrip(";").strip()).lower()
