"""Add application accounts and organization tenancy.

Revision ID: 20260824_0004
Revises: 20260823_0003
Create Date: 2026-08-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.common.config import APP_DB_SCHEMA

revision: str = "20260824_0004"
down_revision: Union[str, None] = "20260823_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = APP_DB_SCHEMA


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        sa.CheckConstraint("length(trim(email)) > 0", name="ck_users_email"),
        sa.CheckConstraint(
            "length(trim(display_name)) > 0", name="ck_users_display_name"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ux_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        schema=SCHEMA,
    )

    op.create_table(
        "organizations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("kind", sa.Text(), nullable=False, server_default="personal"),
        sa.Column("personal_owner_user_id", sa.BigInteger(), unique=True),
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
            "kind IN ('personal', 'team')", name="ck_organizations_kind"
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_organizations_name"),
        sa.ForeignKeyConstraint(
            ["personal_owner_user_id"],
            [f"{SCHEMA}.users.id"],
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "organization_memberships",
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            [f"{SCHEMA}.organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{SCHEMA}.users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("organization_id", "user_id"),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'member', 'viewer')",
            name="ck_organization_memberships_role",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_organization_memberships_user",
        "organization_memberships",
        ["user_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "user_sessions",
        sa.Column("token_hash", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("csrf_token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{SCHEMA}.users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            [f"{SCHEMA}.organizations.id"],
            ondelete="CASCADE",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_user_sessions_user", "user_sessions", ["user_id"], schema=SCHEMA
    )
    op.create_index(
        "idx_user_sessions_expires", "user_sessions", ["expires_at"], schema=SCHEMA
    )

    op.add_column(
        "connections", sa.Column("organization_id", sa.BigInteger()), schema=SCHEMA
    )
    op.add_column(
        "connections", sa.Column("created_by_user_id", sa.BigInteger()), schema=SCHEMA
    )
    op.add_column("connections", sa.Column("storage_key", sa.Text()), schema=SCHEMA)
    op.execute(sa.text(f'UPDATE "{SCHEMA}".connections SET storage_key = slug'))
    op.alter_column(
        "connections",
        "storage_key",
        existing_type=sa.Text(),
        nullable=False,
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_connections_organization",
        "connections",
        "organizations",
        ["organization_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_connections_created_by_user",
        "connections",
        "users",
        ["created_by_user_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="SET NULL",
    )
    op.drop_constraint("connections_slug_key", "connections", schema=SCHEMA)
    op.create_unique_constraint(
        "uq_connections_storage_key", "connections", ["storage_key"], schema=SCHEMA
    )
    op.create_index(
        "uq_connections_organization_slug",
        "connections",
        ["organization_id", "slug"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("organization_id IS NOT NULL"),
    )
    op.create_index(
        "idx_connections_organization",
        "connections",
        ["organization_id"],
        schema=SCHEMA,
    )

    op.add_column(
        "collections", sa.Column("organization_id", sa.BigInteger()), schema=SCHEMA
    )
    op.add_column(
        "collections", sa.Column("created_by_user_id", sa.BigInteger()), schema=SCHEMA
    )
    op.create_foreign_key(
        "fk_collections_organization",
        "collections",
        "organizations",
        ["organization_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_collections_created_by_user",
        "collections",
        "users",
        ["created_by_user_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="SET NULL",
    )
    op.drop_constraint("collections_slug_key", "collections", schema=SCHEMA)
    op.create_index(
        "uq_collections_organization_slug",
        "collections",
        ["organization_id", "slug"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("organization_id IS NOT NULL"),
    )
    op.create_index(
        "idx_collections_organization",
        "collections",
        ["organization_id"],
        schema=SCHEMA,
    )

    # Authorization codes and refresh tokens were issued for the former
    # deployment-wide admin. They cannot safely survive the ownership migration.
    op.execute(sa.text(f'DELETE FROM "{SCHEMA}".oauth_refresh_tokens'))
    op.execute(sa.text(f'DELETE FROM "{SCHEMA}".oauth_authorization_codes'))
    for table in ("oauth_authorization_codes", "oauth_refresh_tokens"):
        op.add_column(table, sa.Column("user_id", sa.BigInteger()), schema=SCHEMA)
        op.add_column(
            table, sa.Column("organization_id", sa.BigInteger()), schema=SCHEMA
        )
        op.create_foreign_key(
            f"fk_{table}_user",
            table,
            "users",
            ["user_id"],
            ["id"],
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
            ondelete="CASCADE",
        )
        op.alter_column(
            table,
            "user_id",
            existing_type=sa.BigInteger(),
            nullable=False,
            schema=SCHEMA,
        )
        op.alter_column(
            table,
            "organization_id",
            existing_type=sa.BigInteger(),
            nullable=False,
            schema=SCHEMA,
        )
        op.create_foreign_key(
            f"fk_{table}_organization",
            table,
            "organizations",
            ["organization_id"],
            ["id"],
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
            ondelete="CASCADE",
        )

    op.add_column("mcp_requests", sa.Column("user_id", sa.BigInteger()), schema=SCHEMA)
    op.add_column(
        "mcp_requests", sa.Column("organization_id", sa.BigInteger()), schema=SCHEMA
    )
    op.create_foreign_key(
        "fk_mcp_requests_user",
        "mcp_requests",
        "users",
        ["user_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_mcp_requests_organization",
        "mcp_requests",
        "organizations",
        ["organization_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="CASCADE",
    )
    op.create_index(
        "idx_mcp_requests_organization_created",
        "mcp_requests",
        ["organization_id", sa.text("created_at DESC")],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_mcp_requests_organization_created",
        table_name="mcp_requests",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "fk_mcp_requests_organization",
        "mcp_requests",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_mcp_requests_user", "mcp_requests", schema=SCHEMA, type_="foreignkey"
    )
    op.drop_column("mcp_requests", "organization_id", schema=SCHEMA)
    op.drop_column("mcp_requests", "user_id", schema=SCHEMA)

    for table in ("oauth_refresh_tokens", "oauth_authorization_codes"):
        op.drop_constraint(
            f"fk_{table}_organization", table, schema=SCHEMA, type_="foreignkey"
        )
        op.drop_constraint(f"fk_{table}_user", table, schema=SCHEMA, type_="foreignkey")
        op.drop_column(table, "organization_id", schema=SCHEMA)
        op.drop_column(table, "user_id", schema=SCHEMA)

    op.drop_index(
        "idx_collections_organization", table_name="collections", schema=SCHEMA
    )
    op.drop_index(
        "uq_collections_organization_slug", table_name="collections", schema=SCHEMA
    )
    op.create_unique_constraint(
        "collections_slug_key", "collections", ["slug"], schema=SCHEMA
    )
    op.drop_constraint(
        "fk_collections_created_by_user",
        "collections",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_collections_organization", "collections", schema=SCHEMA, type_="foreignkey"
    )
    op.drop_column("collections", "created_by_user_id", schema=SCHEMA)
    op.drop_column("collections", "organization_id", schema=SCHEMA)

    op.drop_index(
        "idx_connections_organization", table_name="connections", schema=SCHEMA
    )
    op.drop_index(
        "uq_connections_organization_slug", table_name="connections", schema=SCHEMA
    )
    op.drop_constraint(
        "uq_connections_storage_key", "connections", schema=SCHEMA, type_="unique"
    )
    op.create_unique_constraint(
        "connections_slug_key", "connections", ["slug"], schema=SCHEMA
    )
    op.drop_constraint(
        "fk_connections_created_by_user",
        "connections",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_connections_organization", "connections", schema=SCHEMA, type_="foreignkey"
    )
    op.drop_column("connections", "storage_key", schema=SCHEMA)
    op.drop_column("connections", "created_by_user_id", schema=SCHEMA)
    op.drop_column("connections", "organization_id", schema=SCHEMA)

    op.drop_table("user_sessions", schema=SCHEMA)
    op.drop_index(
        "idx_organization_memberships_user",
        table_name="organization_memberships",
        schema=SCHEMA,
    )
    op.drop_table("organization_memberships", schema=SCHEMA)
    op.drop_table("organizations", schema=SCHEMA)
    op.drop_index("ux_users_email_lower", table_name="users", schema=SCHEMA)
    op.drop_table("users", schema=SCHEMA)
