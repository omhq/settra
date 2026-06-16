import os
import re
import json
import logging

from pathlib import Path
from typing import Any

import yaml
import aiosqlite

from app.common.config import CONFIG_DIR
from app.db import DB_PATH
from app.connector_prompts import connector_prompt_snippets
from app.semantic.consts import SEMANTIC_DIR, SEMANTICS_PATH
from app.semantic.utils import (
    format_semantic_contract,
    infer_column_semantics,
    infer_table_semantics,
    is_ignored_column,
    is_text_data_type,
    semantic_rules,
)

logger = logging.getLogger(__name__)


def _semantic_dir() -> Path:
    if SEMANTIC_DIR:
        return Path(SEMANTIC_DIR)

    config_path = Path(SEMANTICS_PATH)

    if config_path.exists():
        return config_path

    return Path(__file__).resolve().parents[3] / "semantic"


def _connectors_dir() -> Path:
    configured = os.getenv("CONNECTORS_DIR")

    if configured:
        return Path(configured)

    config_path = CONFIG_DIR / "connectors"

    if config_path.exists():
        return config_path

    return Path(__file__).resolve().parents[3] / "connectors"


def _semantic_files() -> list[Path]:
    connectors_dir = _connectors_dir()
    connector_files: list[Path] = []

    if connectors_dir.exists():
        connector_files = sorted(
            [
                *(connectors_dir.glob("*/semantics.yaml")),
                *(connectors_dir.glob("*/semantics.yml")),
            ]
        )

    if connector_files:
        return connector_files

    semantic_dir = _semantic_dir()

    return sorted(
        [
            *(semantic_dir.glob("*.yaml")),
            *(semantic_dir.glob("*.yml")),
        ]
    )


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, list):
        values = value
    else:
        return []

    return [
        str(item).strip()
        for item in values
        if isinstance(item, str) and str(item).strip()
    ]


def ignored_column_postfixes_for_plugin(plugin: str) -> list[str]:
    for yaml_file in _semantic_files():
        data = yaml.safe_load(yaml_file.read_text())

        if not isinstance(data, dict) or data.get("plugin") != plugin:
            continue

        return _normalize_string_list(data.get("ignored_column_postfixes"))

    return []


async def load_semantic_layer() -> dict[str, int]:
    """Load connector semantic YAML files into SQLite and return table counts."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS semantic_metadata (
                plugin      TEXT,
                table_name  TEXT,
                content     JSON,
                PRIMARY KEY (plugin, table_name)
            )
        """)

        semantic_files = _semantic_files()
        loaded_plugins: set[str] = set()
        loaded_counts: dict[str, int] = {}

        for yaml_file in semantic_files:
            data = yaml.safe_load(yaml_file.read_text())

            if not isinstance(data, dict):
                logger.warning(f"Skipping invalid semantic file path={yaml_file}")
                continue

            plugin = data.get("plugin")
            tables = data.get("tables")

            if not isinstance(plugin, str) or not isinstance(tables, dict):
                logger.warning(
                    f"Skipping semantic file with missing "
                    f"plugin/tables path={yaml_file}"
                )
                continue

            if plugin not in loaded_plugins:
                await db.execute(
                    "DELETE FROM semantic_metadata WHERE plugin = ?",
                    (plugin,),
                )
                loaded_plugins.add(plugin)

                loaded_counts[plugin] = 0

            for table_name, meta in tables.items():
                if not isinstance(meta, dict):
                    logger.warning(
                        f"Skipping invalid semantic table "
                        f"path={yaml_file} table={table_name}"
                    )
                    continue

                await db.execute(
                    """
                    INSERT OR REPLACE INTO semantic_metadata 
                    VALUES (?, ?, ?)
                    """,
                    (plugin, table_name, json.dumps(_normalize_table_meta(meta))),
                )

                loaded_counts[plugin] += 1
        await db.commit()
        return loaded_counts


