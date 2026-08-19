\set ON_ERROR_STOP on

\if :{?migrator_password}
\else
  \getenv migrator_password POSTGRES_MIGRATOR_PASSWORD
\endif
\if :{?runtime_password}
\else
  \getenv runtime_password POSTGRES_RUNTIME_PASSWORD
\endif
\if :{?migrator_password}
\else
DO $$ BEGIN RAISE EXCEPTION 'POSTGRES_MIGRATOR_PASSWORD is required'; END $$;
\endif
\if :{?runtime_password}
\else
DO $$ BEGIN RAISE EXCEPTION 'POSTGRES_RUNTIME_PASSWORD is required'; END $$;
\endif
\if :{?fail_after_ownership}
\else
  \set fail_after_ownership false
\endif

SELECT EXISTS (
    SELECT 1 FROM public.alembic_version WHERE version_num = '8d4f2a1c7b90'
) AS already_hardened \gset

\if :already_hardened
DO $$
DECLARE
    invalid_objects text;
    invalid_functions text;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname = 'ctrl_v2_owner' AND NOT rolcanlogin AND NOT rolsuper
          AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolinherit AND NOT rolbypassrls
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname = 'ctrl_v2_migrator' AND rolcanlogin AND NOT rolsuper
          AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolinherit AND NOT rolbypassrls
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname = 'ctrl_v2_runtime' AND rolcanlogin AND NOT rolsuper
          AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolinherit AND NOT rolbypassrls
    ) THEN
        RAISE EXCEPTION 'Existing hardened roles are missing or unsafe';
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
    ) OR pg_has_role('ctrl_v2_runtime', 'ctrl_v2_owner', 'MEMBER') THEN
        RAISE EXCEPTION 'Existing hardened role membership is unsafe';
    END IF;
    IF pg_get_userbyid((SELECT datdba FROM pg_database WHERE datname = current_database()))
       <> 'ctrl_v2_owner'
       OR pg_get_userbyid((SELECT nspowner FROM pg_namespace WHERE nspname = 'public'))
       <> 'ctrl_v2_owner' THEN
        RAISE EXCEPTION 'Existing database or schema ownership is unsafe';
    END IF;
    SELECT string_agg(c.relname, ', ' ORDER BY c.relname)
      INTO invalid_objects
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'S')
       AND pg_get_userbyid(c.relowner) <> 'ctrl_v2_owner';
    IF invalid_objects IS NOT NULL THEN
        RAISE EXCEPTION 'Objects not owned by ctrl_v2_owner: %', invalid_objects;
    END IF;
    SELECT string_agg(p.proname, ', ' ORDER BY p.proname)
      INTO invalid_functions
      FROM pg_proc p
      JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = 'public'
       AND pg_get_userbyid(p.proowner) <> 'ctrl_v2_owner';
    IF invalid_functions IS NOT NULL THEN
        RAISE EXCEPTION 'Functions not owned by ctrl_v2_owner: %', invalid_functions;
    END IF;
    IF (
        SELECT count(*) FROM pg_policies policies
        JOIN pg_class tables ON tables.relname = policies.tablename
        JOIN pg_namespace schemas
          ON schemas.oid = tables.relnamespace AND schemas.nspname = policies.schemaname
        WHERE policies.schemaname = 'public'
          AND policies.policyname = 'workspace_isolation'
          AND tables.relrowsecurity AND tables.relforcerowsecurity
    ) <> 26 THEN
        RAISE EXCEPTION 'Existing hardened database does not have 26 FORCE RLS policies';
    END IF;
    IF (
        SELECT count(*) FROM pg_trigger
        WHERE NOT tgisinternal AND tgenabled IN ('O', 'A')
          AND tgname IN (
              'document_versions_immutable', 'approved_decisions_immutable',
              'approved_decision_requires_evidence', 'approved_decision_links_immutable',
              'response_snapshot_immutable'
          )
    ) <> 5 THEN
        RAISE EXCEPTION 'Existing hardened database is missing required triggers';
    END IF;
    IF has_database_privilege('ctrl_v2_runtime', current_database(), 'TEMP')
       OR has_schema_privilege('ctrl_v2_runtime', 'public', 'CREATE')
       OR has_table_privilege('ctrl_v2_runtime', 'public.documents', 'TRUNCATE')
       OR has_table_privilege('ctrl_v2_runtime', 'public.documents', 'TRIGGER') THEN
        RAISE EXCEPTION 'Existing runtime privileges are unsafe';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_database database
        CROSS JOIN LATERAL aclexplode(
            COALESCE(database.datacl, acldefault('d', database.datdba))
        ) acl
        WHERE database.datname = current_database() AND acl.grantee = 0
          AND acl.privilege_type IN ('CONNECT', 'TEMPORARY')
    ) OR EXISTS (
        SELECT 1
        FROM pg_namespace schema
        CROSS JOIN LATERAL aclexplode(
            COALESCE(schema.nspacl, acldefault('n', schema.nspowner))
        ) acl
        WHERE schema.nspname = 'public' AND acl.grantee = 0
          AND acl.privilege_type IN ('USAGE', 'CREATE')
    ) OR EXISTS (
        SELECT 1
        FROM pg_class object
        JOIN pg_namespace schema ON schema.oid = object.relnamespace
        CROSS JOIN LATERAL aclexplode(object.relacl) acl
        WHERE schema.nspname = 'public' AND acl.grantee = 0
    ) OR EXISTS (
        SELECT 1
        FROM pg_proc function
        JOIN pg_namespace schema ON schema.oid = function.pronamespace
        CROSS JOIN LATERAL aclexplode(
            COALESCE(function.proacl, acldefault('f', function.proowner))
        ) acl
        WHERE schema.nspname = 'public' AND acl.grantee = 0
    ) THEN
        RAISE EXCEPTION 'Existing PUBLIC privileges are unsafe';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'ctrl_v2_app' AND rolcanlogin
    ) THEN
        RAISE EXCEPTION 'Legacy ctrl_v2_app login is still enabled';
    END IF;
