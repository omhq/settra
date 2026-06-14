import json

from typing import Any

import aiosqlite

from fastapi import HTTPException

from app.db import DB_PATH
from app.model_configs import (
    ModelConfigError,
    get_model_config,
    load_model_from_snapshot,
    snapshot_model_config,
)
from app.schemas import ChatRequest
from app.utils import jsonable, parse_json_payload


def message_response(row: aiosqlite.Row) -> dict[str, Any]:
    data = dict(row)
    data["payload"] = parse_json_payload(data.get("payload"))
    data["diagnostics"] = parse_json_payload(data.pop("diagnostics_json", None))

    return data


def normalise_connection_ids(body: ChatRequest) -> list[int]:
    raw_ids = body.connection_ids

    if raw_ids is None:
        raw_ids = [body.connection_id] if body.connection_id is not None else []

    seen: set[int] = set()
    connection_ids: list[int] = []

    for connection_id in raw_ids:
        if connection_id is None:
            continue
        if connection_id not in seen:
            seen.add(connection_id)
            connection_ids.append(connection_id)

    return connection_ids


def connection_summary(connections: list[dict[str, Any]]) -> dict[str, Any]:
    connection_ids = [connection["id"] for connection in connections]

    if not connections:
        return {
            "connection_ids": [],
            "connections": [],
            "connection_name": None,
            "connection_plugin": None,
        }

    if len(connections) == 1:
        return {
            "connection_ids": connection_ids,
            "connections": connections,
            "connection_name": connections[0].get("name"),
            "connection_plugin": connections[0].get("plugin"),
        }

    return {
        "connection_ids": connection_ids,
        "connections": connections,
        "connection_name": f"{len(connections)} connections",
        "connection_plugin": ", ".join(
            sorted(
                {
                    connection["plugin"]
                    for connection in connections
                    if connection.get("plugin")
                }
            )
        ),
    }


async def connection_rows_by_thread(
    db: aiosqlite.Connection,
    thread_ids: list[int],
) -> dict[int, list[dict[str, Any]]]:
    if not thread_ids:
        return {}

    placeholders = ", ".join("?" for _ in thread_ids)

    async with db.execute(
        f"""
        SELECT
            tc.thread_id,
            tc.connection_id,
            c.name,
            c.plugin,
            c.status
        FROM chat_thread_connections tc
        LEFT JOIN connections c ON c.id = tc.connection_id
        WHERE tc.thread_id IN ({placeholders})
        ORDER BY tc.thread_id, tc.position, tc.connection_id
        """,
        thread_ids,
    ) as cur:
        rows = await cur.fetchall()

    by_thread: dict[int, list[dict[str, Any]]] = {
        thread_id: [] for thread_id in thread_ids
    }

    for row in rows:
        by_thread[row["thread_id"]].append(
            {
                "id": row["connection_id"],
                "name": row["name"],
                "plugin": row["plugin"],
                "status": row["status"] or "missing",
            }
        )

    return by_thread


def thread_response(
    row: aiosqlite.Row,
    connections: list[dict[str, Any]],
) -> dict[str, Any]:
    data = dict(row)

    data.update(connection_summary(connections))

    if not data["connection_ids"] and data.get("connection_id"):
        data["connection_ids"] = [data["connection_id"]]

    return data


async def list_thread_summaries() -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("""
            SELECT
                t.id,
                t.title,
                t.connection_id,
                t.model_config_id,
                t.status,
                t.inactive_reason,
                t.created_at,
                t.updated_at,
                m.name AS model_name,
                m.model AS model,
                (
                    SELECT content
                    FROM chat_messages
                    WHERE thread_id = t.id
                    ORDER BY id DESC
                    LIMIT 1
                ) AS last_message
            FROM chat_threads t
            LEFT JOIN model_configs m ON m.id = t.model_config_id
            ORDER BY datetime(t.updated_at) DESC, t.id DESC
            """) as cur:
            rows = await cur.fetchall()

        connection_rows = await connection_rows_by_thread(
            db,
            [row["id"] for row in rows],
        )

    return [thread_response(row, connection_rows.get(row["id"], [])) for row in rows]


