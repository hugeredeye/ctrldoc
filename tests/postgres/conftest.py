from __future__ import annotations

import os
import re
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from ctrl_v2.interfaces.http.app import create_app
from ctrl_v2.interfaces.http.config import Settings


@pytest.fixture(scope="session")
def postgresql_url() -> Iterator[str]:
    test_url = os.getenv("TEST_DATABASE_URL")
    admin_database_url = os.getenv("TEST_DATABASE_ADMIN_URL")
    if not test_url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    if not admin_database_url:
        pytest.skip("TEST_DATABASE_ADMIN_URL is required for PostgreSQL integration tests")
    url = make_url(test_url)
    admin_url = make_url(admin_database_url)
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("TEST_DATABASE_URL must point to PostgreSQL")
    if admin_url.get_backend_name() != "postgresql":
        raise RuntimeError("TEST_DATABASE_ADMIN_URL must point to PostgreSQL")
    database_name = url.database or ""
    if not re.fullmatch(r"[a-zA-Z0-9_]+", database_name):
        raise RuntimeError("Unsafe PostgreSQL integration database name")

    admin_url = admin_url.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    quoted_name = f'"{database_name}"'
    app_role = url.username or ""
    if not re.fullmatch(r"[a-zA-Z0-9_]+", app_role):
        raise RuntimeError("Unsafe PostgreSQL application role name")
    quoted_role = f'"{app_role}"'
    with admin_engine.connect() as connection:
        connection.exec_driver_sql(f"DROP DATABASE IF EXISTS {quoted_name} WITH (FORCE)")
        connection.exec_driver_sql(f"CREATE DATABASE {quoted_name} OWNER {quoted_role}")
    admin_engine.dispose()

    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    try:
        alembic_config = Config("alembic.ini")
        command.upgrade(alembic_config, "head")
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url

    yield test_url

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    with admin_engine.connect() as connection:
        connection.exec_driver_sql(f"DROP DATABASE IF EXISTS {quoted_name} WITH (FORCE)")
    admin_engine.dispose()


@pytest.fixture()
def pg_client(postgresql_url: str, tmp_path) -> Iterator[TestClient]:
    app = create_app(
        Settings(
            database_url=postgresql_url,
            object_storage_root=tmp_path / "private-objects",
            create_schema=False,
            log_level="INFO",
        )
    )
    with TestClient(app) as client:
        yield client
