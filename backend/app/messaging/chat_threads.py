import aiosqlite

from app.db import DB_PATH
from app.routers.chat_store import ensure_thread


async def create_chat_thread(config: dict, title: str) -> int:
    thread = await ensure_thread(
        config["connection_ids"],
        config["model_config_id"],
        None,
        title,
    )
    return int(thread["id"])


async def clear_chat_thread(thread_id: int) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM chat_threads WHERE id = ?",
            (thread_id,),
        ) as cur:
            thread = await cur.fetchone()

        if not thread:
            return None

        cur = await db.execute(
            "DELETE FROM chat_messages WHERE thread_id = ?",
            (thread_id,),
        )
        await db.execute(
            "DELETE FROM chat_requests WHERE thread_id = ?",
            (thread_id,),
        )
        await db.execute(
            """
            UPDATE chat_threads
            SET title = 'New chat',
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (thread_id,),
        )
        await db.commit()

    return int(cur.rowcount or 0)


async def delete_chat_thread(thread_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM chat_messages WHERE thread_id = ?",
            (thread_id,),
        )
        await db.execute(
            "DELETE FROM chat_requests WHERE thread_id = ?",
            (thread_id,),
        )
        await db.execute(
            "DELETE FROM chat_thread_connections WHERE thread_id = ?",
            (thread_id,),
        )
        await db.execute(
            "DELETE FROM chat_threads WHERE id = ?",
            (thread_id,),
        )
        await db.commit()
