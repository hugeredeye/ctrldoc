from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

EXPECTED_ALEMBIC_REVISION = "c7a0e11f6b42"
OWNER_ROLE = "ctrl_v2_owner"
RUNTIME_ROLE = "ctrl_v2_runtime"
TENANT_TABLES = frozenset(
    {
        "capabilities",
        "compliance_decisions",
        "conflicts",
        "decision_evidence_spans",
        "document_blocks",
        "document_representations",
        "document_versions",
        "documents",
        "evaluation_datasets",
        "evaluation_runs",
        "evidence",
        "evidence_spans",
        "human_reviews",
        "outbox_events",
        "processing_jobs",
        "product_version_capabilities",
        "product_version_documents",
        "product_versions",
        "products",
        "requirement_mappings",
        "requirement_source_spans",
        "requirements",
        "response_exports",
        "response_items",
        "responses",
        "rfps",
        "workspace_memberships",
    }
)
REQUIRED_TRIGGERS = {
    "approved_decision_links_immutable": "decision_evidence_spans",
    "approved_decision_requires_evidence": "compliance_decisions",
    "approved_decisions_immutable": "compliance_decisions",
    "document_versions_immutable": "document_versions",
    "response_snapshot_immutable": "responses",
}


class DatabaseReadinessError(RuntimeError):
    pass


