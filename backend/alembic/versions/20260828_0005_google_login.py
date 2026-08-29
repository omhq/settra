"""Add Google login identities.

Revision ID: 20260828_0005
Revises: 20260824_0004
Create Date: 2026-08-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.common.config import APP_DB_SCHEMA

revision: str = "20260828_0005"
down_revision: Union[str, None] = "20260824_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = APP_DB_SCHEMA


def upgrade() -> None:
    op.alter_column(
        "users",
        "password_hash",
        existing_type=sa.Text(),
        nullable=True,
        schema=SCHEMA,
    )
    op.create_table(
        "google_login_identities",
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("google_subject", sa.Text(), nullable=False, unique=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_login_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "length(google_subject) BETWEEN 1 AND 255",
            name="ck_google_login_identities_subject",
        ),
        sa.CheckConstraint(
            "length(trim(email)) > 0",
            name="ck_google_login_identities_email",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [f"{SCHEMA}.users.id"],
            ondelete="CASCADE",
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("google_login_identities", schema=SCHEMA)
    # Google-only accounts have no local credential. Preserve the account row
    # while giving it an intentionally invalid hash that local login rejects.
    op.execute(sa.text(f"""UPDATE "{SCHEMA}".users
                SET password_hash = 'federated-login-disabled'
                WHERE password_hash IS NULL"""))
    op.alter_column(
        "users",
        "password_hash",
        existing_type=sa.Text(),
        nullable=False,
        schema=SCHEMA,
    )
