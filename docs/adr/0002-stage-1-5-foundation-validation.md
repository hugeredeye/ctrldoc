# ADR 0002: Stage 1.5 foundation validation

Status: accepted and implemented.

## Transaction boundary

Application use cases own transaction orchestration. `Stage1Workflow` depends on a
`UnitOfWorkFactory`; the UoW exposes the `Stage1Repository` port and explicit `commit`/`rollback`.
Domain and application modules cannot import SQLAlchemy or infrastructure. SQLAlchemy models,
queries, session lifecycle, and PostgreSQL workspace context are adapter responsibilities.

## PostgreSQL trust boundary

Compose bootstraps separate administrator and application roles. Runtime and migrations use a
non-superuser application role so forced RLS cannot be bypassed accidentally. Each tenant UoW
sets `app.workspace_id` with transaction-local scope before repository access. HTTP and worker
composition roots use the same boundary.

PostgreSQL integration tests recreate a clean isolated database, apply Alembic to head, and verify
RLS, the deferred positive-decision invariant, and immutability triggers in the database itself.
SQLite remains a fast feedback adapter only.

## Evaluation data

Gold datasets contain only manually curated real cases. The authoring interface supports an empty
versioned envelope, schema export, validation, and appending a complete reviewed case. It never
generates source requirements, labels, mappings, evidence, or outcomes.

## Explicitly excluded

Stage 1.5 adds no LLM, retrieval, embedding, vector database, agent, or capability-bootstrap
implementation. Those remain beyond the approved boundary.
