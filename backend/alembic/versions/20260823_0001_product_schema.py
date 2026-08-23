"""Create Settra product schema.

Revision ID: 20260823_0001
Revises:
Create Date: 2026-08-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.common.config import SETTRA_DB_SCHEMA

revision: str = "20260823_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = SETTRA_DB_SCHEMA


def upgrade() -> None:
    op.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))

    op.create_table(
        "connections",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("plugin", sa.Text(), nullable=False, server_default="googlesheets"),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("last_sync_started_at", sa.DateTime(timezone=True)),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("last_sync_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("plugin = 'googlesheets'", name="ck_connections_google_sheets"),
        schema=SCHEMA,
    )
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("connection_id", sa.BigInteger(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("table_count", sa.Integer()),
        sa.Column("row_count", sa.BigInteger()),
        sa.Column("load_ids", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["connection_id"], [f"{SCHEMA}.connections.id"], ondelete="CASCADE"),
        schema=SCHEMA,
    )
    op.create_index("idx_sync_runs_connection_started", "sync_runs", ["connection_id", sa.text("started_at DESC")], schema=SCHEMA)
    op.create_table(
        "collections",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("agent_instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_table(
        "collection_pipes",
        sa.Column("collection_id", sa.BigInteger(), nullable=False),
        sa.Column("pipe_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["collection_id"], [f"{SCHEMA}.collections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pipe_id"], [f"{SCHEMA}.connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("collection_id", "pipe_id"),
        schema=SCHEMA,
    )
    op.create_index("idx_collection_pipes_pipe", "collection_pipes", ["pipe_id"], schema=SCHEMA)
    op.create_table(
        "oauth_clients",
        sa.Column("client_id", sa.Text(), primary_key=True),
        sa.Column("client_name", sa.Text()),
        sa.Column("redirect_uris", sa.Text(), nullable=False),
        sa.Column("grant_types", sa.Text(), nullable=False),
        sa.Column("response_types", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("token_endpoint_auth_method", sa.Text(), nullable=False, server_default="none"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_table(
        "oauth_authorization_codes",
        sa.Column("code_hash", sa.Text(), primary_key=True),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.Text(), nullable=False),
        sa.Column("code_challenge_method", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["client_id"], [f"{SCHEMA}.oauth_clients.client_id"], ondelete="CASCADE"),
        schema=SCHEMA,
    )
    op.create_table(
        "oauth_refresh_tokens",
        sa.Column("token_hash", sa.Text(), primary_key=True),
        sa.Column("family_id", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["client_id"], [f"{SCHEMA}.oauth_clients.client_id"], ondelete="CASCADE"),
        schema=SCHEMA,
    )
    op.create_index("idx_oauth_refresh_tokens_family", "oauth_refresh_tokens", ["family_id"], schema=SCHEMA)
    op.create_index("idx_oauth_refresh_tokens_client", "oauth_refresh_tokens", ["client_id"], schema=SCHEMA)
    op.create_index("idx_oauth_refresh_tokens_expires", "oauth_refresh_tokens", ["expires_at"], schema=SCHEMA)
    op.create_table(
        "mcp_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.Text()),
        sa.Column("client_id", sa.Text()),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("request_bytes", sa.BigInteger(), nullable=False),
        sa.Column("response_bytes", sa.BigInteger(), nullable=False),
        sa.Column("estimated_input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("estimated_output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("error_type", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("idx_mcp_requests_created_at", "mcp_requests", [sa.text("created_at DESC")], schema=SCHEMA)
    op.create_index("idx_mcp_requests_status", "mcp_requests", ["status"], schema=SCHEMA)


def downgrade() -> None:
    for table in (
        "mcp_requests",
        "oauth_refresh_tokens",
        "oauth_authorization_codes",
        "oauth_clients",
        "collection_pipes",
        "collections",
        "sync_runs",
        "connections",
    ):
        op.drop_table(table, schema=SCHEMA)
