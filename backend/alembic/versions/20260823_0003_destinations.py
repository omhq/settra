"""Separate pipe destinations from source connections.

Revision ID: 20260823_0003
Revises: 20260823_0002
Create Date: 2026-08-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.common.config import APP_DB_SCHEMA

revision: str = "20260823_0003"
down_revision: Union[str, None] = "20260823_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = APP_DB_SCHEMA
MANAGED_DESTINATION_SLUG = "built_in_postgres"


def upgrade() -> None:
    op.create_table(
        "destinations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column(
            "configuration",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "is_builtin", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default=sa.false()
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
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_destinations_name"),
        sa.CheckConstraint("length(trim(type)) > 0", name="ck_destinations_type"),
        schema=SCHEMA,
    )
    op.create_index(
        "ux_destinations_default",
        "destinations",
        ["is_default"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("is_default"),
    )
    op.execute(sa.text(f"""
            INSERT INTO "{SCHEMA}".destinations
                (name, slug, type, configuration, is_builtin, is_default)
            VALUES
                ('Managed PostgreSQL', '{MANAGED_DESTINATION_SLUG}', 'postgres',
                 '{{"mode": "environment"}}'::jsonb, true, true)
            ON CONFLICT (slug) DO UPDATE
            SET name = EXCLUDED.name,
                type = EXCLUDED.type,
                configuration = EXCLUDED.configuration,
                is_builtin = EXCLUDED.is_builtin,
                is_default = EXCLUDED.is_default,
                updated_at = now()
            """))
    op.add_column(
        "connections",
        sa.Column("destination_id", sa.BigInteger(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "connections",
        sa.Column("destination_schema", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    op.execute(sa.text(f"""
            UPDATE "{SCHEMA}".connections AS connections
            SET destination_id = destinations.id,
                destination_schema = connections.slug
            FROM "{SCHEMA}".destinations AS destinations
            WHERE destinations.slug = '{MANAGED_DESTINATION_SLUG}'
            """))
    op.alter_column(
        "connections",
        "destination_id",
        schema=SCHEMA,
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.alter_column(
        "connections",
        "destination_schema",
        schema=SCHEMA,
        existing_type=sa.Text(),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_connections_destination",
        "connections",
        "destinations",
        ["destination_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_connections_destination_schema",
        "connections",
        ["destination_id", "destination_schema"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_connections_destination",
        "connections",
        ["destination_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_connections_destination", table_name="connections", schema=SCHEMA
    )
    op.drop_constraint(
        "uq_connections_destination_schema",
        "connections",
        schema=SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "fk_connections_destination",
        "connections",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_column("connections", "destination_schema", schema=SCHEMA)
    op.drop_column("connections", "destination_id", schema=SCHEMA)
    op.drop_index("ux_destinations_default", table_name="destinations", schema=SCHEMA)
    op.drop_table("destinations", schema=SCHEMA)
