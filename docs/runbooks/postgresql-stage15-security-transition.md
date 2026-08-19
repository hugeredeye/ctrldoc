# PostgreSQL Stage 1.5 security transition

This runbook upgrades an existing database at Alembic revision `4b6c3a9e2d11` from the
legacy `ctrl_v2_app` ownership model to the production owner/migrator/runtime boundary. It does
not apply to a clean database; clean databases use `deploy/postgres/init` followed by the full
Alembic history.

## Preconditions

- Stop the API and every worker that uses the target database.
- Confirm PostgreSQL 16 and Alembic revision `4b6c3a9e2d11`.
- Confirm the legacy and target CTRL role names are dedicated to this CTRL deployment. The
  transition refuses to run when `ctrl_v2_app` owns another database or a tablespace.
- Take and verify a deployment-specific database backup before the maintenance window.
- Obtain a cluster administrator connection and independently injected passwords for
  `ctrl_v2_migrator` and `ctrl_v2_runtime`.
- Run from the exact release containing revision `8d4f2a1c7b90`.

## Existing database transition

Run `deploy/postgres/transition/upgrade-stage15-to-production-roles.sql` as the cluster
administrator. The script reads `POSTGRES_MIGRATOR_PASSWORD` and
`POSTGRES_RUNTIME_PASSWORD` from the psql process environment without placing either secret in
the psql command line. The script:

1. validates the legacy Alembic head and administrator authority;
2. creates and validates the three production roles;
3. grants the migrator explicit `SET ROLE ctrl_v2_owner` ability with no inherited owner rights;
4. transfers database, schema, table, sequence, and function ownership in one transaction;
5. revokes legacy and PUBLIC access, disables login for `ctrl_v2_app`, pins `search_path`, and
   grants only database connection to the migrator/runtime;
6. commits only if every statement succeeds.

The passwords must come from the deployment secret injector, not a repository file, command
argument, or shell history:

```powershell
psql $env:CTRL_ADMIN_DATABASE_URL `
  --set=fail_after_ownership=false `
  --file=deploy/postgres/transition/upgrade-stage15-to-production-roles.sql
```

Do not start the API yet. Run Alembic with only the migrator credential:

```powershell
$env:DATABASE_URL = $env:CTRL_MIGRATOR_DATABASE_URL
python -m alembic upgrade head
python -m alembic current
```

Then start the API with only `CTRL_RUNTIME_DATABASE_URL` exposed as `DATABASE_URL`. Startup
readiness validates the runtime role, ownership, expected revision, all 26 forced RLS policies,
and all five invariant triggers.

## Failure and retry behavior

- Any error before the admin transaction commits rolls back role creation, password changes,
  ownership transfer, and grants together.
- If the admin transaction commits but Alembic fails, the database remains unavailable to the
  API because the runtime readiness check rejects the old revision or missing access. Fix the
  migration problem and rerun Alembic with the migrator credential.
- Rerunning the admin script at revision `4b6c3a9e2d11` safely reapplies the transition.
- Rerunning it at revision `8d4f2a1c7b90` performs strict role, ownership, RLS, trigger, and
  privilege validation and exits without changes. Validation failure is fatal.
- `fail_after_ownership=true` is a rehearsal-only failpoint that raises inside the transaction;
  never set it in a real transition.

The disabled legacy `ctrl_v2_app` role is retained so existing ownership references cannot be
silently orphaned. Remove it only in a later, separately rehearsed maintenance change after
catalog verification.
