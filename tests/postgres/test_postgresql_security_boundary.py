from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from ctrl_v2.infrastructure.persistence import DatabaseReadinessError
from ctrl_v2.infrastructure.persistence.database import REQUIRED_TRIGGERS, TENANT_TABLES
from ctrl_v2.interfaces.http.app import create_app
from ctrl_v2.interfaces.http.config import Settings
from tests.conftest import PostgreSQLTestUrls
from tests.helpers import Journey

pytestmark = pytest.mark.postgres


@contextmanager
def _database_url(value: str | None) -> Iterator[None]:
    previous = os.environ.get("DATABASE_URL")
    if value is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.mark.parametrize(
    "statement",
    [
        "ALTER TABLE public.documents ADD COLUMN runtime_forbidden text",
        "DROP TABLE public.documents",
        "TRUNCATE TABLE public.documents",
        "CREATE TABLE public.runtime_forbidden (id integer)",
        (
            "CREATE FUNCTION public.runtime_forbidden() RETURNS integer "
            "LANGUAGE sql AS 'SELECT 1'"
        ),
        "ALTER TABLE public.documents DISABLE ROW LEVEL SECURITY",
    ],
    ids=[
        "alter-table",
        "drop-table",
        "truncate",
        "create-table",
        "create-function",
        "disable-rls",
    ],
)
def test_runtime_cannot_execute_ddl_or_truncate(postgres_urls, statement: str):
    engine = create_engine(postgres_urls.runtime, hide_parameters=True)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                with pytest.raises(DBAPIError, match="permission denied|must be owner"):
                    connection.execute(text(statement))
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def test_runtime_without_workspace_context_sees_zero_tenant_rows(client, postgres_urls):
    journey = Journey(client, "No workspace context")
    document = journey.upload("tenant private", "RFP", "private.xlsx")
    engine = create_engine(postgres_urls.runtime, hide_parameters=True)
    try:
        with engine.connect() as connection:
            visible = connection.scalar(
                text("SELECT count(*) FROM documents WHERE id = :id"),
                {"id": document["document_id"]},
            )
        assert visible == 0
    finally:
        engine.dispose()


def test_unexpected_public_role_has_no_database_schema_or_table_access(postgres_urls):
    role_name = "ctrl_v2_unexpected_test"
    admin_engine = create_engine(
        postgres_urls.admin, isolation_level="AUTOCOMMIT", hide_parameters=True
    )
    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f"DROP ROLE IF EXISTS {role_name}")
            connection.exec_driver_sql(
                f"CREATE ROLE {role_name} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOINHERIT NOBYPASSRLS"
            )
            privileges = connection.execute(
                text(
                    """
                    SELECT
                        has_database_privilege(:role, current_database(), 'CONNECT') AS connect,
                        has_database_privilege(:role, current_database(), 'TEMP') AS temporary,
                        has_schema_privilege(:role, 'public', 'USAGE') AS schema_usage,
                        has_schema_privilege(:role, 'public', 'CREATE') AS schema_create,
                        has_table_privilege(:role, 'public.documents', 'SELECT') AS table_select
                    """
                ),
                {"role": role_name},
            ).mappings().one()
            assert not any(privileges.values())
    finally:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f"DROP ROLE IF EXISTS {role_name}")
        admin_engine.dispose()


def test_migrator_can_run_alembic_to_head(postgres_urls):
    with _database_url(postgres_urls.migrator):
        command.upgrade(Config("alembic.ini"), "head")


def test_runtime_cannot_run_alembic(postgres_urls):
    with _database_url(postgres_urls.runtime):
        with pytest.raises(RuntimeError, match="ctrl_v2_migrator"):
            command.upgrade(Config("alembic.ini"), "head")


def test_alembic_requires_database_url():
    with _database_url(None):
        with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
            command.upgrade(Config("alembic.ini"), "head")


def test_alembic_rejects_non_postgresql_url():
    with _database_url("sqlite:///forbidden.db"):
        with pytest.raises(RuntimeError, match="require a PostgreSQL"):
            command.upgrade(Config("alembic.ini"), "head")


def _runtime_app(postgres_urls: PostgreSQLTestUrls, tmp_path):
    return create_app(
        Settings(
            database_url=postgres_urls.runtime,
            object_storage_root=tmp_path / "private-objects",
        )
    )


