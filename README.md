# CTRL v2

Greenfield Response Intelligence application. This repository contains Stage 0, the Stage 1
walking skeleton, and Stage 1.5 foundation validation. It has no runtime dependency on CTRL v1.

Implemented path:

`Workspace -> secure upload -> parsing -> Requirement -> Mapping -> EvidenceSpan ->
ComplianceDecision -> human approval -> Response snapshot -> deterministic XLSX`

Stage 2 research code now includes an offline product-intelligence vertical slice: versioned atomic
extraction and evidence-verification contracts, controlled-catalog mapping, the existing retrieval
interfaces, deterministic provenance guardrails, conflict aggregation and a guarded compliance
proposal. It is not wired into the production API and never auto-approves a decision. Capability
bootstrap and autonomous processing remain unimplemented.

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

Uploaded documents and exports are held behind `ObjectStorage`; the local adapter writes
create-only content-bound objects to a private runtime directory that FastAPI never mounts as
static content. Every trusted read verifies both SHA-256 and byte size against immutable database
metadata. A mismatch fails closed with an object-integrity error.

Production authentication validates signed OIDC tokens against an explicit issuer, audience and
JWKS trust boundary. Verified issuer/subject pairs resolve to persisted principals; every
workspace operation additionally requires an active membership with the necessary role. The
explicit development bypass is rejected whenever `ENVIRONMENT=production`.

Existing pre-authentication workspaces receive no implicit membership during migration. A
configured provisioning operator may use the one-time `bootstrap-admin` operation only while the
workspace has no active administrator; new workspaces automatically make their operator creator
the initial administrator.

Production also requires explicit confirmation that the deployment provides encryption at rest
for PostgreSQL and the object-storage volume/backend. These configuration gates do not claim
application-layer encryption; verify the actual infrastructure before enabling them.

Evaluation gold cases are always manually curated. See `evaluations/README.md`; the authoring CLI
can initialize, validate, and append reviewed cases, but cannot synthesize them.

The public/synthetic Stage 2.4 demo can be run with `ctrl-intelligence-demo`. Its default adapters
are deterministic and dependency-free. Pass
`--semantic-config evaluations/config/semantic-retrieval-v1.json` to opt into the existing pinned
E5/BGE research stack. The separate real OpenAI smoke is explicit and research-only; see
`docs/stage2-product-intelligence.md`.

Stage 2.5 adds an official DeepSeek V4 Pro research adapter behind the same extractor/verifier
contracts. It is not production-wired and refuses confidential, restricted, personal, and customer
confidential classifications before serialization or network access. See
`docs/stage2-deepseek-provider.md` for the public-safe opt-in smoke procedure.

## Intelligence Workbench demo

The isolated frontend in `apps/web` presents the provider-independent CTRL review workflow using
only deterministic synthetic data. No backend or model connection is required:

```powershell
Set-Location C:\dev\ctrl-v2\apps\web
npm ci
npm run dev
```

Open `http://127.0.0.1:4173`. Run frontend checks with:

```powershell
npm run typecheck
npm run lint
npm test
npm run build
```

See `apps/web/README.md` for the demo-only trust boundary and production bundle preview command.
