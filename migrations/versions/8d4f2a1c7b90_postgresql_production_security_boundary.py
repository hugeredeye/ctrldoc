"""PostgreSQL production role and privilege boundary.

Revision ID: 8d4f2a1c7b90
Revises: 4b6c3a9e2d11
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "8d4f2a1c7b90"
down_revision: str | None = "4b6c3a9e2d11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = (
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
)


def _assert_bootstrap_boundary() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            DECLARE
                invalid_objects text;
            BEGIN
                IF current_user <> 'ctrl_v2_owner' THEN
                    RAISE EXCEPTION 'Security migration must run as ctrl_v2_owner';
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM pg_roles
                    WHERE rolname = 'ctrl_v2_owner'
                      AND NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb
                      AND NOT rolcreaterole AND NOT rolinherit AND NOT rolbypassrls
                ) THEN
                    RAISE EXCEPTION 'ctrl_v2_owner role is missing or unsafe';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_roles
                    WHERE rolname = 'ctrl_v2_migrator'
                      AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb
                      AND NOT rolcreaterole AND NOT rolinherit AND NOT rolbypassrls
                ) THEN
                    RAISE EXCEPTION 'ctrl_v2_migrator role is missing or unsafe';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_roles
                    WHERE rolname = 'ctrl_v2_runtime'
                      AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb
                      AND NOT rolcreaterole AND NOT rolinherit AND NOT rolbypassrls
                ) THEN
                    RAISE EXCEPTION 'ctrl_v2_runtime role is missing or unsafe';
                END IF;
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_auth_members membership
                    JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
                    JOIN pg_roles member_role ON member_role.oid = membership.member
                    WHERE granted_role.rolname = 'ctrl_v2_owner'
                      AND member_role.rolname = 'ctrl_v2_migrator'
                      AND NOT membership.admin_option
                      AND NOT membership.inherit_option
                      AND membership.set_option
                ) THEN
                    RAISE EXCEPTION 'ctrl_v2_migrator membership options are unsafe';
                END IF;
                IF pg_has_role('ctrl_v2_runtime', 'ctrl_v2_owner', 'MEMBER') THEN
                    RAISE EXCEPTION 'ctrl_v2_runtime must not inherit ctrl_v2_owner';
                END IF;

                IF pg_get_userbyid((SELECT datdba FROM pg_database WHERE datname = current_database()))
                   <> 'ctrl_v2_owner' THEN
                    RAISE EXCEPTION 'Database must be owned by ctrl_v2_owner';
                END IF;
                IF pg_get_userbyid((SELECT nspowner FROM pg_namespace WHERE nspname = 'public'))
                   <> 'ctrl_v2_owner' THEN
                    RAISE EXCEPTION 'public schema must be owned by ctrl_v2_owner';
                END IF;

                SELECT string_agg(c.relname, ', ' ORDER BY c.relname)
                  INTO invalid_objects
                  FROM pg_class c
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'public'
                   AND c.relkind IN ('r', 'p', 'S')
                   AND pg_get_userbyid(c.relowner) <> 'ctrl_v2_owner';
                IF invalid_objects IS NOT NULL THEN
                    RAISE EXCEPTION 'Objects not owned by ctrl_v2_owner: %', invalid_objects;
                END IF;

                SELECT string_agg(p.proname, ', ' ORDER BY p.proname)
                  INTO invalid_objects
                  FROM pg_proc p
                  JOIN pg_namespace n ON n.oid = p.pronamespace
                 WHERE n.nspname = 'public'
                   AND pg_get_userbyid(p.proowner) <> 'ctrl_v2_owner';
                IF invalid_objects IS NOT NULL THEN
                    RAISE EXCEPTION 'Functions not owned by ctrl_v2_owner: %', invalid_objects;
                END IF;
            END;
            $$
            """
        )
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("The production security boundary requires PostgreSQL")

    _assert_bootstrap_boundary()

    for table in TENANT_TABLES:
        op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'DROP POLICY IF EXISTS workspace_isolation ON "{table}"'))
        op.execute(
            sa.text(
                f'CREATE POLICY workspace_isolation ON "{table}" '
                "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')) "
                "WITH CHECK "
                "(workspace_id = NULLIF(current_setting('app.workspace_id', true), ''))"
            )
        )

    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                EXECUTE format(
                    'REVOKE ALL PRIVILEGES ON DATABASE %I FROM PUBLIC', current_database()
                );
                EXECUTE format(
                    'REVOKE ALL PRIVILEGES ON DATABASE %I FROM ctrl_v2_migrator, ctrl_v2_runtime',
                    current_database()
                );
                EXECUTE format(
                    'GRANT CONNECT ON DATABASE %I TO ctrl_v2_migrator, ctrl_v2_runtime',
                    current_database()
                );
            END;
            $$;

            REVOKE ALL PRIVILEGES ON SCHEMA public FROM PUBLIC;
            REVOKE ALL PRIVILEGES ON SCHEMA public FROM ctrl_v2_migrator, ctrl_v2_runtime;
            GRANT USAGE ON SCHEMA public TO ctrl_v2_runtime;

            REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM PUBLIC;
            REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM ctrl_v2_migrator;
            REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM ctrl_v2_runtime;
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
                TO ctrl_v2_runtime;
            REVOKE INSERT, UPDATE, DELETE ON TABLE alembic_version FROM ctrl_v2_runtime;

            REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC;
            REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM ctrl_v2_migrator;
            REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM ctrl_v2_runtime;
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ctrl_v2_runtime;

            REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
            REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public
                FROM ctrl_v2_migrator, ctrl_v2_runtime;

            ALTER DEFAULT PRIVILEGES FOR ROLE ctrl_v2_owner IN SCHEMA public
                REVOKE ALL PRIVILEGES ON TABLES FROM PUBLIC;
            ALTER DEFAULT PRIVILEGES FOR ROLE ctrl_v2_owner IN SCHEMA public
                REVOKE ALL PRIVILEGES ON SEQUENCES FROM PUBLIC;
            ALTER DEFAULT PRIVILEGES FOR ROLE ctrl_v2_owner IN SCHEMA public
                REVOKE ALL PRIVILEGES ON FUNCTIONS FROM PUBLIC;
            ALTER DEFAULT PRIVILEGES FOR ROLE ctrl_v2_owner IN SCHEMA public
                REVOKE ALL PRIVILEGES ON TYPES FROM PUBLIC;
            ALTER DEFAULT PRIVILEGES FOR ROLE ctrl_v2_owner IN SCHEMA public
                GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ctrl_v2_runtime;
            ALTER DEFAULT PRIVILEGES FOR ROLE ctrl_v2_owner IN SCHEMA public
                GRANT USAGE, SELECT ON SEQUENCES TO ctrl_v2_runtime;
            """
        )
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("The production security boundary requires PostgreSQL")
    op.execute(
        sa.text(
            """
            REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
                FROM ctrl_v2_runtime;
            REVOKE USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public FROM ctrl_v2_runtime;
            ALTER DEFAULT PRIVILEGES FOR ROLE ctrl_v2_owner IN SCHEMA public
                REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM ctrl_v2_runtime;
            ALTER DEFAULT PRIVILEGES FOR ROLE ctrl_v2_owner IN SCHEMA public
                REVOKE USAGE, SELECT ON SEQUENCES FROM ctrl_v2_runtime;
            """
        )
    )
