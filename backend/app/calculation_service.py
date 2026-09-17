from typing import Any

import asyncpg
import yaml

from app.auth import (
    current_organization_id,
    require_organization_write_access,
)
from app.calculations.parser import validate_calculation_yaml_draft
from app.collection_service import get_collection
from app.db import db_connection
from app.errors import (
    InvalidInputError,
    InvalidOperationError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from app.utils import slugify_name


async def list_calculations(
    *,
    collection_id: int | None = None,
) -> list[dict[str, Any]]:
    organization_id = current_organization_id()
    collection_filter = "" if collection_id is None else "AND c.collection_id = $2"
    parameters: tuple[int, ...] = (
        (organization_id,)
        if collection_id is None
        else (organization_id, collection_id)
    )

    async with db_connection() as db:
        rows = await db.fetch(
            f"""
            SELECT c.id, c.name, c.slug, c.collection_id,
                   collection.name AS collection_name,
                   collection.slug AS collection_slug,
                   c.created_at, c.updated_at
            FROM calculations c
            LEFT JOIN collections collection ON collection.id = c.collection_id
            WHERE c.organization_id = $1
              {collection_filter}
            ORDER BY lower(c.name), c.id
            """,
            *parameters,
        )

    return [dict(row) for row in rows]


async def list_calculation_documents(collection_id: int) -> list[dict[str, Any]]:
    """Load App calculation documents for dependency analysis."""

    async with db_connection() as db:
        rows = await db.fetch(
            """
            SELECT id, name, slug, content
            FROM calculations
            WHERE collection_id = $1 AND organization_id = $2
            ORDER BY lower(name), id
            """,
            collection_id,
            current_organization_id(),
        )

    return [dict(row) for row in rows]


async def get_calculation(calculation_id: int) -> dict[str, Any]:
    organization_id = current_organization_id()

    async with db_connection() as db:
        row = await db.fetchrow(
            """
            SELECT c.id, c.name, c.slug, c.content, c.collection_id,
                   collection.name AS collection_name,
                   collection.slug AS collection_slug,
                   c.created_at, c.updated_at
            FROM calculations c
            LEFT JOIN collections collection ON collection.id = c.collection_id
            WHERE c.id = $1 AND c.organization_id = $2
            """,
            calculation_id,
            organization_id,
        )

    if row is None:
        raise ResourceNotFoundError("Calculation not found")

    return dict(row)


async def get_calculation_in_collection(
    collection_id: int,
    calculation_slug: str,
) -> dict[str, Any]:
    organization_id = current_organization_id()

    async with db_connection() as db:
        row = await db.fetchrow(
            """
            SELECT c.id, c.name, c.slug, c.content, c.collection_id,
                   collection.name AS collection_name,
                   collection.slug AS collection_slug,
                   c.created_at, c.updated_at
            FROM calculations c
            JOIN collections collection ON collection.id = c.collection_id
            WHERE c.collection_id = $1
              AND c.slug = $2
              AND c.organization_id = $3
            """,
            collection_id,
            calculation_slug,
            organization_id,
        )

    if row is None:
        raise ResourceNotFoundError(
            f"Calculation '{calculation_slug}' was not found in this App"
        )

    return dict(row)


async def create_calculation(
    *,
    collection_id: int,
    name: str,
    content: str,
) -> dict[str, Any]:
    identity = require_organization_write_access()
    await get_collection(collection_id, include_assets=False)
    normalized_name = _required_name(name)
    slug = slugify_name(normalized_name, prefix="calculation")[:63].rstrip("_")

    if not slug:
        raise InvalidInputError("Calculation name must contain letters or numbers")

    normalized_content = _validated_content(content)

    try:
        async with db_connection() as db:
            calculation_id = await db.fetchval(
                """
                INSERT INTO calculations (
                    organization_id, collection_id, created_by_user_id,
                    name, slug, content
                ) VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                identity.organization_id,
                collection_id,
                identity.user_id,
                normalized_name,
                slug,
                normalized_content,
            )
    except asyncpg.UniqueViolationError as exc:
        raise ResourceConflictError(
            "A calculation with that name already exists in this App",
        ) from exc

    return await get_calculation(int(calculation_id))


async def assign_calculation_collection(
    calculation_id: int,
    *,
    collection_id: int,
) -> dict[str, Any]:
    organization_id = require_organization_write_access().organization_id
    await get_collection(collection_id, include_assets=False)
    calculation = await get_calculation(calculation_id)
    previous_collection_id = calculation.get("collection_id")

    if previous_collection_id is not None and previous_collection_id != collection_id:
        raise InvalidOperationError("Calculations cannot be moved between Apps")

    if previous_collection_id is None:
        async with db_connection() as db:
            references = _calculation_reference_slugs(str(calculation["content"]))

            if references:
                target_rows = await db.fetch(
                    """
                    SELECT slug
                    FROM calculations
                    WHERE collection_id = $1 AND organization_id = $2
                    """,
                    collection_id,
                    organization_id,
                )
                target_slugs = {str(row["slug"]) for row in target_rows}
                missing_references = sorted(references - target_slugs)

                if missing_references:
                    raise ResourceConflictError(
                        f"Calculation '{calculation['name']}' depends on calculations "
                        "that are not in the destination App: "
                        + ", ".join(missing_references)
                    )

    try:
        async with db_connection() as db:
            row = await db.fetchrow(
                """
                UPDATE calculations
                SET collection_id = $1, updated_at = now()
                WHERE id = $2 AND organization_id = $3
                RETURNING id
                """,
                collection_id,
                calculation_id,
                organization_id,
            )
    except asyncpg.UniqueViolationError as exc:
        raise ResourceConflictError(
            "A calculation with that name already exists in this App"
        ) from exc

    if row is None:
        raise ResourceNotFoundError("Calculation not found")

    return await get_calculation(calculation_id)


async def update_calculation(
    calculation_id: int,
    *,
    content: str,
    expected_content: str | None,
) -> dict[str, Any]:
    organization_id = require_organization_write_access().organization_id
    normalized_content = _validated_content(content)

    if expected_content is None:
        raise InvalidInputError(
            "expected_content is required when updating a calculation"
        )

    async with db_connection() as db:
        row = await db.fetchrow(
            """
            UPDATE calculations
            SET content = $1, updated_at = now()
            WHERE id = $2 AND organization_id = $3 AND content = $4
            RETURNING id
            """,
            normalized_content,
            calculation_id,
            organization_id,
            expected_content,
        )

        if row is None:
            exists = await db.fetchrow(
                """
                SELECT id
                FROM calculations
                WHERE id = $1 AND organization_id = $2
                """,
                calculation_id,
                organization_id,
            )

    if row is None:
        if exists is None:
            raise ResourceNotFoundError("Calculation not found")

        raise ResourceConflictError(
            "This calculation was changed elsewhere. Reload before saving."
        )

    return await get_calculation(calculation_id)


async def delete_calculation(calculation_id: int) -> dict[str, Any]:
    organization_id = require_organization_write_access().organization_id

    async with db_connection() as db:
        calculation = await db.fetchrow(
            """
            SELECT id, name, slug, collection_id
            FROM calculations
            WHERE id = $1 AND organization_id = $2
            """,
            calculation_id,
            organization_id,
        )

        if calculation is None:
            raise ResourceNotFoundError("Calculation not found")

        collection_id = calculation.get("collection_id")

        if collection_id is not None:
            candidates = await db.fetch(
                """
                SELECT id, name, content
                FROM calculations
                WHERE collection_id = $1
                  AND organization_id = $2
                  AND id <> $3
                ORDER BY lower(name), id
                """,
                collection_id,
                organization_id,
                calculation_id,
            )
            dependents = [
                str(candidate["name"])
                for candidate in candidates
                if str(calculation["slug"])
                in _calculation_reference_slugs(str(candidate["content"]))
            ]

            if dependents:
                raise ResourceConflictError(
                    f"Calculation '{calculation['name']}' is used by: "
                    + ", ".join(dependents)
                    + ". Remove those calculation output references first."
                )

        row = await db.fetchrow(
            """
            DELETE FROM calculations
            WHERE id = $1 AND organization_id = $2
            RETURNING id, name
            """,
            calculation_id,
            organization_id,
        )

    return {"ok": True, "deleted": dict(row)}


def _required_name(value: str) -> str:
    name = " ".join(value.strip().split())

    if not 1 <= len(name) <= 120:
        raise InvalidInputError(
            "Calculation name must be between 1 and 120 characters",
        )

    return name


def _validated_content(value: str) -> str:
    return validate_calculation_yaml_draft(value)


def _calculation_reference_slugs(content: str) -> set[str]:
    try:
        document = yaml.safe_load(content)
    except yaml.YAMLError:
        return set()

    if not isinstance(document, dict) or not isinstance(document.get("nodes"), list):
        return set()

    return {
        str(node["calculation"])
        for node in document["nodes"]
        if isinstance(node, dict)
        and node.get("type") == "calculation_output"
        and isinstance(node.get("calculation"), str)
    }
