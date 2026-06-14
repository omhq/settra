import logging
import asyncpg

from typing import Any

from app.agent.consts import (
    MAX_QUERY_ATTEMPTS,
    MAX_RESULT_ROWS,
    STEAMPIPE_DB_PASSWORD,
    STEAMPIPE_HOST,
    STEAMPIPE_PORT,
)
from app.agent.query_workspace import build_query_workspace_item
from app.agent.schemas import AnalyticsState, QueryResult
from app.utils import jsonable

logger = logging.getLogger(__name__)


async def execute_sql_state(state: AnalyticsState) -> AnalyticsState:
    if state.get("error") or not state.get("sql"):
        return {"results": QueryResult().model_dump()}

    attempt = int(state.get("query_attempts") or 0) + 1
    max_attempts = int(state.get("max_query_attempts") or MAX_QUERY_ATTEMPTS)
    sql = state["sql"]
    workspace = list(state.get("query_workspace", []))

    pg = await asyncpg.connect(
        host=STEAMPIPE_HOST,
        port=STEAMPIPE_PORT,
        database="steampipe",
        user="steampipe",
        password=STEAMPIPE_DB_PASSWORD,
        timeout=10,
    )
    try:
        await pg.execute("SET statement_timeout = '15000'")

        limited_sql = (
            f"SELECT * FROM (\n{sql}\n) AS settra_chat_result "
            f"LIMIT {MAX_RESULT_ROWS}"
        )
        statement = await pg.prepare(limited_sql)
        records = await statement.fetch()
        columns = [attr.name for attr in statement.get_attributes()]
    except Exception as exc:
        logger.exception(f"Steampipe query failed error={exc} sql={sql}")
        message = f"Steampipe query failed: {exc}"
        workspace.append(
            build_query_workspace_item(
                state,
                attempt=attempt,
                max_attempts=max_attempts,
                sql=sql,
                columns=[],
                rows=[],
                error=message,
            )
        )
        return {
            "query_attempts": attempt,
            "query_workspace": workspace,
            "error": message,
            "needs_retry": True,
            "results": QueryResult().model_dump(),
        }
    finally:
        await pg.close()

    rows: list[dict[str, Any]] = [
        {key: jsonable(value) for key, value in dict(record).items()}
        for record in records
    ]

    results = QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=len(rows) >= MAX_RESULT_ROWS,
    ).model_dump()
    workspace.append(
        build_query_workspace_item(
            state,
            attempt=attempt,
            max_attempts=max_attempts,
            sql=sql,
            columns=columns,
            rows=rows,
            error="",
        )
    )

    return {
        "query_attempts": attempt,
        "query_workspace": workspace,
        "results": results,
        "error": "",
        "needs_retry": False,
    }
