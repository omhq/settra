import json

import aiosqlite

from app.common.config import DB_PATH

_SEMANTIC_SCHEMA_SQL = """

CREATE TABLE IF NOT EXISTS semantic_tables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    connection_id INTEGER NOT NULL,
    source_name TEXT NOT NULL,
    schema_name TEXT NOT NULL,
    table_name TEXT NOT NULL,
    label TEXT,
    description TEXT,
    table_type TEXT,
    grain TEXT,
    primary_time_column TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    hidden INTEGER DEFAULT 0,
    status TEXT DEFAULT 'draft',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(connection_id) REFERENCES connections(id) ON DELETE CASCADE,
    UNIQUE(connection_id, schema_name, table_name)
);

CREATE TABLE IF NOT EXISTS semantic_columns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    semantic_table_id INTEGER NOT NULL,
    column_name TEXT NOT NULL,
    label TEXT,
    description TEXT,
    data_type TEXT,
    semantic_type TEXT,
    expression TEXT,
    unit TEXT,
    is_dimension INTEGER DEFAULT 0,
    is_measure INTEGER DEFAULT 0,
    is_time INTEGER DEFAULT 0,
    is_id INTEGER DEFAULT 0,
    is_foreign_key INTEGER DEFAULT 0,
    hidden INTEGER DEFAULT 0,
    status TEXT DEFAULT 'draft',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(semantic_table_id) REFERENCES semantic_tables(id) ON DELETE CASCADE,
    UNIQUE(semantic_table_id, column_name)
);

CREATE TABLE IF NOT EXISTS semantic_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_connection_id INTEGER NOT NULL,
    to_connection_id INTEGER NOT NULL,
    from_table_id INTEGER NOT NULL,
    from_column_id INTEGER NOT NULL,
    to_table_id INTEGER NOT NULL,
    to_column_id INTEGER NOT NULL,
    relationship_type TEXT NOT NULL,
    match_type TEXT NOT NULL,
    confidence REAL DEFAULT 0,
    status TEXT DEFAULT 'suggested',
    source TEXT DEFAULT 'system',
    validation_status TEXT DEFAULT 'valid',
    validation_note TEXT,
    evidence TEXT,
    rationale TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(from_connection_id) REFERENCES connections(id) ON DELETE CASCADE,
    FOREIGN KEY(to_connection_id) REFERENCES connections(id) ON DELETE CASCADE,
    FOREIGN KEY(from_table_id) REFERENCES semantic_tables(id) ON DELETE CASCADE,
    FOREIGN KEY(to_table_id) REFERENCES semantic_tables(id) ON DELETE CASCADE,
    FOREIGN KEY(from_column_id) REFERENCES semantic_columns(id) ON DELETE CASCADE,
    FOREIGN KEY(to_column_id) REFERENCES semantic_columns(id) ON DELETE CASCADE,
    UNIQUE(from_table_id, from_column_id, to_table_id, to_column_id)
);

CREATE TABLE IF NOT EXISTS semantic_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    connection_id INTEGER NOT NULL,
    semantic_table_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    label TEXT,
    expression TEXT NOT NULL,
    filters_json TEXT,
    time_column TEXT,
    unit TEXT,
    status TEXT DEFAULT 'draft',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(connection_id) REFERENCES connections(id) ON DELETE CASCADE,
    FOREIGN KEY(semantic_table_id) REFERENCES semantic_tables(id) ON DELETE CASCADE,
    UNIQUE(connection_id, name)
);
"""