END;
$$;
\echo 'Database is already hardened at 8d4f2a1c7b90; validation passed; no changes made.'
\quit
\endif

BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '5min';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = current_user AND rolsuper) THEN
        RAISE EXCEPTION 'Stage 1.5 transition requires a PostgreSQL superuser';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ctrl_v2_app') THEN
        RAISE EXCEPTION 'Legacy role ctrl_v2_app does not exist';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_database database
        JOIN pg_roles role ON role.oid = database.datdba
        WHERE role.rolname = 'ctrl_v2_app' AND database.datname <> current_database()
    ) OR EXISTS (
        SELECT 1
        FROM pg_tablespace tablespace
        JOIN pg_roles role ON role.oid = tablespace.spcowner
        WHERE role.rolname = 'ctrl_v2_app'
    ) THEN
        RAISE EXCEPTION 'Legacy ctrl_v2_app owns shared objects outside this database';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.alembic_version WHERE version_num = '4b6c3a9e2d11'
    ) THEN
        RAISE EXCEPTION 'Expected Stage 1.5 Alembic revision 4b6c3a9e2d11';
    END IF;
END;
$$;

SELECT 'CREATE ROLE ctrl_v2_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
       'NOINHERIT NOBYPASSRLS'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ctrl_v2_owner') \gexec
SELECT 'CREATE ROLE ctrl_v2_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
       'NOINHERIT NOBYPASSRLS'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ctrl_v2_migrator') \gexec
SELECT 'CREATE ROLE ctrl_v2_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
       'NOINHERIT NOBYPASSRLS'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ctrl_v2_runtime') \gexec

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname = 'ctrl_v2_owner' AND NOT rolcanlogin AND NOT rolsuper
          AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolinherit AND NOT rolbypassrls
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname = 'ctrl_v2_migrator' AND rolcanlogin AND NOT rolsuper
          AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolinherit AND NOT rolbypassrls
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname = 'ctrl_v2_runtime' AND rolcanlogin AND NOT rolsuper
          AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolinherit AND NOT rolbypassrls
    ) THEN
        RAISE EXCEPTION 'Existing target role attributes are unsafe';
    END IF;
END;
$$;

