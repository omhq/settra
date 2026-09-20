"""Add one executable graph draft per collection.

Revision ID: 20260918_0009
Revises: 20260914_0008
Create Date: 2026-09-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

from app.common.config import APP_DB_SCHEMA

revision: str = "20260918_0009"
down_revision: str | None = "20260914_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = APP_DB_SCHEMA


def upgrade() -> None:
    op.create_table(
        "collection_graphs",
        sa.Column("collection_id", sa.BigInteger(), primary_key=True),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger()),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "layout",
            sa.Text(),
            nullable=False,
            server_default='{"version":1,"nodes":{}}',
        ),
        sa.Column(
            "revision",
            sa.BigInteger(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("revision > 0", name="ck_collection_graphs_revision"),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            [f"{SCHEMA}.collections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            [f"{SCHEMA}.organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            [f"{SCHEMA}.users.id"],
            ondelete="SET NULL",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_collection_graphs_organization",
        "collection_graphs",
        ["organization_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("collection_graphs", schema=SCHEMA)
