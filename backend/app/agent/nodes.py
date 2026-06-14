from langchain_core.language_models.chat_models import BaseChatModel
from typing import Any

from app.agent.answers import answer_state
from app.agent.context import load_context_state
from app.agent.flow import route_question_state
from app.agent.llm import AgentLLM
from app.agent.semantic_search import search_semantics_state
from app.agent.schemas import AnalyticsState
from app.agent.sql import (
    execute_sql_state,
    generate_sql_state,
    repair_sql_state,
    review_sql_state,
)


class AnalyticsAgentNodes:
    def __init__(
        self,
        llm: BaseChatModel | None,
        diagnostics: list[dict[str, Any]] | None = None,
    ):
        self.llm = AgentLLM(llm, diagnostics=diagnostics)

    async def route(self, state: AnalyticsState) -> AnalyticsState:
        return await route_question_state(state, self.llm)

    async def understand(self, state: AnalyticsState) -> AnalyticsState:
        return await load_context_state(state, self.llm)

    async def generate_sql(self, state: AnalyticsState) -> AnalyticsState:
        return await generate_sql_state(state, self.llm)

    async def search_semantics(self, state: AnalyticsState) -> AnalyticsState:
        return await search_semantics_state(state)

    async def review_sql(self, state: AnalyticsState) -> AnalyticsState:
        return await review_sql_state(state, self.llm)

    async def repair_sql(self, state: AnalyticsState) -> AnalyticsState:
        return await repair_sql_state(state, self.llm)

    async def execute_sql(self, state: AnalyticsState) -> AnalyticsState:
        return await execute_sql_state(state)

    async def answer(self, state: AnalyticsState) -> AnalyticsState:
        return await answer_state(state, self.llm)