async def introspect_connection_semantics(
    *,
    db: aiosqlite.Connection,
    connection: dict,
    live_schema: list[dict],
) -> None:
    connection_id = int(connection["id"])
    source_name = str(connection["plugin"])
    schema_name = str(connection["schema"])
    ignored_column_postfixes = ignored_column_postfixes_for_plugin(source_name)
    live_table_names = [str(table["name"]) for table in live_schema]

    await _align_connection_semantic_schema(
        db,
        connection_id=connection_id,
        schema_name=schema_name,
        live_table_names=live_table_names,
    )

    for table in live_schema:
        table_name = table["name"]
        raw_columns = table.get("columns", [])
        columns = [
            column
            for column in raw_columns
            if not is_ignored_column(
                str(column.get("name", "")),
                ignored_column_postfixes,
            )
        ]
        inferred = infer_table_semantics(table_name, columns)

        cursor = await db.execute(
            """
            INSERT INTO semantic_tables (
                connection_id,
                source_name,
                schema_name,
                table_name,
                label,
                description,
                table_type,
                grain,
                primary_time_column,
                hidden,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed')
            ON CONFLICT(connection_id, schema_name, table_name)
            DO UPDATE SET
                label = COALESCE(semantic_tables.label, excluded.label),
                description = COALESCE(semantic_tables.description, excluded.description),
                table_type = COALESCE(semantic_tables.table_type, excluded.table_type),
                grain = COALESCE(semantic_tables.grain, excluded.grain),
                primary_time_column = COALESCE(semantic_tables.primary_time_column, excluded.primary_time_column),
                status = CASE
                    WHEN semantic_tables.status = 'draft' THEN 'confirmed'
                    ELSE semantic_tables.status
                END,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
            """,
            (
                connection_id,
                source_name,
                schema_name,
                table_name,
                inferred["label"],
                inferred["description"],
                inferred["table_type"],
                inferred["grain"],
                inferred["primary_time_column"],
                int(inferred["hidden"]),
            ),
        )

        row = await cursor.fetchone()
        semantic_table_id = row[0]
        column_names = [str(column.get("name", "")) for column in columns]

        await _prune_stale_semantic_columns(
            db,
            semantic_table_id=int(semantic_table_id),
            live_column_names=column_names,
        )

        ignored_column_names = [
            str(column.get("name", ""))
            for column in raw_columns
            if is_ignored_column(
                str(column.get("name", "")),
                ignored_column_postfixes,
            )
        ]

        if ignored_column_names:
            placeholders = ",".join("?" for _ in ignored_column_names)

            async with db.execute(
                f"""
                SELECT id
                FROM semantic_columns
                WHERE semantic_table_id = ?
                  AND column_name IN ({placeholders})
                """,
                (semantic_table_id, *ignored_column_names),
            ) as cur:
                ignored_column_ids = [int(row[0]) for row in await cur.fetchall()]

            if ignored_column_ids:
                id_placeholders = ",".join("?" for _ in ignored_column_ids)

                await db.execute(
                    f"""
                    DELETE FROM semantic_relationships
                    WHERE from_column_id IN ({id_placeholders})
                       OR to_column_id IN ({id_placeholders})
                    """,
                    (*ignored_column_ids, *ignored_column_ids),
                )

            await db.execute(
                f"""
                DELETE FROM semantic_columns
                WHERE semantic_table_id = ?
                  AND column_name IN ({placeholders})
                """,
                (semantic_table_id, *ignored_column_names),
            )

        for column in columns:
            col_inferred = infer_column_semantics(column)

            await db.execute(
                """
                INSERT INTO semantic_columns (
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
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed')
                ON CONFLICT(semantic_table_id, column_name)
                DO UPDATE SET
                    label = COALESCE(semantic_columns.label, excluded.label),
                    description = COALESCE(semantic_columns.description, excluded.description),
                    data_type = excluded.data_type,
                    semantic_type = CASE
                        WHEN semantic_columns.semantic_type IN ('email', 'domain')
                            AND excluded.semantic_type NOT IN ('email', 'domain')
                        THEN excluded.semantic_type
                        ELSE COALESCE(semantic_columns.semantic_type, excluded.semantic_type)
                    END,
                    expression = COALESCE(semantic_columns.expression, excluded.expression),
                    unit = COALESCE(semantic_columns.unit, excluded.unit),
                    status = CASE
                        WHEN semantic_columns.status = 'draft' THEN 'confirmed'
                        ELSE semantic_columns.status
                    END,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    semantic_table_id,
                    column["name"],
                    col_inferred["label"],
                    column.get("description", ""),
                    column.get("type", ""),
                    col_inferred["semantic_type"],
                    col_inferred["expression"],
                    col_inferred["unit"],
                    int(col_inferred["is_dimension"]),
                    int(col_inferred["is_measure"]),
                    int(col_inferred["is_time"]),
                    int(col_inferred["is_id"]),
                    int(col_inferred["is_foreign_key"]),
                    int(col_inferred["hidden"]),
                ),
            )

    await db.commit()


async def _align_connection_semantic_schema(
    db: aiosqlite.Connection,
    *,
    connection_id: int,
    schema_name: str,
    live_table_names: list[str],
) -> None:
    if not live_table_names:
        async with db.execute(
            """
            SELECT id
            FROM semantic_tables
            WHERE connection_id = ?
            """,
            (connection_id,),
        ) as cur:
            stale_table_ids = [int(row[0]) for row in await cur.fetchall()]

        await _delete_semantic_tables(db, stale_table_ids)
        return

    placeholders = ",".join("?" for _ in live_table_names)

    await db.execute(
        f"""
        UPDATE semantic_tables
        SET schema_name = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE connection_id = ?
          AND schema_name != ?
          AND table_name IN ({placeholders})
          AND NOT EXISTS (
            SELECT 1
            FROM semantic_tables current_table
            WHERE current_table.connection_id = ?
              AND current_table.schema_name = ?
              AND current_table.table_name = semantic_tables.table_name
          )
        """,
        (
            schema_name,
            connection_id,
            schema_name,
            *live_table_names,
            connection_id,
            schema_name,
        ),
    )

    async with db.execute(
        """
        SELECT id
        FROM semantic_tables
        WHERE connection_id = ?
          AND schema_name != ?
        """,
        (connection_id, schema_name),
    ) as cur:
        stale_table_ids = [int(row[0]) for row in await cur.fetchall()]

    await _delete_semantic_tables(db, stale_table_ids)


async def _prune_stale_semantic_columns(
    db: aiosqlite.Connection,
    *,
    semantic_table_id: int,
    live_column_names: list[str],
) -> None:
    if live_column_names:
        placeholders = ",".join("?" for _ in live_column_names)

        async with db.execute(
            f"""
            SELECT id
            FROM semantic_columns
            WHERE semantic_table_id = ?
              AND column_name NOT IN ({placeholders})
            """,
            (semantic_table_id, *live_column_names),
        ) as cur:
            stale_column_ids = [int(row[0]) for row in await cur.fetchall()]
    else:
        async with db.execute(
            """
            SELECT id
            FROM semantic_columns
            WHERE semantic_table_id = ?
            """,
            (semantic_table_id,),
        ) as cur:
            stale_column_ids = [int(row[0]) for row in await cur.fetchall()]

    if not stale_column_ids:
        return

    column_placeholders = ",".join("?" for _ in stale_column_ids)

    await db.execute(
        f"""
        DELETE FROM semantic_relationships
        WHERE from_column_id IN ({column_placeholders})
           OR to_column_id IN ({column_placeholders})
        """,
        (*stale_column_ids, *stale_column_ids),
    )
    await db.execute(
        f"""
        DELETE FROM semantic_columns
        WHERE id IN ({column_placeholders})
        """,
        stale_column_ids,
    )


async def _delete_semantic_tables(
    db: aiosqlite.Connection,
    semantic_table_ids: list[int],
) -> None:
    if not semantic_table_ids:
        return

    placeholders = ",".join("?" for _ in semantic_table_ids)

    await db.execute(
        f"""
        DELETE FROM semantic_relationships
        WHERE from_column_id IN (
                SELECT id
                FROM semantic_columns
                WHERE semantic_table_id IN ({placeholders})
            )
           OR to_column_id IN (
                SELECT id
                FROM semantic_columns
                WHERE semantic_table_id IN ({placeholders})
           )
        """,
        (*semantic_table_ids, *semantic_table_ids),
    )

    await db.execute(
        f"""
        DELETE FROM semantic_relationships
        WHERE from_table_id IN ({placeholders})
           OR to_table_id IN ({placeholders})
        """,
        (*semantic_table_ids, *semantic_table_ids),
    )
    await db.execute(
        f"""
        DELETE FROM semantic_metrics
        WHERE semantic_table_id IN ({placeholders})
        """,
        semantic_table_ids,
    )
    await db.execute(
        f"""
        DELETE FROM semantic_columns
        WHERE semantic_table_id IN ({placeholders})
        """,
        semantic_table_ids,
    )
    await db.execute(
        f"""
        DELETE FROM semantic_tables
        WHERE id IN ({placeholders})
        """,
        semantic_table_ids,
    )


async def delete_connection_semantics(
    db: aiosqlite.Connection,
    connection_id: int,
) -> None:
    # Warnings are derived from relationship validation state and plugin metadata.
    # Deleting relationship rows clears connection-specific warning objects too.
    await db.execute(
        """
        DELETE FROM semantic_relationships
        WHERE from_connection_id = ?
           OR to_connection_id = ?
           OR from_table_id IN (
                SELECT id
                FROM semantic_tables
                WHERE connection_id = ?
           )
           OR to_table_id IN (
                SELECT id
                FROM semantic_tables
                WHERE connection_id = ?
           )
           OR from_column_id IN (
                SELECT c.id
                FROM semantic_columns c
                JOIN semantic_tables t ON t.id = c.semantic_table_id
                WHERE t.connection_id = ?
           )
           OR to_column_id IN (
                SELECT c.id
                FROM semantic_columns c
                JOIN semantic_tables t ON t.id = c.semantic_table_id
                WHERE t.connection_id = ?
           )
        """,
        (
            connection_id,
            connection_id,
            connection_id,
            connection_id,
            connection_id,
            connection_id,
        ),
    )

    await db.execute(
        """
        DELETE FROM semantic_metrics
        WHERE connection_id = ?
           OR semantic_table_id IN (
                SELECT id
                FROM semantic_tables
                WHERE connection_id = ?
           )
        """,
        (connection_id, connection_id),
    )

    await db.execute(
        """
        DELETE FROM semantic_columns
        WHERE semantic_table_id IN (
            SELECT id
            FROM semantic_tables
            WHERE connection_id = ?
        )
        """,
        (connection_id,),
    )

    await db.execute(
        """
        DELETE FROM semantic_tables
        WHERE connection_id = ?
        """,
        (connection_id,),
    )

    await db.commit()


async def discover_relationships(
    db: aiosqlite.Connection,
    connection_ids: list[int],
) -> None:
    if not connection_ids:
        return

    db.row_factory = aiosqlite.Row

    await prune_stale_system_relationships(db)
    await delete_system_relationship_suggestions(db, connection_ids)
    await prune_invalid_relationship_suggestions(db)

    async with db.execute(
        """
        SELECT
            t.id AS table_id,
            t.connection_id,
            t.source_name,
            t.schema_name,
            t.table_name,
            c.id AS column_id,
            c.column_name,
            c.data_type,
            c.semantic_type
        FROM semantic_tables t
        JOIN semantic_columns c ON c.semantic_table_id = t.id
        WHERE t.connection_id IN ({placeholders})
          AND t.hidden = 0
          AND c.hidden = 0
          AND c.semantic_type IN ('id', 'foreign_key', 'email', 'domain')
        """.format(placeholders=",".join("?" for _ in connection_ids)),
        connection_ids,
    ) as cur:
        rows = await cur.fetchall()

    cols = [dict(row) for row in rows]

    for left in cols:
        for right in cols:
            if left["column_id"] == right["column_id"]:
                continue

            candidate = relationship_candidate(left, right)

            if not candidate:
                continue

            if (
                candidate["match_type"] in {"exact_email", "exact_domain"}
                and left["column_id"] > right["column_id"]
            ):
                continue

            await db.execute(
                """
                INSERT OR IGNORE INTO semantic_relationships (
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
                    source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'suggested', 'system')
                """,
                (
                    left["connection_id"],
                    right["connection_id"],
                    left["table_id"],
                    left["column_id"],
                    right["table_id"],
                    right["column_id"],
                    candidate["relationship_type"],
                    candidate["match_type"],
                    candidate["confidence"],
                ),
            )

    await db.commit()


def relationship_candidate(left: dict, right: dict) -> dict | None:
    ltype = left["semantic_type"]
    rtype = right["semantic_type"]
    lname = left["column_name"].lower()
    rname = right["column_name"].lower()

    if left["table_id"] == right["table_id"]:
        return None

    if (
        ltype == "foreign_key"
        and rtype == "id"
        and left.get("source_name") == right.get("source_name")
        and rname in {"id", "uuid"}
        and id_data_types_compatible(left.get("data_type"), right.get("data_type"))
    ):
        base = foreign_key_entity_key(lname)

        if base and base == table_entity_key(right):
            return {
                "relationship_type": "many_to_one",
                "match_type": "exact_id",
                "confidence": 0.90,
            }

    return None


def normalized_tokens(name: str) -> list[str]:
    tokens = [token for token in re.split(r"[^a-z0-9]+", name.lower()) if token]

    return [singularize(token) for token in tokens]


def singularize(token: str) -> str:
    if len(token) > 3 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def table_entity_key(row: dict) -> str:
    tokens = normalized_tokens(str(row.get("table_name", "")))
    source_tokens = normalized_tokens(str(row.get("source_name", "")))

    if source_tokens and tokens[: len(source_tokens)] == source_tokens:
        tokens = tokens[len(source_tokens) :]

    return "_".join(tokens)


def column_key(column_name: str) -> str:
    return "_".join(normalized_tokens(column_name))


def foreign_key_entity_key(column_name: str) -> str:
    key = column_key(column_name)

    return key.removesuffix("_id")


def value_link_is_near_perfect(left: dict, right: dict) -> bool:
    return table_entity_key(left) == table_entity_key(right) and column_key(
        str(left.get("column_name", ""))
    ) == column_key(str(right.get("column_name", "")))


def id_data_types_compatible(left_type: str | None, right_type: str | None) -> bool:
    left = str(left_type or "").strip().lower()
    right = str(right_type or "").strip().lower()

    if left == right:
        return True

    return is_text_data_type(left) and is_text_data_type(right)


async def delete_system_relationship_suggestions(
    db: aiosqlite.Connection,
    connection_ids: list[int],
) -> None:
    placeholders = ",".join("?" for _ in connection_ids)

    await db.execute(
        f"""
        DELETE FROM semantic_relationships
        WHERE status = 'suggested'
          AND source = 'system'
          AND (
            from_connection_id IN ({placeholders})
            OR to_connection_id IN ({placeholders})
          )
        """,
        (*connection_ids, *connection_ids),
    )


async def prune_stale_system_relationships(db: aiosqlite.Connection) -> None:
    async with db.execute("""
        SELECT
            r.id,
            ft.id AS from_table_id,
            ft.source_name AS from_source_name,
            ft.table_name AS from_table_name,
            fc.id AS from_column_id,
            fc.column_name AS from_column_name,
            fc.data_type AS from_data_type,
            fc.semantic_type AS from_semantic_type,
            tt.id AS to_table_id,
            tt.source_name AS to_source_name,
            tt.table_name AS to_table_name,
            tc.id AS to_column_id,
            tc.column_name AS to_column_name,
            tc.data_type AS to_data_type,
            tc.semantic_type AS to_semantic_type
        FROM semantic_relationships r
        JOIN semantic_tables ft ON ft.id = r.from_table_id
        JOIN semantic_columns fc ON fc.id = r.from_column_id
        JOIN semantic_tables tt ON tt.id = r.to_table_id
        JOIN semantic_columns tc ON tc.id = r.to_column_id
        WHERE r.source = 'system'
          AND r.status != 'confirmed'
        """) as cur:
        rows = [dict(row) for row in await cur.fetchall()]

    stale_ids = []

    for row in rows:
        left = {
            "table_id": row["from_table_id"],
            "source_name": row["from_source_name"],
            "table_name": row["from_table_name"],
            "column_id": row["from_column_id"],
            "column_name": row["from_column_name"],
            "data_type": row["from_data_type"],
            "semantic_type": row["from_semantic_type"],
        }
        right = {
            "table_id": row["to_table_id"],
            "source_name": row["to_source_name"],
            "table_name": row["to_table_name"],
            "column_id": row["to_column_id"],
            "column_name": row["to_column_name"],
            "data_type": row["to_data_type"],
            "semantic_type": row["to_semantic_type"],
        }

        if not relationship_candidate(left, right):
            stale_ids.append(int(row["id"]))

    if not stale_ids:
        return

    placeholders = ",".join("?" for _ in stale_ids)

    await db.execute(
        f"""
        DELETE FROM semantic_relationships
        WHERE id IN ({placeholders})
        """,
        stale_ids,
    )


async def prune_invalid_relationship_suggestions(db: aiosqlite.Connection) -> None:
    await db.execute("""
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
          )
        """)


async def confirm_relationship(
    db: aiosqlite.Connection,
    relationship_id: int,
) -> None:
    await db.execute(
        """
        UPDATE semantic_relationships
        SET status = 'confirmed',
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (relationship_id,),
    )
    await db.commit()


