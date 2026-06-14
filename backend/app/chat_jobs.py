import json
import logging
import asyncio

from collections.abc import AsyncIterator
from typing import Any

import aiosqlite

from app.db import DB_PATH
from app.schemas import ChatRequest
from app.utils import jsonable
from app.routers.chat_store import ensure_thread, get_connections
from app.routers.chat_runner import chat_events

logger = logging.getLogger(__name__)


async def enqueue_chat_job(request_id: str, thread_id: int) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                INSERT INTO chat_jobs (request_id, thread_id)
                VALUES (?, ?)
                """,
                (request_id, thread_id),
            )
            await db.commit()
            async with db.execute("SELECT last_insert_rowid()") as cur:
                job_id = int((await cur.fetchone())[0])
            return {"id": job_id, "status": "queued"}
        except aiosqlite.IntegrityError:
            async with db.execute(
                """
                SELECT id, status
                FROM chat_jobs
                WHERE request_id = ?
                """,
                (request_id,),
            ) as cur:
                row = await cur.fetchone()

    return {"id": row[0], "status": row[1]} if row else {"id": None, "status": "exists"}


async def recover_running_chat_jobs() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            UPDATE chat_jobs
            SET status = 'pending',
                locked_at = NULL,
                updated_at = datetime('now')
            WHERE status = 'running'
            """)

        await db.commit()
        return int(cur.rowcount or 0)


async def claim_next_chat_job() -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        await db.execute("BEGIN IMMEDIATE")

        async with db.execute("""
            SELECT id
            FROM chat_jobs
            WHERE status = 'pending'
            ORDER BY id
            LIMIT 1
            """) as cur:
            row = await cur.fetchone()

        if not row:
            await db.commit()
            return None

        job_id = int(row["id"])

        await db.execute(
            """
            UPDATE chat_jobs
            SET status = 'running',
                attempts = attempts + 1,
                locked_at = datetime('now'),
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (job_id,),
        )

        async with db.execute(
            """
            SELECT
                j.id,
                j.request_id,
                j.thread_id,
                j.attempts,
                m.id AS user_message_id,
                m.content AS message
            FROM chat_jobs j
            JOIN chat_messages m
              ON m.request_id = j.request_id
             AND m.role = 'user'
            WHERE j.id = ?
            """,
            (job_id,),
        ) as cur:
            job = await cur.fetchone()

        await db.commit()

    return dict(job) if job else None


async def complete_chat_job(request_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE chat_jobs
            SET status = 'completed',
                locked_at = NULL,
                updated_at = datetime('now')
            WHERE request_id = ?
            """,
            (request_id,),
        )
        await db.commit()


async def fail_chat_job(request_id: str, error: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE chat_jobs
            SET status = 'failed',
                error = ?,
                locked_at = NULL,
                updated_at = datetime('now')
            WHERE request_id = ?
            """,
            (error[:1000], request_id),
        )
        await db.commit()


async def append_chat_run_event(
    request_id: str,
    event: dict[str, Any],
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO chat_run_events (request_id, event_type, event_json)
            VALUES (?, ?, ?)
            """,
            (
                request_id,
                str(event.get("type") or "event"),
                json.dumps(jsonable(event), default=str),
            ),
        )
        await db.commit()


async def stream_chat_run_events(
    request_id: str,
    *,
    poll_interval: float = 0.5,
) -> AsyncIterator[dict[str, Any]]:
    last_event_id = 0

    while True:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                """
                SELECT id, event_type, event_json
                FROM chat_run_events
                WHERE request_id = ? AND id > ?
                ORDER BY id
                """,
                (request_id, last_event_id),
            )
            status_row = await (
                await db.execute(
                    """
                    SELECT status, error
                    FROM chat_jobs
                    WHERE request_id = ?
                    """,
                    (request_id,),
                )
            ).fetchone()

        for row in rows:
            last_event_id = int(row["id"])

            yield json.loads(row["event_json"])

        status = status_row["status"] if status_row else "missing"

        if status in {"completed", "failed", "missing"}:
            return

        await asyncio.sleep(poll_interval)


async def active_chat_jobs_for_thread(thread_id: int) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            """
            SELECT
                j.id,
                j.request_id,
                j.thread_id,
                j.status,
                j.created_at,
                j.updated_at,
                m.content AS message
            FROM chat_jobs j
            LEFT JOIN chat_messages m
              ON m.request_id = j.request_id
             AND m.role = 'user'
            WHERE j.thread_id = ?
              AND j.status IN ('pending', 'running')
            ORDER BY j.id
            """,
            (thread_id,),
        )

    return [dict(row) for row in rows]


async def build_prepared_chat_job(
    job: dict[str, Any],
) -> tuple[ChatRequest, dict[str, Any]]:
    request_id = str(job["request_id"])
    thread_id = int(job["thread_id"])
    user_message_id = int(job["user_message_id"])
    question = str(job["message"] or "")
    thread = await ensure_thread([], None, thread_id, question)
    connections = await get_connections(thread["connection_ids"])
    history = await _get_history_before_message(thread_id, user_message_id)

    return (
        ChatRequest(
            message=question,
            thread_id=thread_id,
            request_id=request_id,
        ),
        {
            "question": question,
            "thread": thread,
            "thread_id": thread_id,
            "connections": connections,
            "history": history,
        },
    )


async def run_chat_worker(poll_interval: float = 1.0) -> None:
    recovered = await recover_running_chat_jobs()

    if recovered:
        logger.info("Recovered %s running chat jobs", recovered)

    logger.info("Chat worker started")

    while True:
        job = await claim_next_chat_job()

        if not job:
            await asyncio.sleep(poll_interval)
            continue

        await _process_chat_job(job)


async def _process_chat_job(job: dict[str, Any]) -> None:
    request_id = str(job["request_id"])

    try:
        body, prepared = await build_prepared_chat_job(job)

        async for event in chat_events(body, prepared):
            await append_chat_run_event(request_id, event)

        await complete_chat_job(request_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("Chat job failed request_id=%s error=%s", request_id, exc)
        await fail_chat_job(request_id, str(exc))
        await append_chat_run_event(
            request_id,
            {
                "type": "error",
                "thread_id": job.get("thread_id"),
                "message": f"Chat failed: {exc}",
            },
        )


async def _get_history_before_message(
    thread_id: int,
    message_id: int,
    limit: int = 12,
) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            """
            SELECT role, content, payload, created_at
            FROM chat_messages
            WHERE thread_id = ? AND id < ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (thread_id, message_id, limit),
        )

    messages = [dict(row) for row in rows]

    messages.reverse()
    return messages