async def get_thread_detail(thread_id: int) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            """
            SELECT
                t.id,
                t.title,
                t.connection_id,
                t.model_config_id,
                t.status,
                t.inactive_reason,
                t.created_at,
                t.updated_at,
                m.name AS model_name,
                m.model AS model,
                m.status AS model_status
            FROM chat_threads t
            LEFT JOIN model_configs m ON m.id = t.model_config_id
            WHERE t.id = ?
            """,
            (thread_id,),
        ) as cur:
            thread = await cur.fetchone()

        if not thread:
            raise HTTPException(404, "Chat thread not found")

        connection_rows = await connection_rows_by_thread(db, [thread_id])

        async with db.execute(
            """
            SELECT id, role, content, payload, request_id, diagnostics_json, created_at
            FROM chat_messages
            WHERE thread_id = ?
            ORDER BY id ASC
            """,
            (thread_id,),
        ) as cur:
            messages = await cur.fetchall()

    return {
        "thread": thread_response(thread, connection_rows.get(thread_id, [])),
        "messages": [message_response(message) for message in messages],
    }


async def delete_thread_record(thread_id: int) -> None:
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

        cur = await db.execute(
            "DELETE FROM chat_threads WHERE id = ?",
            (thread_id,),
        )

        await db.commit()

    if cur.rowcount == 0:
        raise HTTPException(404, "Chat thread not found")


async def clear_thread_messages(thread_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            "SELECT id FROM chat_threads WHERE id = ?",
            (thread_id,),
        ) as cur:
            thread = await cur.fetchone()

        if not thread:
            raise HTTPException(404, "Chat thread not found")

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


async def get_connections(connection_ids: list[int]) -> list[dict[str, Any]]:
    if not connection_ids:
        raise HTTPException(400, "At least one connection is required")

    placeholders = ", ".join("?" for _ in connection_ids)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            f"""
            SELECT id, name, slug, plugin, status
            FROM connections
            WHERE id IN ({placeholders})
            """,
            connection_ids,
        ) as cur:
            rows = await cur.fetchall()

    by_id = {row["id"]: dict(row) for row in rows}
    missing = [
        connection_id for connection_id in connection_ids if connection_id not in by_id
    ]

    if missing:
        raise HTTPException(404, "Connection not found")

    ordered = [by_id[connection_id] for connection_id in connection_ids]
    inactive = [
        connection for connection in ordered if connection["status"] != "active"
    ]

    if inactive:
        names = ", ".join(connection["name"] for connection in inactive)

        raise HTTPException(409, f"Connection is not active: {names}")

    return ordered


async def get_thread_connection_ids(
    db: aiosqlite.Connection,
    thread_id: int,
    legacy_connection_id: int | None,
) -> list[int]:
    async with db.execute(
        """
        SELECT connection_id
        FROM chat_thread_connections
        WHERE thread_id = ?
        ORDER BY position, connection_id
        """,
        (thread_id,),
    ) as cur:
        rows = await cur.fetchall()

    connection_ids = [row["connection_id"] for row in rows]

    if connection_ids or legacy_connection_id is None:
        return connection_ids

    await db.execute(
        """
        INSERT OR IGNORE INTO chat_thread_connections
            (thread_id, connection_id, position)
        VALUES (?, ?, 0)
        """,
        (thread_id, legacy_connection_id),
    )
    await db.commit()
    return [legacy_connection_id]