async def build_semantic_contract(
    db: aiosqlite.Connection,
    *,
    selected_connection_ids: list[int],
    relevant_table_names: list[str] | None = None,
) -> dict:
    db.row_factory = aiosqlite.Row

    if not selected_connection_ids:
        return {
            "selected_connection_ids": [],
            "tables": {},
            "confirmed_relationships": [],
            "metrics": {},
            "rules": semantic_rules(),
        }

    placeholders = ",".join("?" for _ in selected_connection_ids)
    table_params: list = [*selected_connection_ids]
    relevant_filter = ""

    if relevant_table_names:
        relevant_filter = "AND t.table_name IN ({})".format(
            ",".join("?" for _ in relevant_table_names)
        )

        table_params.extend(relevant_table_names)

    async with db.execute(
        f"""
        SELECT *
        FROM semantic_tables t
        WHERE t.connection_id IN ({placeholders})
          AND t.hidden = 0
          AND t.status IN ('published', 'confirmed')
          {relevant_filter}
        ORDER BY t.source_name, t.table_name
        """,
        table_params,
    ) as cur:
        table_rows = [dict(row) for row in await cur.fetchall()]

    table_ids = [row["id"] for row in table_rows]

    if not table_ids:
        return {
            "selected_connection_ids": selected_connection_ids,
            "tables": {},
            "confirmed_relationships": [],
            "metrics": {},
            "rules": semantic_rules(),
        }

    table_placeholders = ",".join("?" for _ in table_ids)

    async with db.execute(
        f"""
        SELECT c.*, t.schema_name, t.table_name
        FROM semantic_columns c
        JOIN semantic_tables t ON t.id = c.semantic_table_id
        WHERE c.semantic_table_id IN ({table_placeholders})
          AND c.hidden = 0
          AND c.status IN ('published', 'confirmed')
        ORDER BY t.table_name, c.column_name
        """,
        table_ids,
    ) as cur:
        column_rows = [dict(row) for row in await cur.fetchall()]

    async with db.execute(
        f"""
        SELECT
            r.*,
            ft.schema_name AS from_schema,
            ft.table_name AS from_table,
            fc.column_name AS from_column,
            tt.schema_name AS to_schema,
            tt.table_name AS to_table,
            tc.column_name AS to_column
        FROM semantic_relationships r
        JOIN semantic_tables ft ON ft.id = r.from_table_id
        JOIN semantic_columns fc ON fc.id = r.from_column_id
        JOIN semantic_tables tt ON tt.id = r.to_table_id
        JOIN semantic_columns tc ON tc.id = r.to_column_id
        WHERE r.status = 'confirmed'
          AND ft.hidden = 0
          AND tt.hidden = 0
          AND fc.hidden = 0
          AND tc.hidden = 0
          AND ft.status IN ('published', 'confirmed')
          AND tt.status IN ('published', 'confirmed')
          AND fc.status IN ('published', 'confirmed')
          AND tc.status IN ('published', 'confirmed')
          AND r.from_table_id IN ({table_placeholders})
          AND r.to_table_id IN ({table_placeholders})
          AND r.from_connection_id IN ({placeholders})
          AND r.to_connection_id IN ({placeholders})
        ORDER BY r.confidence DESC
        """,
        [*table_ids, *table_ids, *selected_connection_ids, *selected_connection_ids],
    ) as cur:
        relationship_rows = [dict(row) for row in await cur.fetchall()]

    async with db.execute(
        f"""
        SELECT m.*, t.schema_name, t.table_name
        FROM semantic_metrics m
        JOIN semantic_tables t ON t.id = m.semantic_table_id
        WHERE m.connection_id IN ({placeholders})
          AND m.semantic_table_id IN ({table_placeholders})
          AND m.status IN ('published', 'confirmed')
        ORDER BY m.name
        """,
        [*selected_connection_ids, *table_ids],
    ) as cur:
        metric_rows = [dict(row) for row in await cur.fetchall()]

    return format_semantic_contract(
        tables=table_rows,
        columns=column_rows,
        relationships=relationship_rows,
        metrics=metric_rows,
        selected_connection_ids=selected_connection_ids,
        rules=_connector_semantic_rules(table_rows),
    )


def _normalize_table_meta(meta: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(meta)

    for section in ("metrics", "dimensions"):
        if section in normalized:
            normalized[section] = _normalize_semantic_mapping(normalized.get(section))

    return normalized


def _connector_semantic_rules(table_rows: list[dict[str, Any]]) -> list[str]:
    plugins = sorted(
        {
            str(table.get("source_name") or "").strip()
            for table in table_rows
            if str(table.get("source_name") or "").strip()
        }
    )
    rules: list[str] = []

    for snippet in connector_prompt_snippets(
        plugins,
        "semantic",
        "rules",
        include_headers=False,
    ):
        rules.extend(line.strip() for line in snippet.splitlines() if line.strip())

    return rules


def _normalize_semantic_mapping(value: Any) -> Any:
    if not isinstance(value, dict):
        return value

    normalized = {}

    for key, meta in value.items():
        if isinstance(meta, dict):
            item = dict(meta)

            if "expression" in item and "sql" not in item and "column" not in item:
                item["sql"] = item["expression"]

            normalized[key] = item
        else:
            normalized[key] = meta

    return normalized
