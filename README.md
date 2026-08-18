# CTRL v2

Greenfield Response Intelligence application. This repository contains Stage 0, the Stage 1
walking skeleton, and Stage 1.5 foundation validation. It has no runtime dependency on CTRL v1.

Implemented path:

`Workspace -> secure upload -> parsing -> Requirement -> Mapping -> EvidenceSpan ->
ComplianceDecision -> human approval -> Response snapshot -> deterministic XLSX`

AI extraction, automated mapping, retrieval, contradiction detection and capability bootstrap
are deliberately represented only by versioned contracts/ports. They are not implemented.

## Local setup

1. Set `POSTGRES_ADMIN_PASSWORD`, `POSTGRES_APP_PASSWORD`, `DATABASE_URL`, and
   `OBJECT_STORAGE_ROOT` in the local environment. `DATABASE_URL` must use the non-superuser
   application role, never the Compose bootstrap administrator.
2. Start PostgreSQL with `docker compose up -d postgres`.
3. Run `alembic upgrade head`.
4. Install the package with its development dependencies and run `pytest`.
5. Start the API with `ctrl-api`.

The PostgreSQL suite requires two runtime-only URLs: `TEST_DATABASE_URL` for the non-superuser
application role and `TEST_DATABASE_ADMIN_URL` for creating and dropping the isolated test
database. Run it with `pytest tests/postgres -vv`. SQLite tests remain useful for fast feedback,
but are not accepted as validation of RLS, deferred constraints, or PostgreSQL triggers.

Uploaded documents and exports are held behind `ObjectStorage`; the local adapter writes to a
private runtime directory that FastAPI never mounts as static content.

Workspace creation returns a high-entropy access token once. It is stored only as a SHA-256
digest and is a deliberately small Stage 1 authentication adapter, not the future identity/RBAC
model.

Evaluation gold cases are always manually curated. See `evaluations/README.md`; the authoring CLI
can initialize, validate, and append reviewed cases, but cannot synthesize them.