def test_wrong_alembic_revision_fails_startup(postgres_urls, tmp_path):
    admin_engine = create_engine(postgres_urls.admin, hide_parameters=True)
    try:
        with admin_engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num = 'wrong_revision'"))
        with pytest.raises(DatabaseReadinessError, match="Alembic revision mismatch"):
            with TestClient(_runtime_app(postgres_urls, tmp_path)):
                pass
    finally:
        with admin_engine.begin() as connection:
            connection.execute(
                text("UPDATE alembic_version SET version_num = '8d4f2a1c7b90'")
            )
        admin_engine.dispose()


def test_missing_rls_policy_fails_startup(postgres_urls, tmp_path):
    admin_engine = create_engine(postgres_urls.admin, hide_parameters=True)
    try:
        with admin_engine.begin() as connection:
            connection.execute(text("DROP POLICY workspace_isolation ON documents"))
        with pytest.raises(DatabaseReadinessError, match="missing or unsafe RLS policies"):
            with TestClient(_runtime_app(postgres_urls, tmp_path)):
                pass
    finally:
        with admin_engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE POLICY workspace_isolation ON documents "
                    "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')) "
                    "WITH CHECK "
                    "(workspace_id = NULLIF(current_setting('app.workspace_id', true), ''))"
                )
            )
        admin_engine.dispose()


def test_missing_required_trigger_fails_startup(postgres_urls, tmp_path):
    admin_engine = create_engine(postgres_urls.admin, hide_parameters=True)
    try:
        with admin_engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE document_versions "
                    "DISABLE TRIGGER document_versions_immutable"
                )
            )
        with pytest.raises(DatabaseReadinessError, match="missing or disabled triggers"):
            with TestClient(_runtime_app(postgres_urls, tmp_path)):
                pass
    finally:
        with admin_engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE document_versions "
                    "ENABLE TRIGGER document_versions_immutable"
                )
            )
        admin_engine.dispose()


def test_wrong_function_owner_fails_startup(postgres_urls, tmp_path):
    function_name = "ctrl_reject_document_version_mutation()"
    admin_engine = create_engine(postgres_urls.admin, hide_parameters=True)
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f"ALTER FUNCTION {function_name} OWNER TO ctrl_v2_admin"))
        with pytest.raises(DatabaseReadinessError, match="functions not owned"):
            with TestClient(_runtime_app(postgres_urls, tmp_path)):
                pass
    finally:
        with admin_engine.begin() as connection:
            connection.execute(text(f"ALTER FUNCTION {function_name} OWNER TO ctrl_v2_owner"))
        admin_engine.dispose()


def test_runtime_owner_membership_fails_startup(postgres_urls, tmp_path):
    admin_engine = create_engine(postgres_urls.admin, hide_parameters=True)
    try:
        with admin_engine.begin() as connection:
            connection.execute(text("GRANT ctrl_v2_owner TO ctrl_v2_runtime"))
        with pytest.raises(DatabaseReadinessError, match="must not be a member"):
            with TestClient(_runtime_app(postgres_urls, tmp_path)):
                pass
    finally:
        with admin_engine.begin() as connection:
            connection.execute(text("REVOKE ctrl_v2_owner FROM ctrl_v2_runtime"))
        admin_engine.dispose()


def test_create_schema_true_is_rejected(postgres_urls, tmp_path):
    with pytest.raises(ValidationError, match="CREATE_SCHEMA is forbidden"):
        Settings(
            database_url=postgres_urls.runtime,
            object_storage_root=tmp_path / "private-objects",
            create_schema=True,
        )