_SEMANTIC_AI_RUNS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS semantic_ai_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed')),
    model_config_id INTEGER,
    model_snapshot_json TEXT NOT NULL DEFAULT '{}',
    connection_ids_json TEXT NOT NULL DEFAULT '[]',
    semantic_table_ids_json TEXT NOT NULL DEFAULT '[]',
    flows_json TEXT NOT NULL DEFAULT '[]',
    result_json TEXT,
    diagnostics_json TEXT,
    error TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    duration_ms REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_semantic_ai_runs_created_at
    ON semantic_ai_runs(created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_semantic_ai_runs_status
    ON semantic_ai_runs(status, created_at DESC);
"""

_MESSAGING_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS messaging_configs (
    id                              INTEGER PRIMARY KEY AUTOINCREMENT,
    name                            TEXT NOT NULL UNIQUE,
    provider                        TEXT NOT NULL,
    config_json                     TEXT NOT NULL DEFAULT '{}',
    encrypted_secrets               TEXT NOT NULL DEFAULT '',
    default_model_config_id          INTEGER NOT NULL,
    default_connection_ids_json      TEXT NOT NULL DEFAULT '[]',
    status                          TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive', 'deleted')),
    created_at                      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at                      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(default_model_config_id) REFERENCES models(id)
);

CREATE TABLE IF NOT EXISTS messaging_conversations (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id                   INTEGER NOT NULL,
    external_conversation_id    TEXT NOT NULL,
    external_user_id            TEXT,
    chat_thread_id              INTEGER NOT NULL,
    created_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(config_id) REFERENCES messaging_configs(id) ON DELETE CASCADE,
    FOREIGN KEY(chat_thread_id) REFERENCES chat_threads(id) ON DELETE CASCADE,
    UNIQUE(config_id, external_conversation_id)
);

CREATE TABLE IF NOT EXISTS messaging_events (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id                   INTEGER NOT NULL,
    conversation_id             INTEGER,
    direction                   TEXT NOT NULL
        CHECK (direction IN ('inbound', 'outbound')),
    provider_message_id         TEXT,
    external_conversation_id    TEXT NOT NULL,
    external_user_id            TEXT,
    message_text                TEXT NOT NULL,
    payload_json                TEXT NOT NULL DEFAULT '{}',
    status                      TEXT NOT NULL DEFAULT 'received'
        CHECK (status IN ('received', 'sent', 'failed')),
    error                       TEXT,
    created_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(config_id) REFERENCES messaging_configs(id) ON DELETE CASCADE,
    FOREIGN KEY(conversation_id) REFERENCES messaging_conversations(id)
        ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_messaging_events_provider_message
    ON messaging_events(config_id, direction, provider_message_id)
    WHERE provider_message_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_messaging_conversations_config
    ON messaging_conversations(config_id, external_conversation_id);

CREATE INDEX IF NOT EXISTS idx_messaging_events_conversation
    ON messaging_events(conversation_id, id);
"""

_MESSAGING_JOBS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS messaging_jobs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id           INTEGER NOT NULL,
    inbound_event_id    INTEGER NOT NULL UNIQUE,
    conversation_id     INTEGER,
    status              TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    attempts            INTEGER NOT NULL DEFAULT 0,
    locked_at           TEXT,
    error               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(config_id) REFERENCES messaging_configs(id) ON DELETE CASCADE,
    FOREIGN KEY(inbound_event_id) REFERENCES messaging_events(id) ON DELETE CASCADE,
    FOREIGN KEY(conversation_id) REFERENCES messaging_conversations(id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_messaging_jobs_status
    ON messaging_jobs(status, id);
"""

_CHAT_JOBS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chat_jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL UNIQUE,
    thread_id  INTEGER NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    attempts   INTEGER NOT NULL DEFAULT 0,
    locked_at  TEXT,
    error      TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(request_id) REFERENCES chat_requests(request_id) ON DELETE CASCADE,
    FOREIGN KEY(thread_id) REFERENCES chat_threads(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chat_run_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id  TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    event_json  TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(request_id) REFERENCES chat_requests(request_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chat_jobs_status
    ON chat_jobs(status, id);

CREATE INDEX IF NOT EXISTS idx_chat_run_events_request
    ON chat_run_events(request_id, id);
"""

_MIGRATIONS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS connections (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL,
        slug       TEXT NOT NULL UNIQUE,
        plugin     TEXT NOT NULL,
        status     TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_threads (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        connection_id INTEGER NOT NULL,
        title         TEXT NOT NULL,
        created_at    TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (connection_id) REFERENCES connections(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS chat_messages (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id  INTEGER NOT NULL,
        role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
        content    TEXT NOT NULL,
        payload    TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (thread_id) REFERENCES chat_threads(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_id
        ON chat_messages(thread_id, id);
    """,
    """
    CREATE TABLE IF NOT EXISTS models (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        name              TEXT NOT NULL,
        provider          TEXT NOT NULL,
        model             TEXT NOT NULL,
        config_json       TEXT NOT NULL DEFAULT '{}',
        encrypted_secrets TEXT NOT NULL DEFAULT '',
        status            TEXT NOT NULL DEFAULT 'active'
            CHECK (status IN ('active', 'deleted')),
        created_at        TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
    );

    ALTER TABLE chat_threads
        ADD COLUMN model_config_id INTEGER;

    ALTER TABLE chat_threads
        ADD COLUMN model_snapshot_json TEXT;

    ALTER TABLE chat_threads
        ADD COLUMN status TEXT NOT NULL DEFAULT 'active'
            CHECK (status IN ('active', 'inactive'));

    ALTER TABLE chat_threads
        ADD COLUMN inactive_reason TEXT;

    CREATE INDEX IF NOT EXISTS idx_chat_threads_model_config_id
        ON chat_threads(model_config_id);
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_requests (
        request_id TEXT PRIMARY KEY,
        thread_id  INTEGER,
        status     TEXT NOT NULL DEFAULT 'started'
            CHECK (status IN ('started', 'completed', 'failed')),
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (thread_id) REFERENCES chat_threads(id) ON DELETE CASCADE
    );

    ALTER TABLE chat_messages
        ADD COLUMN request_id TEXT;

    CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_messages_request_id
        ON chat_messages(request_id)
        WHERE request_id IS NOT NULL;
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_thread_connections (
        thread_id     INTEGER NOT NULL,
        connection_id INTEGER NOT NULL,
        position      INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (thread_id, connection_id),
        FOREIGN KEY (thread_id) REFERENCES chat_threads(id) ON DELETE CASCADE,
        FOREIGN KEY (connection_id) REFERENCES connections(id) ON DELETE CASCADE
    );

    INSERT OR IGNORE INTO chat_thread_connections
        (thread_id, connection_id, position)
    SELECT id, connection_id, 0
    FROM chat_threads;

    CREATE INDEX IF NOT EXISTS idx_chat_thread_connections_connection_id
        ON chat_thread_connections(connection_id);
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_prompts (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        prompt_key TEXT NOT NULL,
        role       TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant')),
        content    TEXT NOT NULL,
        position   INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (prompt_key, position)
    );

    CREATE INDEX IF NOT EXISTS idx_agent_prompts_key
        ON agent_prompts(prompt_key, position);
    """,
    _SEMANTIC_SCHEMA_SQL,
    """
    UPDATE semantic_tables
    SET status = 'confirmed',
        updated_at = CURRENT_TIMESTAMP
    WHERE status = 'draft';

    UPDATE semantic_columns
    SET status = 'confirmed',
        updated_at = CURRENT_TIMESTAMP
    WHERE status = 'draft';
    """,
    """
    UPDATE semantic_columns
    SET semantic_type = CASE
            WHEN lower(coalesce(data_type, '')) IN ('bool', 'boolean') THEN 'boolean'
            WHEN lower(coalesce(data_type, '')) LIKE '%json%' THEN 'json'
            WHEN lower(coalesce(data_type, '')) IN (
                'bigint',
                'decimal',
                'double precision',
                'integer',
                'numeric',
                'real',
                'smallint'
            ) THEN 'number'
            WHEN lower(coalesce(data_type, '')) = 'date'
                OR lower(coalesce(data_type, '')) LIKE '%time%' THEN 'timestamp'
            ELSE 'text'
        END,
        is_dimension = CASE
            WHEN lower(coalesce(data_type, '')) IN ('bool', 'boolean') THEN 1
            ELSE 0
        END,
        is_measure = CASE
            WHEN lower(coalesce(data_type, '')) IN (
                'bigint',
                'decimal',
                'double precision',
                'integer',
                'numeric',
                'real',
                'smallint'
            ) THEN 1
            ELSE 0
        END,
        is_time = CASE
            WHEN lower(coalesce(data_type, '')) = 'date'
                OR lower(coalesce(data_type, '')) LIKE '%time%' THEN 1
            ELSE 0
        END,
        is_id = 0,
        is_foreign_key = 0,
        updated_at = CURRENT_TIMESTAMP
    WHERE semantic_type IN ('email', 'domain')
      AND lower(coalesce(data_type, '')) NOT IN (
        'char',
        'character',
        'character varying',
        'citext',
        'text',
        'varchar'
      );

    DELETE FROM semantic_relationships
    WHERE status = 'suggested'
      AND match_type IN ('exact_email', 'exact_domain')
      AND (
        EXISTS (
            SELECT 1
            FROM semantic_columns c
            WHERE c.id = semantic_relationships.from_column_id
              AND lower(coalesce(c.data_type, '')) NOT IN (
                'char',
                'character',
                'character varying',
                'citext',
                'text',
                'varchar'
              )
        )
        OR EXISTS (
            SELECT 1
            FROM semantic_columns c
            WHERE c.id = semantic_relationships.to_column_id
              AND lower(coalesce(c.data_type, '')) NOT IN (
                'char',
                'character',
                'character varying',
                'citext',
                'text',
                'varchar'
              )
        )
      );
    """,
    """
    DELETE FROM semantic_relationships
    WHERE status = 'suggested'
      AND source = 'system';
    """,
    """
    ALTER TABLE chat_messages
        ADD COLUMN diagnostics_json TEXT;
    """,
    _MESSAGING_SCHEMA_SQL,
    _MESSAGING_JOBS_SCHEMA_SQL,
    _CHAT_JOBS_SCHEMA_SQL,
    _SEMANTIC_AI_RUNS_SCHEMA_SQL,
]


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        row = await (await db.execute("PRAGMA user_version")).fetchone()
        current_version: int = row[0]

        pending = _MIGRATIONS[current_version:]
        for i, sql in enumerate(pending, start=current_version + 1):
            await db.executescript(sql)
            # PRAGMA user_version cannot use parameterised queries
            await db.execute(f"PRAGMA user_version = {i}")

        if pending:
            await db.commit()

        await _ensure_models_schema(db)
        await _ensure_chat_schema(db)
        await _ensure_chat_job_schema(db)
        await _ensure_semantic_schema(db)
        await _ensure_semantic_ai_runs_schema(db)
        await _ensure_messaging_schema(db)


async def _table_columns(db: aiosqlite.Connection, table_name: str) -> set[str]:
    rows = await (await db.execute(f"PRAGMA table_info({table_name})")).fetchall()
    return {str(row[1]) for row in rows}


async def _ensure_columns(
    db: aiosqlite.Connection,
    table_name: str,
    existing_columns: set[str],
    columns: dict[str, str],
) -> set[str]:
    for column_name, definition in columns.items():
        if column_name in existing_columns:
            continue

        await db.execute(f"ALTER TABLE {table_name} ADD COLUMN {definition}")
        existing_columns.add(column_name)

    return existing_columns


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


async def _create_models_table(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS models (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            name              TEXT NOT NULL,
            provider          TEXT NOT NULL,
            model             TEXT NOT NULL,
            config_json       TEXT NOT NULL DEFAULT '{}',
            encrypted_secrets TEXT NOT NULL DEFAULT '',
            status            TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'deleted')),
            created_at        TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """)


async def _detach_deleted_models(
    db: aiosqlite.Connection,
    table_name: str,
) -> None:
    if await _table_exists(db, "chat_threads"):
        await db.execute(f"""
            UPDATE chat_threads
            SET status = 'inactive',
                inactive_reason = 'Model deleted',
                model_snapshot_json = NULL,
                model_config_id = NULL,
                updated_at = datetime('now')
            WHERE model_config_id IN (
                SELECT id
                FROM {table_name}
                WHERE status = 'deleted'
            )
            """)

    if await _table_exists(db, "messaging_configs"):
        await db.execute(f"""
            UPDATE messaging_configs
            SET status = 'inactive',
                updated_at = datetime('now')
            WHERE default_model_config_id IN (
                SELECT id
                FROM {table_name}
                WHERE status = 'deleted'
            )
              AND status = 'active'
            """)


async def _ensure_models_schema(db: aiosqlite.Connection) -> None:
    has_models = await _table_exists(db, "models")
    has_model_configs = await _table_exists(db, "model_configs")

    if not has_models and not has_model_configs:
        return

    await db.execute("PRAGMA foreign_keys = OFF")

    if not has_models:
        await _create_models_table(db)

    if has_model_configs:
        await _detach_deleted_models(db, "model_configs")
        await db.execute("""
            INSERT OR IGNORE INTO models (
                id,
                name,
                provider,
                model,
                config_json,
                encrypted_secrets,
                status,
                created_at,
                updated_at
            )
            SELECT
                id,
                name,
                provider,
                model,
                config_json,
                encrypted_secrets,
                status,
                created_at,
                updated_at
            FROM model_configs
            WHERE status != 'deleted'
            """)
        await db.execute("DROP TABLE model_configs")

    await _detach_deleted_models(db, "models")
    await db.execute("DELETE FROM models WHERE status = 'deleted'")
    await db.commit()


async def _ensure_chat_schema(db: aiosqlite.Connection) -> None:
    chat_message_columns = await _table_columns(db, "chat_messages")

    if not chat_message_columns:
        return

    await _ensure_columns(
        db,
        "chat_messages",
        chat_message_columns,
        {
            "diagnostics_json": "diagnostics_json TEXT",
        },
    )
    await db.commit()


async def _ensure_chat_job_schema(db: aiosqlite.Connection) -> None:
    chat_job_columns = await _table_columns(db, "chat_jobs")

    if not chat_job_columns:
        await db.executescript(_CHAT_JOBS_SCHEMA_SQL)
        await db.commit()


async def _ensure_semantic_ai_runs_schema(db: aiosqlite.Connection) -> None:
    ai_run_columns = await _table_columns(db, "semantic_ai_runs")

    if not ai_run_columns:
        await db.executescript(_SEMANTIC_AI_RUNS_SCHEMA_SQL)
        await db.commit()


async def _messaging_configs_references_old_model_table(
    db: aiosqlite.Connection,
) -> bool:
    rows = await (
        await db.execute("PRAGMA foreign_key_list(messaging_configs)")
    ).fetchall()

    return any(str(row[2]) == "model_configs" for row in rows)


async def _ensure_messaging_model_fk(db: aiosqlite.Connection) -> None:
    if not await _messaging_configs_references_old_model_table(db):
        return

    await db.execute("PRAGMA foreign_keys = OFF")
    await db.executescript("""
        CREATE TABLE messaging_configs_rebuilt (
            id                              INTEGER PRIMARY KEY AUTOINCREMENT,
            name                            TEXT NOT NULL UNIQUE,
            provider                        TEXT NOT NULL,
            config_json                     TEXT NOT NULL DEFAULT '{}',
            encrypted_secrets               TEXT NOT NULL DEFAULT '',
            default_model_config_id          INTEGER NOT NULL,
            default_connection_ids_json      TEXT NOT NULL DEFAULT '[]',
            status                          TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'inactive', 'deleted')),
            created_at                      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at                      TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(default_model_config_id) REFERENCES models(id)
        );

        INSERT INTO messaging_configs_rebuilt (
            id,
            name,
            provider,
            config_json,
            encrypted_secrets,
            default_model_config_id,
            default_connection_ids_json,
            status,
            created_at,
            updated_at
        )
        SELECT
            id,
            name,
            provider,
            config_json,
            encrypted_secrets,
            default_model_config_id,
            default_connection_ids_json,
            status,
            created_at,
            updated_at
        FROM messaging_configs;

        DROP TABLE messaging_configs;
        ALTER TABLE messaging_configs_rebuilt RENAME TO messaging_configs;
        """)
    await db.commit()


async def _ensure_messaging_schema(db: aiosqlite.Connection) -> None:
    messaging_config_columns = await _table_columns(db, "messaging_configs")

    if not messaging_config_columns:
        await db.executescript(_MESSAGING_SCHEMA_SQL)
        await db.executescript(_MESSAGING_JOBS_SCHEMA_SQL)
        await db.commit()
        return

    await _ensure_messaging_model_fk(db)

    messaging_job_columns = await _table_columns(db, "messaging_jobs")

    if not messaging_job_columns:
        await db.executescript(_MESSAGING_JOBS_SCHEMA_SQL)
        await db.commit()


async def _ensure_semantic_schema(db: aiosqlite.Connection) -> None:
    semantic_table_columns = await _table_columns(db, "semantic_tables")

    if not semantic_table_columns:
        await db.executescript(_SEMANTIC_SCHEMA_SQL)
        await db.commit()
        return

    semantic_column_columns = await _table_columns(db, "semantic_columns")
    relationship_columns = await _table_columns(db, "semantic_relationships")
    metric_columns = await _table_columns(db, "semantic_metrics")

    if not semantic_column_columns or not relationship_columns or not metric_columns:
        await db.executescript(_SEMANTIC_SCHEMA_SQL)
        await db.commit()
        return

    relationship_columns = await _ensure_columns(
        db,
        "semantic_relationships",
        relationship_columns,
        {
            "validation_status": "validation_status TEXT DEFAULT 'valid'",
            "validation_note": "validation_note TEXT",
            "evidence": "evidence TEXT",
            "rationale": "rationale TEXT",
        },
    )
    semantic_table_columns = await _ensure_columns(
        db,
        "semantic_tables",
        semantic_table_columns,
        {
            "metadata_json": "metadata_json TEXT NOT NULL DEFAULT '{}'",
        },
    )
    await _migrate_semantic_table_metadata(db, semantic_table_columns)
    await db.commit()

    needs_rebuild = (
        "workspace_id" in semantic_table_columns
        or "header_row" in semantic_table_columns
        or "workspace_id" in relationship_columns
        or "workspace_id" in metric_columns
        or "updated_at" not in semantic_column_columns
    )

    if not needs_rebuild:
        return

    await db.executescript("""
        DROP TABLE IF EXISTS semantic_relationships_legacy;
        DROP TABLE IF EXISTS semantic_metrics_legacy;
        DROP TABLE IF EXISTS semantic_columns_legacy;
        DROP TABLE IF EXISTS semantic_tables_legacy;

        ALTER TABLE semantic_relationships RENAME TO semantic_relationships_legacy;
        ALTER TABLE semantic_metrics RENAME TO semantic_metrics_legacy;
        ALTER TABLE semantic_columns RENAME TO semantic_columns_legacy;
        ALTER TABLE semantic_tables RENAME TO semantic_tables_legacy;
        """)
    await db.executescript(_SEMANTIC_SCHEMA_SQL)
    await db.executescript("""
        INSERT OR IGNORE INTO semantic_tables (
            id,
            connection_id,
            source_name,
            schema_name,
            table_name,
            label,
            description,
            table_type,
            grain,
            primary_time_column,
            metadata_json,
            hidden,
            status,
            created_at,
            updated_at
        )
        SELECT
            id,
            connection_id,
            source_name,
            schema_name,
            table_name,
            label,
            description,
            table_type,
            grain,
            primary_time_column,
            metadata_json,
            hidden,
            status,
            created_at,
            updated_at
        FROM semantic_tables_legacy;

        INSERT OR IGNORE INTO semantic_columns (
            id,
            semantic_table_id,
            column_name,
            label,
            description,
            data_type,
            semantic_type,
            expression,
            unit,
            is_dimension,
            is_measure,
            is_time,
            is_id,
            is_foreign_key,
            hidden,
            status,
            created_at,
            updated_at
        )
        SELECT
            id,
            semantic_table_id,
            column_name,
            label,
            description,
            data_type,
            semantic_type,
            expression,
            unit,
            is_dimension,
            is_measure,
            is_time,
            is_id,
            is_foreign_key,
            hidden,
            status,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM semantic_columns_legacy;

        INSERT OR IGNORE INTO semantic_relationships (
            id,
            from_connection_id,
            to_connection_id,
            from_table_id,
            from_column_id,
            to_table_id,
            to_column_id,
            relationship_type,
            match_type,
            confidence,
            status,
            source,
            validation_status,
            validation_note,
            evidence,
            rationale,
            created_at,
            updated_at
        )
        SELECT
            id,
            from_connection_id,
            to_connection_id,
            from_table_id,
            from_column_id,
            to_table_id,
            to_column_id,
            relationship_type,
            match_type,
            confidence,
            status,
            source,
            validation_status,
            validation_note,
            evidence,
            rationale,
            created_at,
            updated_at
        FROM semantic_relationships_legacy;

        INSERT OR IGNORE INTO semantic_metrics (
            id,
            connection_id,
            semantic_table_id,
            name,
            label,
            expression,
            filters_json,
            time_column,
            unit,
            status,
            created_at,
            updated_at
        )
        SELECT
            id,
            connection_id,
            semantic_table_id,
            name,
            label,
            expression,
            filters_json,
            time_column,
            unit,
            status,
            created_at,
            updated_at
        FROM semantic_metrics_legacy;

        DROP TABLE semantic_relationships_legacy;
        DROP TABLE semantic_metrics_legacy;
        DROP TABLE semantic_columns_legacy;
        DROP TABLE semantic_tables_legacy;
        """)
    await db.commit()


async def _migrate_semantic_table_metadata(
    db: aiosqlite.Connection,
    semantic_table_columns: set[str],
) -> None:
    if "header_row" not in semantic_table_columns:
        return

    rows = await (await db.execute("""
            SELECT id, header_row, metadata_json
            FROM semantic_tables
            WHERE header_row IS NOT NULL
            """)).fetchall()

    for table_id, header_row, metadata_json in rows:
        try:
            metadata = json.loads(metadata_json or "{}")
        except json.JSONDecodeError:
            metadata = {}

        if not isinstance(metadata, dict) or metadata.get("header_row") is not None:
            continue

        metadata["header_row"] = int(header_row)
        await db.execute(
            """
            UPDATE semantic_tables
            SET metadata_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (json.dumps(metadata), table_id),
        )
