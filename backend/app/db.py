import aiosqlite

from app.common.config import DB_PATH

_CONNECTIONS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS connections (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    slug       TEXT NOT NULL UNIQUE,
    plugin     TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_NOOP_MIGRATION_SQL = """
-- Retired migrations are intentionally no-op.
"""

_DROP_RETIRED_SCHEMA_SQL = """
DROP INDEX IF EXISTS idx_messaging_events_provider_message;
DROP INDEX IF EXISTS idx_messaging_conversations_config;
DROP INDEX IF EXISTS idx_messaging_events_conversation;
DROP INDEX IF EXISTS idx_messaging_jobs_status;
DROP INDEX IF EXISTS idx_chat_jobs_status;
DROP INDEX IF EXISTS idx_chat_run_events_request;
DROP INDEX IF EXISTS idx_chat_messages_thread_id;
DROP INDEX IF EXISTS idx_chat_messages_request_id;
DROP INDEX IF EXISTS idx_chat_threads_model_config_id;
DROP INDEX IF EXISTS idx_chat_thread_connections_connection_id;
DROP INDEX IF EXISTS idx_agent_prompts_key;
DROP INDEX IF EXISTS idx_semantic_tables_connection_status;
DROP INDEX IF EXISTS idx_semantic_columns_table_status;
DROP INDEX IF EXISTS idx_semantic_metrics_connection_status;
DROP INDEX IF EXISTS idx_semantic_relationships_from_status;
DROP INDEX IF EXISTS idx_semantic_relationships_to_status;
DROP INDEX IF EXISTS idx_semantic_ai_runs_created_at;
DROP INDEX IF EXISTS idx_semantic_ai_runs_status;

DROP TABLE IF EXISTS messaging_jobs;
DROP TABLE IF EXISTS messaging_events;
DROP TABLE IF EXISTS messaging_conversations;
DROP TABLE IF EXISTS messaging_configs;
DROP TABLE IF EXISTS chat_run_events;
DROP TABLE IF EXISTS chat_jobs;
DROP TABLE IF EXISTS chat_thread_connections;
DROP TABLE IF EXISTS chat_messages;
DROP TABLE IF EXISTS chat_requests;
DROP TABLE IF EXISTS chat_threads;
DROP TABLE IF EXISTS agent_prompts;
DROP TABLE IF EXISTS semantic_relationships;
DROP TABLE IF EXISTS semantic_metrics;
DROP TABLE IF EXISTS semantic_columns;
DROP TABLE IF EXISTS semantic_tables;
DROP TABLE IF EXISTS semantic_metadata;
DROP TABLE IF EXISTS semantic_ai_runs;
"""

_DROP_MODEL_SCHEMA_SQL = """
DROP TABLE IF EXISTS model_configs;
DROP TABLE IF EXISTS models;
"""

_OAUTH_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id                  TEXT PRIMARY KEY,
    client_name                TEXT,
    redirect_uris              TEXT NOT NULL,
    grant_types                TEXT NOT NULL,
    response_types             TEXT NOT NULL,
    scope                      TEXT NOT NULL,
    token_endpoint_auth_method TEXT NOT NULL DEFAULT 'none',
    created_at                 TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS oauth_authorization_codes (
    code_hash             TEXT PRIMARY KEY,
    client_id             TEXT NOT NULL,
    redirect_uri          TEXT NOT NULL,
    scope                 TEXT NOT NULL,
    resource              TEXT NOT NULL,
    code_challenge        TEXT NOT NULL,
    code_challenge_method TEXT NOT NULL,
    expires_at            INTEGER NOT NULL,
    consumed_at           TEXT,
    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (client_id) REFERENCES oauth_clients(client_id)
);
"""

_MIGRATIONS: list[str] = [
    _CONNECTIONS_SCHEMA_SQL,
    _NOOP_MIGRATION_SQL,
    _NOOP_MIGRATION_SQL,
    _NOOP_MIGRATION_SQL,
    _NOOP_MIGRATION_SQL,
    _NOOP_MIGRATION_SQL,
    _NOOP_MIGRATION_SQL,
    _NOOP_MIGRATION_SQL,
    _NOOP_MIGRATION_SQL,
    _NOOP_MIGRATION_SQL,
    _NOOP_MIGRATION_SQL,
    _NOOP_MIGRATION_SQL,
    _NOOP_MIGRATION_SQL,
    _NOOP_MIGRATION_SQL,
    _NOOP_MIGRATION_SQL,
    _DROP_RETIRED_SCHEMA_SQL,
    _DROP_MODEL_SCHEMA_SQL,
    _OAUTH_SCHEMA_SQL,
]


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        row = await (await db.execute("PRAGMA user_version")).fetchone()
        current_version: int = row[0]

        pending = _MIGRATIONS[current_version:]
        for i, sql in enumerate(pending, start=current_version + 1):
            await db.executescript(sql)
            # PRAGMA user_version cannot use parameterised queries.
            await db.execute(f"PRAGMA user_version = {i}")

        if pending:
            await db.commit()

        await _ensure_connections_schema(db)
        await _ensure_oauth_schema(db)
        await _drop_retired_schema(db)
        await _drop_model_schema(db)


async def _table_exists(db: aiosqlite.Connection, table_name: str) -> bool:
    row = await (
        await db.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table_name,),
        )
    ).fetchone()

    return row is not None


async def _ensure_connections_schema(db: aiosqlite.Connection) -> None:
    if await _table_exists(db, "connections"):
        return

    await db.executescript(_CONNECTIONS_SCHEMA_SQL)
    await db.commit()


async def _ensure_oauth_schema(db: aiosqlite.Connection) -> None:
    if await _table_exists(db, "oauth_clients") and await _table_exists(
        db,
        "oauth_authorization_codes",
    ):
        return

    await db.executescript(_OAUTH_SCHEMA_SQL)
    await db.commit()


async def _drop_retired_schema(db: aiosqlite.Connection) -> None:
    await db.execute("PRAGMA foreign_keys = OFF")
    await db.executescript(_DROP_RETIRED_SCHEMA_SQL)
    await db.commit()


async def _drop_model_schema(db: aiosqlite.Connection) -> None:
    await db.execute("PRAGMA foreign_keys = OFF")
    await db.executescript(_DROP_MODEL_SCHEMA_SQL)
    await db.commit()