ALTER ROLE ctrl_v2_migrator PASSWORD :'migrator_password';
ALTER ROLE ctrl_v2_runtime PASSWORD :'runtime_password';
GRANT ctrl_v2_owner TO ctrl_v2_migrator;
DO $$
BEGIN
    IF pg_has_role('ctrl_v2_runtime', 'ctrl_v2_owner', 'MEMBER') THEN
        EXECUTE 'REVOKE ctrl_v2_owner FROM ctrl_v2_runtime';
    END IF;
END;
$$;

REASSIGN OWNED BY ctrl_v2_app TO ctrl_v2_owner;

DO $$
DECLARE
    object_record record;
BEGIN
    EXECUTE format('ALTER DATABASE %I OWNER TO ctrl_v2_owner', current_database());
    ALTER SCHEMA public OWNER TO ctrl_v2_owner;

    FOR object_record IN
        SELECT c.relname, c.relkind
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'S')
    LOOP
        IF object_record.relkind = 'S' THEN
            EXECUTE format(
                'ALTER SEQUENCE public.%I OWNER TO ctrl_v2_owner', object_record.relname
            );
        ELSE
            EXECUTE format(
                'ALTER TABLE public.%I OWNER TO ctrl_v2_owner', object_record.relname
            );
        END IF;
    END LOOP;

    FOR object_record IN
        SELECT p.proname, pg_get_function_identity_arguments(p.oid) AS arguments
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public'
    LOOP
        EXECUTE format(
            'ALTER FUNCTION public.%I(%s) OWNER TO ctrl_v2_owner',
            object_record.proname,
            object_record.arguments
        );
    END LOOP;
END;
$$;

\if :fail_after_ownership
DO $$
BEGIN
    RAISE EXCEPTION 'Intentional transition failpoint after ownership transfer';
END;
$$;
\endif

DO $$
BEGIN
    EXECUTE format('REVOKE ALL PRIVILEGES ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format(
        'REVOKE ALL PRIVILEGES ON DATABASE %I '
        'FROM ctrl_v2_app, ctrl_v2_migrator, ctrl_v2_runtime', current_database()
    );
    EXECUTE format(
        'GRANT CONNECT ON DATABASE %I TO ctrl_v2_migrator, ctrl_v2_runtime',
        current_database()
    );
    EXECUTE format(
        'ALTER ROLE ctrl_v2_owner IN DATABASE %I SET search_path TO pg_catalog, public',
        current_database()
    );
    EXECUTE format(
        'ALTER ROLE ctrl_v2_migrator IN DATABASE %I SET search_path TO pg_catalog, public',
        current_database()
    );
    EXECUTE format(
        'ALTER ROLE ctrl_v2_runtime IN DATABASE %I SET search_path TO pg_catalog, public',
        current_database()
    );
END;
$$;

REVOKE ALL PRIVILEGES ON SCHEMA public
    FROM PUBLIC, ctrl_v2_app, ctrl_v2_migrator, ctrl_v2_runtime;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public
    FROM PUBLIC, ctrl_v2_app, ctrl_v2_migrator, ctrl_v2_runtime;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public
    FROM PUBLIC, ctrl_v2_app, ctrl_v2_migrator, ctrl_v2_runtime;
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public
    FROM PUBLIC, ctrl_v2_app, ctrl_v2_migrator, ctrl_v2_runtime;

ALTER DEFAULT PRIVILEGES FOR ROLE ctrl_v2_owner IN SCHEMA public
    REVOKE ALL PRIVILEGES ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ctrl_v2_owner IN SCHEMA public
    REVOKE ALL PRIVILEGES ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ctrl_v2_owner IN SCHEMA public
    REVOKE ALL PRIVILEGES ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ctrl_v2_owner IN SCHEMA public
    REVOKE ALL PRIVILEGES ON TYPES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ctrl_v2_app IN SCHEMA public
    REVOKE ALL PRIVILEGES ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ctrl_v2_app IN SCHEMA public
    REVOKE ALL PRIVILEGES ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ctrl_v2_app IN SCHEMA public
    REVOKE ALL PRIVILEGES ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ctrl_v2_app IN SCHEMA public
    REVOKE ALL PRIVILEGES ON TYPES FROM PUBLIC;

GRANT USAGE ON SCHEMA public TO ctrl_v2_runtime;
ALTER ROLE ctrl_v2_app NOLOGIN PASSWORD NULL NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOBYPASSRLS;

COMMIT;
