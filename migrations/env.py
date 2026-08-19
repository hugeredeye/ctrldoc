from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import make_url

from ctrl_v2.infrastructure.persistence.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

MIGRATOR_ROLE = "ctrl_v2_migrator"
OWNER_ROLE = "ctrl_v2_owner"


def _required_migration_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for PostgreSQL migrations")
    try:
        url = make_url(database_url)
    except Exception as exc:
        raise RuntimeError("DATABASE_URL is not a valid SQLAlchemy URL") from exc
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("Alembic migrations require a PostgreSQL DATABASE_URL")
    if url.username != MIGRATOR_ROLE:
        raise RuntimeError(f"Alembic migrations require the {MIGRATOR_ROLE} credential")
    return database_url


config.set_main_option("sqlalchemy.url", _required_migration_url().replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    raise RuntimeError("Offline migrations are disabled because role identity cannot be verified")


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        session_user = connection.exec_driver_sql("SELECT session_user").scalar_one()
        if session_user != MIGRATOR_ROLE:
            raise RuntimeError(f"Connected migration role must be {MIGRATOR_ROLE}")
        connection.exec_driver_sql(f'SET ROLE "{OWNER_ROLE}"')
        connection.exec_driver_sql("SET search_path TO public")
        current_user = connection.exec_driver_sql("SELECT current_user").scalar_one()
        if current_user != OWNER_ROLE:
            raise RuntimeError(f"Migration role cannot SET ROLE {OWNER_ROLE}")
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
