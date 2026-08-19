# CTRL v2

Greenfield Response Intelligence application. This repository contains Stage 0, the Stage 1
walking skeleton, and Stage 1.5 foundation validation. It has no runtime dependency on CTRL v1.

Implemented path:

`Workspace -> secure upload -> parsing -> Requirement -> Mapping -> EvidenceSpan ->
ComplianceDecision -> human approval -> Response snapshot -> deterministic XLSX`

AI extraction, automated mapping, retrieval, contradiction detection and capability bootstrap
are deliberately represented only by versioned contracts/ports. They are not implemented.

## Local setup

1. Set `POSTGRES_ADMIN_PASSWORD`, `POSTGRES_MIGRATOR_PASSWORD`,
   `POSTGRES_RUNTIME_PASSWORD`, `DATABASE_URL`, `OBJECT_STORAGE_ROOT`, and the authentication
   configuration in the local
   environment. The API `DATABASE_URL` must use `ctrl_v2_runtime`. For the separate Alembic
   process only, set `DATABASE_URL` to `ctrl_v2_migrator`; never expose that URL to the API.
2. Start PostgreSQL with `docker compose up -d postgres`.
3. Run `alembic upgrade head`.
4. Install the package with its development dependencies and run `pytest`.
5. Start the API with `ctrl-api`.

The test suite requires `TEST_DATABASE_ADMIN_URL`, `TEST_DATABASE_MIGRATOR_URL`, and
`TEST_DATABASE_RUNTIME_URL`. Tests create and drop an isolated PostgreSQL database, apply the
complete Alembic history as `ctrl_v2_migrator`, and exercise the application as
`ctrl_v2_runtime`. SQLite is not a supported runtime or migration backend.

Uploaded documents and exports are held behind `ObjectStorage`; the local adapter writes to a
private runtime directory that FastAPI never mounts as static content.

Production authentication validates signed OIDC tokens against an explicit issuer, audience and
JWKS trust boundary. Verified issuer/subject pairs resolve to persisted principals; every
workspace operation additionally requires an active membership with the necessary role. The
explicit development bypass is rejected whenever `ENVIRONMENT=production`.

Existing pre-authentication workspaces receive no implicit membership during migration. A
configured provisioning operator may use the one-time `bootstrap-admin` operation only while the
workspace has no active administrator; new workspaces automatically make their operator creator
the initial administrator.

Evaluation gold cases are always manually curated. See `evaluations/README.md`; the authoring CLI
can initialize, validate, and append reviewed cases, but cannot synthesize them.
