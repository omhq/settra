import os
import json

from math import ceil
from typing import Any

import aiosqlite

from app.common.config import DB_PATH
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
    error_type: str | None = None,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                client_id,
                kind,
                name,
                status,
                duration_ms,
                request_bytes,
                response_bytes,
                estimated_tokens(request_bytes),
                estimated_tokens(response_bytes),
                error_type,
            ),
        )
        await db.execute(
            """
            DELETE FROM mcp_requests
            WHERE id < COALESCE(
                (
                    SELECT id
                    FROM mcp_requests
                    ORDER BY id DESC
                    LIMIT 1 OFFSET ?
                ),
                0
            )
            """,
            (MCP_REQUEST_HISTORY_LIMIT - 1,),
        )
        await db.commit()


async def mcp_request_page(
    *,
    limit: int = 50,
    cursor: int | None = None,
) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        params: list[Any] = []
        where = ""

        if cursor is not None:
            where = "WHERE id < ?"
            params.append(cursor)

        params.append(limit + 1)

        rows = await (
            await db.execute(
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
                LIMIT ?
                """,
                params,
            )
        ).fetchall()
        summary = await (await db.execute("""
                SELECT
                    COUNT(*) AS total_requests,
                    COALESCE(SUM(
                        CASE WHEN status = 'success' THEN 1 ELSE 0 END
                    ), 0)
                        AS successful_requests,
                    COALESCE(SUM(
                        CASE WHEN status = 'error' THEN 1 ELSE 0 END
                    ), 0)
                        AS failed_requests,
                    COALESCE(SUM(estimated_input_tokens), 0)
                        AS estimated_input_tokens,
                    COALESCE(SUM(estimated_output_tokens), 0)
                        AS estimated_output_tokens,
                    COALESCE(AVG(duration_ms), 0)
                        AS average_duration_ms
                FROM mcp_requests
                """)).fetchone()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    requests = []

    for row in page_rows:
        item = dict(row)
        created_at = str(item.get("created_at") or "")

        if created_at and not created_at.endswith("Z"):
            item["created_at"] = f"{created_at.replace(' ', 'T')}Z"

        item["estimated_tokens"] = (
            item["estimated_input_tokens"] + item["estimated_output_tokens"]
        )

        requests.append(item)

    summary_data = dict(summary) if summary is not None else {}
    summary_data["estimated_tokens"] = int(
        summary_data.get("estimated_input_tokens") or 0
    ) + int(summary_data.get("estimated_output_tokens") or 0)

    return {
        "requests": requests,
        "summary": summary_data,
        "next_cursor": page_rows[-1]["id"] if has_more and page_rows else None,
        "tracking": {
            "payloads_stored": False,
            "token_estimate": "Serialized UTF-8 payload bytes divided by four.",
            "history_limit": MCP_REQUEST_HISTORY_LIMIT,
        },
    }
