import json

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

_MODELS_SCHEMA_SQL = """
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
"""

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

_SEMANTIC_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_semantic_tables_connection_status
    ON semantic_tables(connection_id, status, hidden, table_name);

CREATE INDEX IF NOT EXISTS idx_semantic_columns_table_status
    ON semantic_columns(semantic_table_id, status, hidden, column_name);

CREATE INDEX IF NOT EXISTS idx_semantic_metrics_connection_status
    ON semantic_metrics(connection_id, status, name);

CREATE INDEX IF NOT EXISTS idx_semantic_relationships_from_status
    ON semantic_relationships(from_connection_id, status);

CREATE INDEX IF NOT EXISTS idx_semantic_relationships_to_status
    ON semantic_relationships(to_connection_id, status);
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

_SEMANTIC_CONFIRM_DRAFTS_SQL = """
UPDATE semantic_tables
SET status = 'confirmed',
    updated_at = CURRENT_TIMESTAMP
WHERE status = 'draft';

UPDATE semantic_columns
SET status = 'confirmed',
    updated_at = CURRENT_TIMESTAMP
WHERE status = 'draft';
"""

_SEMANTIC_TYPE_CLEANUP_SQL = """
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
"""

_SEMANTIC_DELETE_SYSTEM_RELATIONSHIPS_SQL = """
DELETE FROM semantic_relationships
WHERE status = 'suggested'
  AND source = 'system';
"""

_NOOP_MIGRATION_SQL = """
-- Retired surface migrations are intentionally no-op.
"""

_MIGRATIONS: list[str] = [
    _CONNECTIONS_SCHEMA_SQL,
    _NOOP_MIGRATION_SQL,
    _MODELS_SCHEMA_SQL,
    _NOOP_MIGRATION_SQL,
    _NOOP_MIGRATION_SQL,
    _NOOP_MIGRATION_SQL,
    _SEMANTIC_SCHEMA_SQL,
    _SEMANTIC_CONFIRM_DRAFTS_SQL,
    _SEMANTIC_TYPE_CLEANUP_SQL,
    _SEMANTIC_DELETE_SYSTEM_RELATIONSHIPS_SQL,
    _NOOP_MIGRATION_SQL,
    _NOOP_MIGRATION_SQL,
    _NOOP_MIGRATION_SQL,
    _NOOP_MIGRATION_SQL,
    _SEMANTIC_AI_RUNS_SCHEMA_SQL,
]

_REMOVED_TABLES = (
    "messaging_jobs",
    "messaging_events",
    "messaging_conversations",
    "messaging_configs",
    "chat_run_events",
    "chat_jobs",
    "chat_thread_connections",
    "chat_messages",
    "chat_requests",
    "chat_threads",
    "agent_prompts",
)

_REMOVED_INDEXES = (
    "idx_messaging_events_provider_message",
    "idx_messaging_conversations_config",
    "idx_messaging_events_conversation",
    "idx_messaging_jobs_status",
    "idx_chat_jobs_status",
    "idx_chat_run_events_request",
    "idx_chat_messages_thread_id",
    "idx_chat_messages_request_id",
    "idx_chat_threads_model_config_id",
    "idx_chat_thread_connections_connection_id",
    "idx_agent_prompts_key",
)


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
        await _ensure_models_schema(db)
        await _ensure_semantic_schema(db)
        await _ensure_semantic_ai_runs_schema(db)
        await _drop_removed_surface_schema(db)


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


async def _ensure_connections_schema(db: aiosqlite.Connection) -> None:
    if await _table_exists(db, "connections"):
        return

    await db.executescript(_CONNECTIONS_SCHEMA_SQL)
    await db.commit()


async def _create_models_table(db: aiosqlite.Connection) -> None:
    await db.executescript(_MODELS_SCHEMA_SQL)


async def _ensure_models_schema(db: aiosqlite.Connection) -> None:
    has_models = await _table_exists(db, "models")
    has_model_configs = await _table_exists(db, "model_configs")

    if not has_models:
        await _create_models_table(db)

    if has_model_configs:
        await db.execute("PRAGMA foreign_keys = OFF")
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

    await db.execute("DELETE FROM models WHERE status = 'deleted'")
    await db.commit()


async def _ensure_semantic_ai_runs_schema(db: aiosqlite.Connection) -> None:
    ai_run_columns = await _table_columns(db, "semantic_ai_runs")

    if not ai_run_columns:
        await db.executescript(_SEMANTIC_AI_RUNS_SCHEMA_SQL)
        await db.commit()


async def _ensure_semantic_schema(db: aiosqlite.Connection) -> None:
    semantic_table_columns = await _table_columns(db, "semantic_tables")

    if not semantic_table_columns:
        await db.executescript(_SEMANTIC_SCHEMA_SQL)
        await db.executescript(_SEMANTIC_INDEX_SQL)
        await db.commit()
        return

    semantic_column_columns = await _table_columns(db, "semantic_columns")
    relationship_columns = await _table_columns(db, "semantic_relationships")
    metric_columns = await _table_columns(db, "semantic_metrics")

    if not semantic_column_columns or not relationship_columns or not metric_columns:
        await db.executescript(_SEMANTIC_SCHEMA_SQL)
        await db.executescript(_SEMANTIC_INDEX_SQL)
        await db.commit()
        return

    await db.executescript(_SEMANTIC_INDEX_SQL)

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
    await db.executescript(_SEMANTIC_INDEX_SQL)
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


async def _drop_removed_surface_schema(db: aiosqlite.Connection) -> None:
    existing_tables = [
        table for table in _REMOVED_TABLES if await _table_exists(db, table)
    ]

    if not existing_tables:
        return

    await db.execute("PRAGMA foreign_keys = OFF")

    for index_name in _REMOVED_INDEXES:
        await db.execute(f"DROP INDEX IF EXISTS {index_name}")

    for table_name in _REMOVED_TABLES:
        await db.execute(f"DROP TABLE IF EXISTS {table_name}")

    await db.commit()
