from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url

from ctrl_v2.interfaces.http.app import create_app
from ctrl_v2.interfaces.http.config import Settings


@dataclass(frozen=True)
class PostgreSQLTestUrls:
    admin: str
    migrator: str
    runtime: str
    database_name: str


def _required_url(name: str, expected_user: str | None = None) -> URL:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required; PostgreSQL tests must not be skipped")
    url = make_url(value)
    if url.get_backend_name() != "postgresql":
        raise RuntimeError(f"{name} must point to PostgreSQL")
    if expected_user is not None and url.username != expected_user:
        raise RuntimeError(f"{name} must use {expected_user}")
    return url


@pytest.fixture(scope="session")
def postgres_urls() -> Iterator[PostgreSQLTestUrls]:
    admin_base = _required_url("TEST_DATABASE_ADMIN_URL")
    migrator_base = _required_url("TEST_DATABASE_MIGRATOR_URL", "ctrl_v2_migrator")
    runtime_base = _required_url("TEST_DATABASE_RUNTIME_URL", "ctrl_v2_runtime")
    database_name = runtime_base.database or ""
    if not re.fullmatch(r"[a-zA-Z0-9_]+", database_name):
        raise RuntimeError("Unsafe PostgreSQL integration database name")

    admin_url = admin_base.set(database="postgres")
    migrator_url = migrator_base.set(database=database_name)
    runtime_url = runtime_base.set(database=database_name)
    quoted_name = f'"{database_name}"'

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    with admin_engine.connect() as connection:
        connection.exec_driver_sql(f"DROP DATABASE IF EXISTS {quoted_name} WITH (FORCE)")
        connection.exec_driver_sql(
            f"CREATE DATABASE {quoted_name} OWNER ctrl_v2_owner TEMPLATE template0"
        )
    admin_engine.dispose()

    database_admin_engine = create_engine(
        admin_base.set(database=database_name), isolation_level="AUTOCOMMIT", hide_parameters=True
    )
    with database_admin_engine.connect() as connection:
        connection.exec_driver_sql("ALTER SCHEMA public OWNER TO ctrl_v2_owner")
        connection.exec_driver_sql(
            f"REVOKE ALL PRIVILEGES ON DATABASE {quoted_name} FROM PUBLIC"
        )
        connection.exec_driver_sql(
            f"GRANT CONNECT ON DATABASE {quoted_name} TO ctrl_v2_migrator, ctrl_v2_runtime"
        )
        connection.exec_driver_sql("REVOKE ALL PRIVILEGES ON SCHEMA public FROM PUBLIC")
        for role in ("ctrl_v2_owner", "ctrl_v2_migrator", "ctrl_v2_runtime"):
            connection.exec_driver_sql(
                f"ALTER ROLE {role} IN DATABASE {quoted_name} "
                "SET search_path TO pg_catalog, public"
            )
    database_admin_engine.dispose()

    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = migrator_url.render_as_string(hide_password=False)
    try:
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url

    urls = PostgreSQLTestUrls(
        admin=admin_base.set(database=database_name).render_as_string(hide_password=False),
        migrator=migrator_url.render_as_string(hide_password=False),
        runtime=runtime_url.render_as_string(hide_password=False),
        database_name=database_name,
    )
    yield urls

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    with admin_engine.connect() as connection:
        connection.exec_driver_sql(f"DROP DATABASE IF EXISTS {quoted_name} WITH (FORCE)")
    admin_engine.dispose()


@pytest.fixture(scope="session")
def postgresql_url(postgres_urls: PostgreSQLTestUrls) -> str:
    return postgres_urls.runtime


@pytest.fixture()
def client(postgres_urls: PostgreSQLTestUrls, tmp_path) -> Iterator[TestClient]:
    app = create_app(
        Settings(
            database_url=postgres_urls.runtime,
            object_storage_root=tmp_path / "private-objects",
            log_level="INFO",
        )
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def pg_client(client: TestClient) -> TestClient:
    return client
