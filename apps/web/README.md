# CTRL Intelligence Workbench v0

Desktop-first product demo for evidence-backed requirement assessment. The frontend is an
independent Vite/React/TypeScript application and uses only deterministic synthetic fixtures from
`src/data/demoCases.ts`. It does not call the CTRL API, OpenAI, DeepSeek, or any other external
service. Human actions update local component state only.

## Run locally

Node.js 20 or 22 is recommended.

```powershell
Set-Location C:\dev\ctrl-v2\apps\web
npm ci
npm run dev
```

Open `http://127.0.0.1:4173`.

The backend is not required for this deterministic UI demo. To run it separately, use the root
repository setup and start `ctrl-api` after PostgreSQL and Alembic are ready.

## Quality gates

```powershell
Set-Location C:\dev\ctrl-v2\apps\web
npm run typecheck
npm run lint
npm test
npm run build
```

The production bundle is generated in ignored `apps/web/dist/`. To inspect that bundle locally:

```powershell
npm run preview
```

## Scope boundary

This stage implements the Assessment Workbench surface only. Approval, escalation, evidence
search, and decision edits are explicitly non-authoritative demo interactions. Production auth,
RLS, storage, policy, and HumanReview writes are unchanged.
