# Worker composition root

Reserved for the durable straight-through worker. Stage 1 deliberately performs the manual
walking-skeleton commands synchronously and does not implement LLM or retrieval jobs.

The worker composition root must use the same application `Stage1Workflow` and
`UnitOfWorkFactory` port as HTTP. Every job must carry a workspace id; the SQLAlchemy adapter sets
`app.workspace_id` transaction-locally before any repository call. A worker must never reuse a
global or unset tenant context.
