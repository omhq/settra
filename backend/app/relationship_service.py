from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import asyncpg

from app.collection_service import get_collection
from app.destinations import DestinationRuntime, runtime_from_connection
from app.semantic.relationships import relationship_catalog, test_relationship_catalog


async def get_collection_relationships(collection_id: int) -> dict[str, Any]:
    collection = await get_collection(collection_id)
    allowed_names = set(collection["cube_names"])
    catalog = await relationship_catalog(allowed_names)
    return {
        "collection_id": collection["id"],
        "collection_slug": collection["slug"],
        **catalog,
    }


async def validate_collection_relationships(collection_id: int) -> dict[str, Any]:
    collection = await get_collection(collection_id)
    allowed_names = set(collection["cube_names"])
    catalog = await relationship_catalog(allowed_names)
    cube_validation = await test_relationship_catalog(
        catalog,
        allowed_names=allowed_names,
    )
    data_validation = await validate_relationship_data(collection, catalog)
    cube_by_id = {str(item["id"]): item for item in cube_validation["relationships"]}
    data_by_id = {str(item["id"]): item for item in data_validation["relationships"]}
    results: list[dict[str, Any]] = []

    for relationship in catalog["relationships"]:
        relationship_id = str(relationship["id"])
        cube_result = cube_by_id[relationship_id]
        data_result = data_by_id[relationship_id]
        results.append(
            {
                "id": relationship_id,
                "source_cube": relationship["source_cube"],
                "target_cube": relationship["target_cube"],
                "valid": bool(cube_result["valid"] and data_result["valid"]),
                "cube_query": cube_result,
                "data_integrity": data_result,
            }
        )

    return {
        "collection_id": collection["id"],
        "collection_slug": collection["slug"],
        "valid": bool(catalog["valid"] and all(item["valid"] for item in results)),
        "relationship_count": len(results),
        "tested_count": sum(item["valid"] for item in results),
        "relationships": results,
    }


async def validate_relationship_data(
    collection: dict[str, Any],
    catalog: dict[str, Any],
) -> dict[str, Any]:
    """Check declared cardinality against durable PostgreSQL snapshots."""

    pipes = {int(pipe["id"]): pipe for pipe in collection["pipes"]}
    results: list[dict[str, Any]] = []

    for relationship in catalog["relationships"]:
        result: dict[str, Any] = {
            "id": relationship["id"],
            "valid": False,
            "source_row_count": 0,
            "target_row_count": 0,
            "source_null_key_count": 0,
            "target_null_key_count": 0,
            "unmatched_source_row_count": 0,
            "duplicate_source_key_count": 0,
            "duplicate_target_key_count": 0,
            "error": None,
        }
        required = (
            "source_connection_id",
            "target_connection_id",
            "source_schema",
            "source_table",
            "source_column",
            "target_schema",
            "target_table",
            "target_column",
        )
        missing = [field for field in required if relationship.get(field) is None]

        if not relationship.get("valid"):
            result["error"] = "Relationship definition is invalid"
        elif missing:
            result["error"] = (
                "Relationship physical keys could not be resolved: "
                + ", ".join(missing)
            )
        else:
            source_pipe = pipes.get(int(relationship["source_connection_id"]))
            target_pipe = pipes.get(int(relationship["target_connection_id"]))

            if source_pipe is None or target_pipe is None:
                result["error"] = "Relationship source is outside this collection"
            elif source_pipe.get("destination_id") != target_pipe.get("destination_id"):
                result["error"] = (
                    "Relationship sources must use the same registered destination"
                )
            else:
                try:
                    runtime = runtime_from_connection(source_pipe)
                    runtime.require_built_in_postgres()
                    async with _destination_connection(runtime) as pg:
                        counts = await pg.fetchrow(
                            _relationship_integrity_sql(relationship)
                        )
                    if counts is None:
                        result["error"] = (
                            "Relationship integrity query returned no result"
                        )
                    else:
                        for field in (
                            "source_row_count",
                            "target_row_count",
                            "source_null_key_count",
                            "target_null_key_count",
                            "unmatched_source_row_count",
                            "duplicate_source_key_count",
                            "duplicate_target_key_count",
                        ):
                            result[field] = int(counts[field])
                        result["valid"] = _cardinality_is_valid(
                            str(relationship["relationship"]),
                            result,
                        )
                        if not result["valid"]:
                            result["error"] = (
                                "Snapshot keys do not satisfy the declared cardinality"
                            )
                except (OSError, ValueError, asyncpg.PostgresError) as exc:
                    result["error"] = (
                        "Relationship data validation failed: "
                        f"{exc.__class__.__name__}"
                    )

        results.append(result)

    return {
        "valid": all(item["valid"] for item in results),
        "relationship_count": len(results),
        "relationships": results,
    }


def _relationship_integrity_sql(relationship: dict[str, Any]) -> str:
    source = _qualified_table(
        str(relationship["source_schema"]),
        str(relationship["source_table"]),
    )
    target = _qualified_table(
        str(relationship["target_schema"]),
        str(relationship["target_table"]),
    )
    source_column = _quote_identifier(str(relationship["source_column"]))
    target_column = _quote_identifier(str(relationship["target_column"]))

    return f"""
        WITH source_keys AS (
            SELECT {source_column} AS relationship_key, count(*) AS key_count
            FROM {source}
            WHERE {source_column} IS NOT NULL
            GROUP BY {source_column}
        ), target_keys AS (
            SELECT {target_column} AS relationship_key, count(*) AS key_count
            FROM {target}
            WHERE {target_column} IS NOT NULL
            GROUP BY {target_column}
        )
        SELECT
            (SELECT count(*) FROM {source}) AS source_row_count,
            (SELECT count(*) FROM {target}) AS target_row_count,
            (SELECT count(*) FROM {source} WHERE {source_column} IS NULL)
                AS source_null_key_count,
            (SELECT count(*) FROM {target} WHERE {target_column} IS NULL)
                AS target_null_key_count,
            (
                SELECT count(*)
                FROM {source} AS source_row
                WHERE source_row.{source_column} IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM {target} AS target_row
                      WHERE target_row.{target_column} = source_row.{source_column}
                  )
            ) AS unmatched_source_row_count,
            (SELECT count(*) FROM source_keys WHERE key_count > 1)
                AS duplicate_source_key_count,
            (SELECT count(*) FROM target_keys WHERE key_count > 1)
                AS duplicate_target_key_count
    """


def _cardinality_is_valid(
    relationship: str,
    counts: dict[str, Any],
) -> bool:
    source_unique = (
        counts["source_null_key_count"] == 0
        and counts["duplicate_source_key_count"] == 0
    )
    target_unique = (
        counts["target_null_key_count"] == 0
        and counts["duplicate_target_key_count"] == 0
    )

    if relationship == "many_to_one":
        return target_unique
    if relationship == "one_to_many":
        return source_unique
    if relationship == "one_to_one":
        return source_unique and target_unique
    return False


def _qualified_table(schema: str, table: str) -> str:
    return f"{_quote_identifier(schema)}.{_quote_identifier(table)}"


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


@asynccontextmanager
async def _destination_connection(
    runtime: DestinationRuntime,
) -> AsyncIterator[asyncpg.Connection]:
    pg = await asyncpg.connect(
        **runtime.asyncpg_connect_kwargs(),
        timeout=10,
        command_timeout=10,
    )
    try:
        yield pg
    finally:
        await pg.close()
