"""Scope calculation names to their collection.

Revision ID: 20260914_0008
Revises: 20260914_0007
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op

from app.common.config import APP_DB_SCHEMA

revision: str = "20260914_0008"
down_revision: str | None = "20260914_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = APP_DB_SCHEMA


def upgrade() -> None:
    op.drop_index(
        "uq_calculations_organization_slug",
        table_name="calculations",
        schema=SCHEMA,
    )
    op.create_index(
        "uq_calculations_collection_slug",
        "calculations",
        ["collection_id", "slug"],
        unique=True,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_calculations_collection_slug",
        table_name="calculations",
        schema=SCHEMA,
    )
    op.create_index(
        "uq_calculations_organization_slug",
        "calculations",
        ["organization_id", "slug"],
        unique=True,
        schema=SCHEMA,
    )
