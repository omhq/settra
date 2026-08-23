from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text
from sqlalchemy.engine import URL

from app.common.config import (
    SETTRA_DB_DATABASE,
    SETTRA_DB_HOST,
    SETTRA_DB_PASSWORD,
    SETTRA_DB_PORT,
    SETTRA_DB_SCHEMA,
    SETTRA_DB_USER,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _url() -> URL:
    return URL.create(
        "postgresql+psycopg2",
        username=SETTRA_DB_USER,
        password=SETTRA_DB_PASSWORD,
        host=SETTRA_DB_HOST,
        port=SETTRA_DB_PORT,
        database=SETTRA_DB_DATABASE,
    )


def _configure(connection=None) -> None:
    context.configure(
        connection=connection,
        url=_url(),
        target_metadata=target_metadata,
        include_schemas=True,
        version_table="alembic_version",
        version_table_schema=SETTRA_DB_SCHEMA,
        compare_type=True,
    )


def run_migrations_offline() -> None:
    _configure()
    with context.begin_transaction():
        context.execute(f'CREATE SCHEMA IF NOT EXISTS "{SETTRA_DB_SCHEMA}"')
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)

    with engine.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SETTRA_DB_SCHEMA}"'))
        connection.commit()
        connection.execute(text("SELECT pg_advisory_lock(hashtext('settra-alembic'))"))
        try:
            _configure(connection)
            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(hashtext('settra-alembic'))"))
            connection.commit()

    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
