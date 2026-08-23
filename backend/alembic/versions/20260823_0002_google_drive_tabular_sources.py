"""Broaden spreadsheet connections to Google Drive tabular files.

Revision ID: 20260823_0002
Revises: 20260823_0001
Create Date: 2026-08-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.common.config import APP_DB_SCHEMA

revision: str = "20260823_0002"
down_revision: Union[str, None] = "20260823_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = APP_DB_SCHEMA


def upgrade() -> None:
    op.drop_constraint(
        "ck_connections_google_sheets",
        "connections",
        schema=SCHEMA,
        type_="check",
    )
    op.execute(
        sa.text(
            f'UPDATE "{SCHEMA}".connections '
            "SET plugin = 'googledrive' WHERE plugin = 'googlesheets'"
        )
    )
    op.alter_column(
        "connections",
        "plugin",
        schema=SCHEMA,
        existing_type=sa.Text(),
        server_default="googledrive",
    )
    op.create_check_constraint(
        "ck_connections_google_drive",
        "connections",
        "plugin = 'googledrive'",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_connections_google_drive",
        "connections",
        schema=SCHEMA,
        type_="check",
    )
    op.execute(
        sa.text(
            f'UPDATE "{SCHEMA}".connections '
            "SET plugin = 'googlesheets' WHERE plugin = 'googledrive'"
        )
    )
    op.alter_column(
        "connections",
        "plugin",
        schema=SCHEMA,
        existing_type=sa.Text(),
        server_default="googlesheets",
    )
    op.create_check_constraint(
        "ck_connections_google_sheets",
        "connections",
        "plugin = 'googlesheets'",
        schema=SCHEMA,
    )
