from typing import Any

import asyncpg
import yaml

from app.auth import (
    current_organization_id,
    require_organization_write_access,
)
from app.db import db_connection
from app.errors import (
    InvalidInputError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from app.utils import slugify_name

MAX_CALCULATION_YAML_BYTES = 256 * 1024


async def list_calculations() -> list[dict[str, Any]]:
    organization_id = current_organization_id()

    async with db_connection() as db:
        rows = await db.fetch(
            """
            SELECT id, name, slug, created_at, updated_at
            FROM calculations
            WHERE organization_id = $1
            ORDER BY lower(name), id
            """,
            organization_id,
        )

    return [dict(row) for row in rows]


async def get_calculation(calculation_id: int) -> dict[str, Any]:
    organization_id = current_organization_id()

    async with db_connection() as db:
        row = await db.fetchrow(
            """
            SELECT id, name, slug, content, created_at, updated_at
            FROM calculations
            WHERE id = $1 AND organization_id = $2
            """,
            calculation_id,
            organization_id,
        )

    if row is None:
        raise ResourceNotFoundError("Calculation not found")

    return dict(row)


async def create_calculation(
    *,
    name: str,
    content: str | None = None,
) -> dict[str, Any]:
    identity = require_organization_write_access()
    normalized_name = _required_name(name)
    slug = slugify_name(normalized_name, prefix="calculation")[:63].rstrip("_")

    if not slug:
        raise InvalidInputError("Calculation name must contain letters or numbers")

    normalized_content = _validated_content(
        content if content is not None else _starter_content(slug)
    )

    try:
        async with db_connection() as db:
            calculation_id = await db.fetchval(
                """
                INSERT INTO calculations (
                    organization_id, created_by_user_id, name, slug, content
                ) VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                identity.organization_id,
                identity.user_id,
                normalized_name,
                slug,
                normalized_content,
            )
    except asyncpg.UniqueViolationError as exc:
        raise ResourceConflictError(
            "A calculation with that name already exists",
        ) from exc

    return await get_calculation(int(calculation_id))


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
            RETURNING id, name, slug, content, created_at, updated_at
            """,
            normalized_content,
            calculation_id,
            organization_id,
        )

    if row is None:
        raise ResourceNotFoundError("Calculation not found")

    return dict(row)


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
    if len(value.encode("utf-8")) > MAX_CALCULATION_YAML_BYTES:
        raise InvalidInputError("Calculation YAML must be 256 KB or smaller")

    if not value.strip():
        raise InvalidInputError("Calculation YAML cannot be empty")

    try:
        parsed = yaml.safe_load(value)
    except yaml.YAMLError as exc:
        problem = str(getattr(exc, "problem", "") or "invalid syntax")
        mark = getattr(exc, "problem_mark", None)
        location = (
            f" at line {mark.line + 1}, column {mark.column + 1}"
            if mark is not None
            else ""
        )
        raise InvalidInputError(
            f"Invalid calculation YAML{location}: {problem}",
        ) from exc

    if not isinstance(parsed, dict):
        raise InvalidInputError("Calculation YAML must contain a mapping")

    return value.rstrip() + "\n"


def _starter_content(slug: str) -> str:
    return yaml.safe_dump(
        {
            "version": 1,
            "name": slug,
            "description": "Describe what this calculation should produce.",
            "nodes": [
                {
                    "id": "source",
                    "type": "source",
                    "cube": "replace_with_cube_name",
                }
            ],
            "output": "source",
        },
        sort_keys=False,
        allow_unicode=True,
    )
