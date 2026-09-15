"""Attach calculation drafts to collections.

Revision ID: 20260914_0007
Revises: 20260913_0006
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

from app.common.config import APP_DB_SCHEMA

revision: str = "20260914_0007"
down_revision: str | None = "20260913_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = APP_DB_SCHEMA


def upgrade() -> None:
    # Pre-existing drafts remain unassigned so the migration never guesses their
    # data boundary. The application requires a collection for every new draft
    # and provides an explicit assignment path for older drafts.
    op.add_column(
        "calculations",
        sa.Column("collection_id", sa.BigInteger()),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_calculations_collection",
        "calculations",
        "collections",
        ["collection_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_index(
        "idx_calculations_collection",
        "calculations",
        ["collection_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_calculations_collection",
        table_name="calculations",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "fk_calculations_collection",
        "calculations",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_column("calculations", "collection_id", schema=SCHEMA)
