"""Add workspace calculation YAML drafts.

Revision ID: 20260913_0006
Revises: 20260828_0005
Create Date: 2026-09-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.common.config import APP_DB_SCHEMA

revision: str = "20260913_0006"
down_revision: Union[str, None] = "20260828_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = APP_DB_SCHEMA


def upgrade() -> None:
    op.create_table(
        "calculations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
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
        sa.CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 120",
            name="ck_calculations_name",
        ),
        sa.CheckConstraint(
            "length(trim(slug)) BETWEEN 1 AND 63",
            name="ck_calculations_slug",
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
        "uq_calculations_organization_slug",
        "calculations",
        ["organization_id", "slug"],
        unique=True,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("calculations", schema=SCHEMA)
