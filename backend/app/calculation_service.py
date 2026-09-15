from typing import Any

import asyncpg

from app.auth import (
    current_organization_id,
    require_organization_write_access,
)
from app.calculations.parser import validate_calculation_yaml_draft
from app.collection_service import get_collection
from app.db import db_connection
from app.errors import (
    InvalidInputError,
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
            "A calculation with that name already exists in this collection",
        ) from exc

    return await get_calculation(int(calculation_id))


async def assign_calculation_collection(
    calculation_id: int,
    *,
    collection_id: int,
) -> dict[str, Any]:
    organization_id = require_organization_write_access().organization_id
    await get_collection(collection_id, include_assets=False)

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
            "A calculation with that name already exists in this collection"
        ) from exc

    if row is None:
        raise ResourceNotFoundError("Calculation not found")

    return await get_calculation(calculation_id)


async def update_calculation(
    calculation_id: int,
    *,
    content: str,
) -> dict[str, Any]:
    organization_id = require_organization_write_access().organization_id
    normalized_content = _validated_content(content)

    async with db_connection() as db:
        row = await db.fetchrow(
            """
            UPDATE calculations
            SET content = $1, updated_at = now()
            WHERE id = $2 AND organization_id = $3
            RETURNING id
            """,
            normalized_content,
            calculation_id,
            organization_id,
        )

    if row is None:
        raise ResourceNotFoundError("Calculation not found")

    return await get_calculation(calculation_id)


async def delete_calculation(calculation_id: int) -> dict[str, Any]:
    organization_id = require_organization_write_access().organization_id

    async with db_connection() as db:
        row = await db.fetchrow(
            """
            DELETE FROM calculations
            WHERE id = $1 AND organization_id = $2
            RETURNING id, name
            """,
            calculation_id,
            organization_id,
        )

    if row is None:
        raise ResourceNotFoundError("Calculation not found")

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
