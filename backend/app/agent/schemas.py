from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

PromptMessage = dict[str, str]
WorkflowMode = Literal["direct", "query", "analysis"]
ResponseType = Literal["table", "chart", "insight"]
AgentActionType = Literal["search_semantics", "run_query", "final_answer"]
SemanticSearchType = Literal["table", "column", "relationship", "metric", "warning"]


class StrictStructuredModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntentDecision(StrictStructuredModel):
    """Routing decision for whether a prompt needs data work."""

    workflow: WorkflowMode = Field(
        description=(
            "direct for no data access, query for one focused SQL result, "
            "analysis for multi-step or diagnostic analytical work"
        )
    )
    reason: str = Field(description="Short explanation for the routing decision")
    direct_answer: str = Field(
        description="Answer to return when workflow is direct; otherwise empty",
    )
    response_type: ResponseType = Field(
        description="Best UI rendering hint for the final answer",
    )


class TableSelection(StrictStructuredModel):
    """Tables that are likely relevant for a user question."""

    tables: list[str] = Field(description="Relevant table names from the allowed list")
    reason: str = Field(description="Short explanation for the table selection")


class SQLPlan(StrictStructuredModel):
    """A read-only SQL plan for answering an analytics question."""

    query_plan: str = Field(description="Short plan for the SQL query")
    sql: str = Field(description="Read-only SQL, or empty string when not needed")
    response_type: ResponseType = Field(description="Best UI rendering hint")
    direct_answer: str = Field(
        description="Answer to return when SQL is not needed; otherwise empty"
    )
    used_tables: list[str] = Field(
        default_factory=list,
        description="Schema-qualified tables used by the SQL",
    )
    used_relationships: list[str] = Field(
        default_factory=list,
        description="Confirmed relationships used, in from=to format",
    )


class SQLAgentAction(StrictStructuredModel):
    """The next bounded tool action for an analytics workflow."""

    action: AgentActionType = Field(
        description=(
            "search_semantics to retrieve semantic context, run_query to execute "
            "one SQL step, final_answer when enough evidence has been gathered"
        ),
    )
    step_name: str = Field(description="Short stable label for this step")
    purpose: str = Field(description="Why this step is needed")
    query_plan: str = Field(description="Short plan for this SQL step")
    sql: str = Field(
        description="Read-only SQL for run_query, or empty string for final_answer"
    )
    response_type: ResponseType = Field(description="Best UI rendering hint")
    direct_answer: str = Field(
        description="Final answer when action is final_answer; otherwise empty"
    )
    used_tables: list[str] = Field(
        description="Schema-qualified tables used by the SQL, or empty list"
    )
    used_relationships: list[str] = Field(
        description="Relationships or join assumptions used by the SQL, or empty list"
    )
    search_query: str = Field(
        description="Keyword query for search_semantics, otherwise empty"
    )
    search_types: list[SemanticSearchType] = Field(
        description=(
            "Semantic item types to search for search_semantics, otherwise empty"
        )
    )
    search_connection_ids: list[int] = Field(
        description=(
            "Connection ids to search for search_semantics, otherwise empty to use active connections"
        )
    )
    search_limit: int = Field(
        description="Maximum semantic results for search_semantics, otherwise 0"
    )


class SQLReview(StrictStructuredModel):
    """Safety and semantic review of generated SQL."""

    approved: bool = Field(description="True when sql is safe and semantically aligned")
    issues: list[str] = Field(description="Issues found during review, or empty list")
    rewritten_sql: str = Field(
        description="Corrected SQL when approved is false and a safe fix is clear",
    )
    revised_query_plan: str = Field(
        description="Updated query plan when SQL was rewritten; otherwise empty"
    )


class QueryResult(StrictStructuredModel):
    """Rows returned by a SQL execution step."""

    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False


class QueryWorkspaceItem(StrictStructuredModel):
    """One attempted SQL step saved for later planning or answer writing."""

    attempt: int
    max_attempts: int
    name: str
    purpose: str
    query_plan: str
    sql: str
    used_tables: list[str] = Field(default_factory=list)
    used_relationships: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    error: str = ""


class SemanticSearchRequest(StrictStructuredModel):
    """A bounded search over semantic metadata."""

    query: str = ""
    types: list[SemanticSearchType] = Field(default_factory=list)
    connection_ids: list[int] = Field(default_factory=list)
    limit: int = Field(default=12, ge=1, le=20)


class SemanticSearchWorkspaceEntry(StrictStructuredModel):
    """One semantic search attempt saved in the agent workspace."""

    attempt: int
    max_attempts: int
    query: str
    types: list[SemanticSearchType]
    connection_ids: list[int] = Field(default_factory=list)
    result_count: int
    results: list[dict[str, Any]] = Field(default_factory=list)


class AnalyticsState(TypedDict, total=False):
    # Input
    question: str
    connection_id: int
    connection_ids: list[int]
    connection_name: str
    connections: list[dict[str, Any]]
    model_config_id: int
    schema: str
    plugin: str
    thread_id: int
    history: list[dict[str, Any]]

    # Flow control
    workflow: WorkflowMode
    route_reason: str

    # Built up through the graph
    raw_schema: list[dict[str, Any]]  # from Steampipe information_schema/metadata
    semantic_meta: dict[str, Any]  # from SQLite/YAML
    semantic_contract: dict[str, Any]
    semantic_contract_text: str
    relevant_tables: list[str]  # subset identified as useful
    context: str  # final formatted context string for LLM
    schema_error: str

    # Query
    agent_action: AgentActionType
    query_plan: str
    current_step_name: str
    current_step_purpose: str
    query_attempts: int
    max_query_attempts: int
    query_workspace: list[dict[str, Any]]
    semantic_workspace: list[dict[str, Any]]
    semantic_search_query: str
    semantic_search_types: list[SemanticSearchType]
    semantic_search_connection_ids: list[int]
    semantic_search_limit: int
    sql: str
    sql_review: dict[str, Any]
    repair_attempted: bool
    results: dict[str, Any]
    direct_answer: str
    used_tables: list[str]
    used_relationships: list[str]

    # Output
    response_type: str  # table | chart | insight
    answer: str
    error: str
    needs_retry: bool
