from langgraph.graph import END, StateGraph
from langchain_core.language_models.chat_models import BaseChatModel
from typing import Any

from app.agent.consts import MAX_QUERY_ATTEMPTS
from app.agent.nodes import AnalyticsAgentNodes
from app.agent.schemas import AnalyticsState


def build_graph(
    llm: BaseChatModel | None,
    diagnostics: list[dict[str, Any]] | None = None,
):
    nodes = AnalyticsAgentNodes(llm, diagnostics=diagnostics)
    graph = StateGraph(AnalyticsState)

    graph.add_node("route", nodes.route)
    graph.add_node("understand", nodes.understand)
    graph.add_node("generate_sql", nodes.generate_sql)
    graph.add_node("search_semantics", nodes.search_semantics)
    graph.add_node("review_sql", nodes.review_sql)
    graph.add_node("repair_sql", nodes.repair_sql)
    graph.add_node("execute_sql", nodes.execute_sql)
    graph.add_node("answer", nodes.answer)

    graph.set_entry_point("route")
    graph.add_conditional_edges(
        "route",
        _after_route,
        {
            "answer": "answer",
            "understand": "understand",
        },
    )
    graph.add_edge("understand", "generate_sql")
    graph.add_conditional_edges(
        "generate_sql",
        _after_generate_sql,
        {
            "answer": "answer",
            "review_sql": "review_sql",
            "execute_sql": "execute_sql",
            "search_semantics": "search_semantics",
        },
    )
    graph.add_conditional_edges(
        "search_semantics",
        _after_search_semantics,
        {
            "answer": "answer",
            "generate_sql": "generate_sql",
        },
    )
    graph.add_conditional_edges(
        "review_sql",
        _after_review_sql,
        {
            "answer": "answer",
            "execute_sql": "execute_sql",
            "repair_sql": "repair_sql",
        },
    )
    graph.add_conditional_edges(
        "execute_sql",
        _after_execute_sql,
        {
            "answer": "answer",
            "generate_sql": "generate_sql",
            "repair_sql": "repair_sql",
        },
    )
    graph.add_conditional_edges(
        "repair_sql",
        _after_repair_sql,
        {
            "answer": "answer",
            "execute_sql": "execute_sql",
        },
    )
    graph.add_edge("answer", END)

    return graph.compile()


def _after_route(state: AnalyticsState) -> str:
    if state.get("error") or state.get("workflow") == "direct":
        return "answer"

    return "understand"


def _after_generate_sql(state: AnalyticsState) -> str:
    if state.get("error"):
        return "answer"
    if state.get("agent_action") == "search_semantics":
        return "search_semantics"
    if not state.get("sql"):
        return "answer"
    if state.get("workflow") == "analysis" and state.get("sql"):
        return "review_sql"

    return "execute_sql"


def _after_search_semantics(state: AnalyticsState) -> str:
    attempts = int(state.get("query_attempts") or 0)
    max_attempts = int(state.get("max_query_attempts") or MAX_QUERY_ATTEMPTS)

    if state.get("error") or attempts >= max_attempts:
        return "answer"

    return "generate_sql"


def _after_review_sql(state: AnalyticsState) -> str:
    if (
        state.get("error")
        and state.get("needs_retry")
        and state.get("sql")
        and not state.get("repair_attempted")
    ):
        return "repair_sql"
    if state.get("error"):
        return "answer"

    return "execute_sql"


def _after_execute_sql(state: AnalyticsState) -> str:
    attempts = int(state.get("query_attempts") or 0)
    max_attempts = int(state.get("max_query_attempts") or MAX_QUERY_ATTEMPTS)

    if (
        state.get("needs_retry")
        and state.get("sql")
        and not state.get("repair_attempted")
        and attempts < max_attempts
    ):
        return "repair_sql"

    if state.get("workflow") == "analysis" and attempts < max_attempts:
        return "generate_sql"

    return "answer"


def _after_repair_sql(state: AnalyticsState) -> str:
    if state.get("error") or not state.get("sql"):
        return "answer"

    return "execute_sql"