class Database:
    def __init__(self, url: str) -> None:
        try:
            parsed_url = make_url(url)
        except Exception as exc:
            raise DatabaseReadinessError("DATABASE_URL is not a valid SQLAlchemy URL") from exc
        if parsed_url.get_backend_name() != "postgresql":
            raise DatabaseReadinessError("CTRL runtime requires PostgreSQL")
        self.engine: Engine = create_engine(
            url,
            future=True,
            hide_parameters=True,
        )
        self.session_factory = sessionmaker(
            bind=self.engine, class_=Session, autoflush=False, expire_on_commit=False
        )

    def verify_runtime_readiness(self) -> None:
        errors: list[str] = []
        with self.engine.connect() as connection:
            role = connection.execute(
                text(
                    """
                    SELECT
                        session_user,
                        current_user,
                        roles.rolsuper,
                        roles.rolcreatedb,
                        roles.rolcreaterole,
                        roles.rolbypassrls,
                        roles.rolcanlogin,
                        pg_has_role(session_user, 'ctrl_v2_owner', 'MEMBER') AS owns_member,
                        current_setting('search_path') AS search_path,
                        has_database_privilege(
                            session_user, current_database(), 'TEMP'
                        ) AS can_temp,
                        has_schema_privilege(session_user, 'public', 'CREATE') AS can_create_schema
                    FROM pg_roles roles
                    WHERE roles.rolname = session_user
                    """
                )
            ).mappings().one()
            if role["session_user"] != RUNTIME_ROLE or role["current_user"] != RUNTIME_ROLE:
                errors.append(f"runtime database role must be {RUNTIME_ROLE}")
            if any(
                role[key]
                for key in ("rolsuper", "rolcreatedb", "rolcreaterole", "rolbypassrls")
            ):
                errors.append("runtime database role has elevated cluster privileges")
            if not role["rolcanlogin"]:
                errors.append("runtime database role cannot login")
            if role["owns_member"]:
                errors.append(f"runtime database role must not be a member of {OWNER_ROLE}")
            if role["can_temp"] or role["can_create_schema"]:
                errors.append("runtime database role can create database or schema objects")
            if role["search_path"] != "pg_catalog, public":
                errors.append("runtime search_path must be pinned to pg_catalog, public")

            boundary_roles = {
                row["rolname"]: row
                for row in connection.execute(
                    text(
                        """
                        SELECT rolname, rolsuper, rolcreatedb, rolcreaterole,
                               rolinherit, rolcanlogin, rolbypassrls
                        FROM pg_roles
                        WHERE rolname IN (
                            'ctrl_v2_owner', 'ctrl_v2_migrator', 'ctrl_v2_runtime'
                        )
                        """
                    )
                ).mappings()
            }
            if set(boundary_roles) != {OWNER_ROLE, "ctrl_v2_migrator", RUNTIME_ROLE}:
                errors.append("production database roles are missing")
            else:
                owner = boundary_roles[OWNER_ROLE]
                migrator = boundary_roles["ctrl_v2_migrator"]
                if owner["rolcanlogin"] or migrator["rolinherit"]:
                    errors.append("owner or migrator role attributes are unsafe")
                if not migrator["rolcanlogin"]:
                    errors.append("migrator database role cannot login")
                for boundary_role in boundary_roles.values():
                    if any(
                        boundary_role[key]
                        for key in ("rolsuper", "rolcreatedb", "rolcreaterole", "rolbypassrls")
                    ):
                        errors.append("production database role has elevated cluster privileges")
                        break
                migrator_membership = connection.execute(
                    text(
                        """
                        SELECT
                            EXISTS (
                                SELECT 1
                                FROM pg_auth_members membership
                                JOIN pg_roles granted_role
                                  ON granted_role.oid = membership.roleid
                                JOIN pg_roles member_role
                                  ON member_role.oid = membership.member
                                WHERE granted_role.rolname = 'ctrl_v2_owner'
                                  AND member_role.rolname = 'ctrl_v2_migrator'
                                  AND NOT membership.admin_option
                                  AND NOT membership.inherit_option
                                  AND membership.set_option
                            ) AS is_safe_membership,
                            pg_has_role('ctrl_v2_runtime', 'ctrl_v2_owner', 'MEMBER')
                                AS runtime_is_member
                        """
                    )
                ).mappings().one()
                if not migrator_membership["is_safe_membership"]:
                    errors.append("migrator membership options are unsafe")
                if migrator_membership["runtime_is_member"]:
                    errors.append("runtime must not be a member of ctrl_v2_owner")

            revision = connection.scalar(text("SELECT version_num FROM public.alembic_version"))
            if revision != EXPECTED_ALEMBIC_REVISION:
                errors.append(
                    "Alembic revision mismatch: "
                    f"expected {EXPECTED_ALEMBIC_REVISION}, got {revision}"
                )

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
            if database_owner != OWNER_ROLE:
                errors.append(f"database must be owned by {OWNER_ROLE}")
            if schema_owner != OWNER_ROLE:
                errors.append(f"public schema must be owned by {OWNER_ROLE}")

            object_owners = connection.execute(
                text(
                    """
                    SELECT c.relname, pg_get_userbyid(c.relowner) AS owner
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'S')
                    """
                )
            ).all()
            invalid_owners = sorted(name for name, owner in object_owners if owner != OWNER_ROLE)
            if invalid_owners:
                errors.append(f"objects not owned by {OWNER_ROLE}: {', '.join(invalid_owners)}")

            function_owners = connection.execute(
                text(
                    """
                    SELECT p.proname, pg_get_userbyid(p.proowner) AS owner
                    FROM pg_proc p
                    JOIN pg_namespace n ON n.oid = p.pronamespace
                    WHERE n.nspname = 'public'
                    """
                )
            ).all()
            invalid_functions = sorted(
                name for name, owner in function_owners if owner != OWNER_ROLE
            )
            if invalid_functions:
                errors.append(
                    f"functions not owned by {OWNER_ROLE}: {', '.join(invalid_functions)}"
                )

            policy_rows = connection.execute(
                text(
                    """
                    SELECT
                        c.relname,
                        c.relrowsecurity,
                        c.relforcerowsecurity,
                        policies.cmd,
                        policies.qual,
                        policies.with_check
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    LEFT JOIN pg_policies policies
                      ON policies.schemaname = n.nspname
                     AND policies.tablename = c.relname
                     AND policies.policyname = 'workspace_isolation'
                    WHERE n.nspname = 'public' AND c.relname = ANY(:tables)
                    """
                ),
                {"tables": list(TENANT_TABLES)},
            ).mappings()
            valid_policy_tables: set[str] = set()
            for policy in policy_rows:
                expression = "app.workspace_id"
                if (
                    policy["relrowsecurity"]
                    and policy["relforcerowsecurity"]
                    and policy["cmd"] == "ALL"
                    and policy["qual"]
                    and policy["with_check"]
                    and expression in policy["qual"]
                    and expression in policy["with_check"]
                ):
                    valid_policy_tables.add(policy["relname"])
            missing_policies = sorted(TENANT_TABLES - valid_policy_tables)
            if missing_policies:
                errors.append(f"missing or unsafe RLS policies: {', '.join(missing_policies)}")

            trigger_rows = connection.execute(
                text(
                    """
                    SELECT triggers.tgname, tables.relname, triggers.tgenabled
                    FROM pg_trigger triggers
                    JOIN pg_class tables ON tables.oid = triggers.tgrelid
                    JOIN pg_namespace schemas ON schemas.oid = tables.relnamespace
                    WHERE schemas.nspname = 'public'
                      AND NOT triggers.tgisinternal
                      AND triggers.tgname = ANY(:triggers)
                    """
                ),
                {"triggers": list(REQUIRED_TRIGGERS)},
            ).all()
            active_triggers = {
                name: table for name, table, enabled in trigger_rows if enabled in {"O", "A"}
            }
            missing_triggers = sorted(
                name
                for name, table in REQUIRED_TRIGGERS.items()
                if active_triggers.get(name) != table
            )
            if missing_triggers:
                errors.append(f"missing or disabled triggers: {', '.join(missing_triggers)}")

        if errors:
            raise DatabaseReadinessError("; ".join(errors))

    def sessions(self) -> Iterator[Session]:
        with self.session_factory() as session:
            yield session
