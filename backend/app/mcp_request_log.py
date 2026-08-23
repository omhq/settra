import os
import json

from math import ceil
from typing import Any

from app.db import db_connection
from app.utils import jsonable

MCP_REQUEST_HISTORY_LIMIT = max(
    100,
    int(os.getenv("MCP_REQUEST_HISTORY_LIMIT", "10000")),
)


def payload_size(value: Any) -> int:
    try:
        serialized = json.dumps(
            jsonable(value),
            separators=(",", ":"),
            ensure_ascii=False,
        )
    except Exception:
        serialized = str(value)

    return len(serialized.encode("utf-8"))


def tool_result_size(result: Any) -> int:
    """Measure one logical MCP tool result, not duplicate renderings of it."""

    if isinstance(result, tuple) and len(result) == 2:
        content, structured_content = result

        if structured_content is not None:
            return payload_size(structured_content)

        return payload_size(content)

    return payload_size(result)


def estimated_tokens(size_bytes: int) -> int:
    return ceil(size_bytes / 4) if size_bytes else 0


async def record_mcp_request(
    *,
    request_id: str | None,
    client_id: str | None,
    kind: str,
    name: str,
    status: str,
    duration_ms: int,
    request_bytes: int,
    response_bytes: int,
    response_token_bytes: int | None = None,
    error_type: str | None = None,
) -> None:
    async with db_connection() as db, db.transaction():
        await db.execute(
            """
            INSERT INTO mcp_requests (
                request_id,
                client_id,
                kind,
                name,
                status,
                duration_ms,
                request_bytes,
                response_bytes,
                estimated_input_tokens,
                estimated_output_tokens,
                error_type
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """,
            request_id,
            client_id,
            kind,
            name,
            status,
            duration_ms,
            request_bytes,
            response_bytes,
            estimated_tokens(request_bytes),
            estimated_tokens(
                response_bytes if response_token_bytes is None else response_token_bytes
            ),
            error_type,
        )
        await db.execute(
            """
            DELETE FROM mcp_requests
            WHERE id < COALESCE(
                (
                    SELECT id
                    FROM mcp_requests
                    ORDER BY id DESC
                    LIMIT 1 OFFSET $1
                ),
                0
            )
            """,
            MCP_REQUEST_HISTORY_LIMIT - 1,
        )


async def mcp_request_page(
    *,
    limit: int = 50,
    cursor: int | None = None,
) -> dict[str, Any]:
    async with db_connection() as db:
        params: list[Any] = []
        where = ""

        if cursor is not None:
            where = "WHERE id < $1"
            params.append(cursor)

        params.append(limit + 1)
        limit_parameter = len(params)

        rows = await db.fetch(
            f"""
            SELECT
                id,
                request_id,
                client_id,
                kind,
                name,
                status,
                duration_ms,
                request_bytes,
                response_bytes,
                estimated_input_tokens,
                estimated_output_tokens,
                error_type,
                created_at
            FROM mcp_requests
            {where}
            ORDER BY id DESC
            LIMIT ${limit_parameter}
            """,
            *params,
        )
        summary = await db.fetchrow("""
            SELECT
                COUNT(*) AS total_requests,
                COALESCE(SUM(
                    CASE WHEN status = 'success' THEN 1 ELSE 0 END
                ), 0) AS successful_requests,
                COALESCE(SUM(
                    CASE WHEN status = 'error' THEN 1 ELSE 0 END
                ), 0) AS failed_requests,
                COALESCE(SUM(estimated_input_tokens), 0)
                    AS estimated_input_tokens,
                COALESCE(SUM(estimated_output_tokens), 0)
                    AS estimated_output_tokens,
                COALESCE(AVG(duration_ms), 0)::double precision
                    AS average_duration_ms
            FROM mcp_requests
            """)

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    requests = []

    for row in page_rows:
        item = dict(row)
        created_at = item.get("created_at")
        if hasattr(created_at, "isoformat"):
            item["created_at"] = created_at.isoformat().replace("+00:00", "Z")

        item["estimated_tokens"] = (
            item["estimated_input_tokens"] + item["estimated_output_tokens"]
        )

        requests.append(item)

    summary_data = dict(summary) if summary is not None else {}
    for key in (
        "total_requests",
        "successful_requests",
        "failed_requests",
        "estimated_input_tokens",
        "estimated_output_tokens",
    ):
        summary_data[key] = int(summary_data.get(key) or 0)
    summary_data["average_duration_ms"] = float(
        summary_data.get("average_duration_ms") or 0
    )
    summary_data["estimated_tokens"] = int(
        summary_data.get("estimated_input_tokens") or 0
    ) + int(summary_data.get("estimated_output_tokens") or 0)

    return {
        "requests": requests,
        "summary": summary_data,
        "next_cursor": page_rows[-1]["id"] if has_more and page_rows else None,
        "tracking": {
            "payloads_stored": False,
            "token_estimate": (
                "Logical UTF-8 argument and result bytes divided by four; "
                "duplicate MCP result renderings are counted once."
            ),
            "history_limit": MCP_REQUEST_HISTORY_LIMIT,
        },
    }
