from typing import Any

import aiosqlite

from app.db import DB_PATH


async def enqueue_messaging_job(
    *,
    config_id: int,
    inbound_event_id: int,
    conversation_id: int | None,
) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                INSERT INTO messaging_jobs (
                    config_id,
                    inbound_event_id,
                    conversation_id
                )
                VALUES (?, ?, ?)
                """,
                (config_id, inbound_event_id, conversation_id),
            )
            await db.commit()
            async with db.execute("SELECT last_insert_rowid()") as cur:
                job_id = int((await cur.fetchone())[0])
            return {"id": job_id, "status": "queued"}
        except aiosqlite.IntegrityError:
            async with db.execute(
                """
                SELECT id, status
                FROM messaging_jobs
                WHERE inbound_event_id = ?
                """,
                (inbound_event_id,),
            ) as cur:
                row = await cur.fetchone()

    return {"id": row[0], "status": row[1]} if row else {"id": None, "status": "exists"}


async def recover_running_jobs() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            UPDATE messaging_jobs
            SET status = 'pending',
                locked_at = NULL,
                updated_at = datetime('now')
            WHERE status = 'running'
            """)
        await db.commit()
        return int(cur.rowcount or 0)


async def claim_next_job() -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")

        async with db.execute("""
            SELECT id
            FROM messaging_jobs
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
            UPDATE messaging_jobs
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
                j.config_id,
                j.inbound_event_id,
                j.conversation_id AS job_conversation_id,
                j.attempts,
                e.conversation_id AS event_conversation_id,
                e.provider_message_id,
                e.external_conversation_id,
                e.external_user_id,
                e.message_text,
                e.payload_json
            FROM messaging_jobs j
            JOIN messaging_events e ON e.id = j.inbound_event_id
            WHERE j.id = ?
            """,
            (job_id,),
        ) as cur:
            job = await cur.fetchone()

        await db.commit()

    return dict(job) if job else None


async def complete_job(job_id: int, conversation_id: int | None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE messaging_jobs
            SET status = 'completed',
                conversation_id = COALESCE(?, conversation_id),
                locked_at = NULL,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (conversation_id, job_id),
        )
        await db.commit()


async def fail_job(job_id: int, error: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE messaging_jobs
            SET status = 'failed',
                error = ?,
                locked_at = NULL,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (error[:1000], job_id),
        )
        await db.commit()


async def attach_job_conversation(job_id: int, conversation_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE messaging_jobs
            SET conversation_id = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (conversation_id, job_id),
        )
        await db.commit()
