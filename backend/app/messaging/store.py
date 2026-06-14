import json

from typing import Any

import aiosqlite

from app.db import DB_PATH
from app.messaging.base import IncomingMessage
from app.utils import jsonable


async def get_conversation(
    config_id: int,
    external_conversation_id: str,
) -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, chat_thread_id
            FROM messaging_conversations
            WHERE config_id = ? AND external_conversation_id = ?
            """,
            (config_id, external_conversation_id),
        ) as cur:
            row = await cur.fetchone()

    return dict(row) if row else None


async def create_conversation(
    *,
    config_id: int,
    external_conversation_id: str,
    external_user_id: str | None,
    chat_thread_id: int,
) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO messaging_conversations (
                config_id,
                external_conversation_id,
                external_user_id,
                chat_thread_id
            )
            VALUES (?, ?, ?, ?)
            """,
            (config_id, external_conversation_id, external_user_id, chat_thread_id),
        )
        await db.commit()
        async with db.execute("SELECT last_insert_rowid()") as cur:
            conversation_id = (await cur.fetchone())[0]

    return {"id": conversation_id, "chat_thread_id": chat_thread_id}


async def set_conversation_thread(
    *,
    conversation_id: int,
    external_user_id: str | None,
    chat_thread_id: int,
) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE messaging_conversations
            SET external_user_id = COALESCE(?, external_user_id),
                chat_thread_id = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (external_user_id, chat_thread_id, conversation_id),
        )
        await db.commit()

    return {"id": conversation_id, "chat_thread_id": chat_thread_id}


async def delete_conversation(conversation_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE messaging_events
            SET conversation_id = NULL
            WHERE conversation_id = ?
            """,
            (conversation_id,),
        )
        await db.execute(
            """
            UPDATE messaging_jobs
            SET conversation_id = NULL
            WHERE conversation_id = ?
            """,
            (conversation_id,),
        )
        await db.execute(
            """
            DELETE FROM messaging_conversations
            WHERE id = ?
            """,
            (conversation_id,),
        )
        await db.commit()


async def record_inbound_event(
    *,
    config_id: int,
    conversation_id: int | None,
    message: IncomingMessage,
) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                INSERT INTO messaging_events (
                    config_id,
                    conversation_id,
                    direction,
                    provider_message_id,
                    external_conversation_id,
                    external_user_id,
                    message_text,
                    payload_json,
                    status
                )
                VALUES (?, ?, 'inbound', ?, ?, ?, ?, ?, 'received')
                """,
                (
                    config_id,
                    conversation_id,
                    message.external_message_id,
                    message.conversation_id,
                    message.sender_id,
                    message.text,
                    json.dumps(jsonable(message.raw), default=str),
                ),
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            return None

        async with db.execute("SELECT last_insert_rowid()") as cur:
            return int((await cur.fetchone())[0])


async def record_outbound_event(
    *,
    config_id: int,
    conversation_id: int | None,
    to: str,
    text: str,
    payload: dict[str, Any],
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO messaging_events (
                config_id,
                conversation_id,
                direction,
                external_conversation_id,
                message_text,
                payload_json,
                status
            )
            VALUES (?, ?, 'outbound', ?, ?, ?, 'sent')
            """,
            (
                config_id,
                conversation_id,
                to,
                text,
                json.dumps(jsonable(payload), default=str),
            ),
        )

        if conversation_id is not None:
            await db.execute(
                """
                UPDATE messaging_conversations
                SET updated_at = datetime('now')
                WHERE id = ?
                """,
                (conversation_id,),
            )

        await db.commit()


async def attach_event_conversation(event_id: int, conversation_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE messaging_events
            SET conversation_id = ?
            WHERE id = ?
            """,
            (conversation_id, event_id),
        )
        await db.commit()


async def mark_event_failed(event_id: int, error: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE messaging_events
            SET status = 'failed',
                error = ?
            WHERE id = ?
            """,
            (error[:1000], event_id),
        )
        await db.commit()
