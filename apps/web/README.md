# CTRL DOC landing and Intelligence Workbench

The independent Vite/React/TypeScript frontend serves the Russian CTRL DOC brand landing at `/`
and the preserved desktop-first Intelligence Workbench demo at `/demo`. Both surfaces use only
deterministic synthetic fixtures and local assets. They do not call the CTRL API, OpenAI, DeepSeek,
or any other external service. Human actions update local component state only.

The landing self-hosts Onest and IBM Plex Mono WOFF2 files from their official OFL repositories.
Exact provenance, revisions, checksums, and license locations are recorded in
`public/fonts/THIRD_PARTY_FONTS.md`.

## Run locally

Node.js 20 or 22 is recommended.

```powershell
Set-Location C:\dev\ctrl-v2\apps\web
npm ci
npm run dev
```

Open `http://127.0.0.1:4173/` for the landing or `http://127.0.0.1:4173/demo` for the Workbench.

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

The landing's product reconstruction and Workbench use synthetic-safe data. Approval, escalation,
evidence search, decision edits, and access-request feedback are explicitly non-authoritative local
interactions. Production auth, RLS, storage, policy, and HumanReview writes are unchanged.