def test_catalog_role_ownership_acl_and_rls_boundary(postgres_urls):
    engine = create_engine(postgres_urls.admin, hide_parameters=True)
    try:
        with engine.connect() as connection:
            roles = {
                row.rolname: row
                for row in connection.execute(
                    text(
                        "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolinherit, "
                        "rolcanlogin, rolbypassrls FROM pg_roles "
                        "WHERE rolname IN "
                        "('ctrl_v2_owner', 'ctrl_v2_migrator', 'ctrl_v2_runtime')"
                    )
                )
            }
            assert set(roles) == {"ctrl_v2_owner", "ctrl_v2_migrator", "ctrl_v2_runtime"}
            assert roles["ctrl_v2_owner"].rolcanlogin is False
            for role in roles.values():
                assert role.rolsuper is False
                assert role.rolcreatedb is False
                assert role.rolcreaterole is False
                assert role.rolinherit is False
                assert role.rolbypassrls is False

            database_owner = connection.scalar(
                text(
                    "SELECT pg_get_userbyid(datdba) FROM pg_database "
                    "WHERE datname = current_database()"
                )
            )
            schema_owner = connection.scalar(
                text(
                    "SELECT pg_get_userbyid(nspowner) FROM pg_namespace "
                    "WHERE nspname = 'public'"
                )
            )
            assert database_owner == "ctrl_v2_owner"
            assert schema_owner == "ctrl_v2_owner"

            object_owners = set(
                connection.scalars(
                    text(
                        "SELECT pg_get_userbyid(c.relowner) FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'S')"
                    )
                )
            )
            function_owners = set(
                connection.scalars(
                    text(
                        "SELECT pg_get_userbyid(p.proowner) FROM pg_proc p "
                        "JOIN pg_namespace n ON n.oid = p.pronamespace "
                        "WHERE n.nspname = 'public'"
                    )
                )
            )
            assert object_owners == {"ctrl_v2_owner"}
            assert function_owners == {"ctrl_v2_owner"}

            membership = connection.execute(
                text(
                    """
                    SELECT membership.admin_option, membership.inherit_option,
                           membership.set_option
                    FROM pg_auth_members membership
                    JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
                    JOIN pg_roles member_role ON member_role.oid = membership.member
                    WHERE granted_role.rolname = 'ctrl_v2_owner'
                      AND member_role.rolname = 'ctrl_v2_migrator'
                    """
                )
            ).one()
            assert membership.admin_option is False
            assert membership.inherit_option is False
            assert membership.set_option is True

            policies = set(
                connection.scalars(
                    text(
                        "SELECT tablename FROM pg_policies "
                        "WHERE schemaname = 'public' AND policyname = 'workspace_isolation'"
                    )
                )
            )
            forced_rls = set(
                connection.scalars(
                    text(
                        "SELECT c.relname FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = 'public' AND c.relrowsecurity "
                        "AND c.relforcerowsecurity"
                    )
                )
            )
            triggers = {
                row.tgname: row.relname
                for row in connection.execute(
                    text(
                        "SELECT t.tgname, c.relname FROM pg_trigger t "
                        "JOIN pg_class c ON c.oid = t.tgrelid "
                        "WHERE NOT t.tgisinternal AND t.tgenabled IN ('O', 'A')"
                    )
                )
            }
            assert policies == TENANT_TABLES
            assert forced_rls == TENANT_TABLES
            assert {name: triggers.get(name) for name in REQUIRED_TRIGGERS} == REQUIRED_TRIGGERS

            runtime_privileges = connection.execute(
                text(
                    """
                    SELECT
                        has_database_privilege('ctrl_v2_runtime', current_database(), 'CONNECT')
                            AS connect,
                        has_database_privilege('ctrl_v2_runtime', current_database(), 'TEMP')
                            AS temporary,
                        has_schema_privilege('ctrl_v2_runtime', 'public', 'USAGE')
                            AS schema_usage,
                        has_schema_privilege('ctrl_v2_runtime', 'public', 'CREATE')
                            AS schema_create,
                        has_table_privilege('ctrl_v2_runtime', 'documents', 'SELECT')
                            AS table_select,
                        has_table_privilege('ctrl_v2_runtime', 'documents', 'INSERT')
                            AS table_insert,
                        has_table_privilege('ctrl_v2_runtime', 'documents', 'UPDATE')
                            AS table_update,
                        has_table_privilege('ctrl_v2_runtime', 'documents', 'DELETE')
                            AS table_delete,
                        has_table_privilege('ctrl_v2_runtime', 'documents', 'TRUNCATE')
                            AS table_truncate,
                        has_table_privilege('ctrl_v2_runtime', 'documents', 'TRIGGER')
                            AS table_trigger,
                        has_table_privilege('ctrl_v2_runtime', 'alembic_version', 'UPDATE')
                            AS migration_update
                    """
                )
            ).mappings().one()
            assert runtime_privileges["connect"]
            assert runtime_privileges["schema_usage"]
            for privilege in ("table_select", "table_insert", "table_update", "table_delete"):
                assert runtime_privileges[privilege]
            for privilege in (
                "temporary",
                "schema_create",
                "table_truncate",
                "table_trigger",
                "migration_update",
            ):
                assert not runtime_privileges[privilege]
    finally:
        engine.dispose()