async def ensure_thread(
    connection_ids: list[int],
    model_config_id: int | None,
    thread_id: int | None,
    title: str,
) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        if thread_id is not None:
            async with db.execute(
                """
                SELECT
                    id,
                    connection_id,
                    model_config_id,
                    model_snapshot_json,
                    status,
                    inactive_reason
                FROM chat_threads
                WHERE id = ?
                """,
                (thread_id,),
            ) as cur:
                row = await cur.fetchone()

            if not row:
                raise HTTPException(404, "Chat thread not found")

            persisted_connection_ids = await get_thread_connection_ids(
                db,
                thread_id,
                row["connection_id"],
            )

            if connection_ids and set(connection_ids) != set(persisted_connection_ids):
                raise HTTPException(
                    409, "Connections cannot be changed after chat starts"
                )

            if row["status"] != "active":
                reason = row["inactive_reason"] or "Chat is inactive"

                raise HTTPException(409, reason)

            if (
                model_config_id is not None
                and row["model_config_id"] != model_config_id
            ):
                raise HTTPException(409, "Model cannot be changed after chat starts")

            model_config = await get_model_config(
                row["model_config_id"],
                allow_deleted=True,
            )

            if not model_config or model_config["status"] != "active":
                await db.execute(
                    """
                    UPDATE chat_threads
                    SET status = 'inactive',
                        inactive_reason = 'Model deleted',
                        model_snapshot_json = NULL,
                        updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (thread_id,),
                )
                await db.commit()
                raise HTTPException(409, "Model deleted")

            try:
                model_snapshot = load_model_from_snapshot(row["model_snapshot_json"])
            except ModelConfigError as exc:
                raise HTTPException(409, str(exc)) from exc

            return {
                "id": thread_id,
                "model": model_snapshot,
                "connection_ids": persisted_connection_ids,
            }

        if model_config_id is None:
            raise HTTPException(400, "Model is required to start a chat")
        if not connection_ids:
            raise HTTPException(400, "At least one connection is required")

        model_config = await get_model_config(model_config_id, include_secrets=True)

        if not model_config:
            raise HTTPException(404, "Model not found")

        model_snapshot = snapshot_model_config(model_config)

        await db.execute(
            """
            INSERT INTO chat_threads
                (connection_id, model_config_id, model_snapshot_json, title)
            VALUES (?, ?, ?, ?)
            """,
            (
                connection_ids[0],
                model_config_id,
                json.dumps(model_snapshot, sort_keys=True),
                title[:80] or "New chat",
            ),
        )
        await db.commit()
        async with db.execute("SELECT last_insert_rowid()") as cur:
            new_thread_id = (await cur.fetchone())[0]

        await db.executemany(
            """
            INSERT INTO chat_thread_connections
                (thread_id, connection_id, position)
            VALUES (?, ?, ?)
            """,
            [
                (new_thread_id, connection_id, position)
                for position, connection_id in enumerate(connection_ids)
            ],
        )
        await db.commit()

    model_snapshot["secrets"] = model_config.get("secrets", {})

    return {
        "id": new_thread_id,
        "model": model_snapshot,
        "connection_ids": connection_ids,
    }


async def get_history(thread_id: int, limit: int = 12) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            """
            SELECT role, content, payload, created_at
            FROM chat_messages
            WHERE thread_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (thread_id, limit),
        ) as cur:
            rows = await cur.fetchall()

    messages = [dict(row) for row in rows]

    messages.reverse()
    return messages


async def insert_message(
    thread_id: int,
    role: str,
    content: str,
    payload: dict[str, Any] | None = None,
    request_id: str | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO chat_messages (
                thread_id,
                role,
                content,
                payload,
                request_id,
                diagnostics_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                thread_id,
                role,
                content,
                json.dumps(jsonable(payload), default=str) if payload else None,
                request_id,
                json.dumps(jsonable(diagnostics), default=str) if diagnostics else None,
            ),
        )
        await db.execute(
            "UPDATE chat_threads SET updated_at = datetime('now') WHERE id = ?",
            (thread_id,),
        )
        await db.commit()


async def set_thread_title(thread_id: int, title: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE chat_threads
            SET title = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (title[:80] or "New chat", thread_id),
        )
        await db.commit()


async def reserve_request(request_id: str | None) -> None:
    if not request_id:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                INSERT INTO chat_requests (request_id, status)
                VALUES (?, 'started')
                """,
                (request_id,),
            )
            await db.commit()
        except aiosqlite.IntegrityError as exc:
            raise HTTPException(409, "Duplicate chat request ignored") from exc


async def attach_request_thread(request_id: str | None, thread_id: int) -> None:
    if not request_id:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE chat_requests
            SET thread_id = ?, updated_at = datetime('now')
            WHERE request_id = ?
            """,
            (thread_id, request_id),
        )
        await db.commit()


async def finish_request(request_id: str | None, status: str) -> None:
    if not request_id:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE chat_requests
            SET status = ?, updated_at = datetime('now')
            WHERE request_id = ?
            """,
            (status, request_id),
        )
        await db.commit()
