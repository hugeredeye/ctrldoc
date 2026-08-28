# CTRL DOC landing and Intelligence Workbench

The independent Vite/React/TypeScript frontend serves the Russian CTRL DOC brand landing at `/`,
the short guided public demo at `/demo/guided`, and the preserved Intelligence Workbench at
`/demo`. All three surfaces use only deterministic synthetic fixtures and local assets. They do not
call the CTRL API, OpenAI, DeepSeek, or any other external service. Human actions update local
component state only. The public demo does not accept arbitrary text or document uploads.

The landing self-hosts Onest and IBM Plex Mono WOFF2 files from their official OFL repositories.
Exact provenance, revisions, checksums, and license locations are recorded in
`public/fonts/THIRD_PARTY_FONTS.md`.

## Run locally

Node.js 20 or 22 is recommended.

```powershell
Set-Location <repo-worktree>\apps\web
npm ci
npm run dev
```

Open `http://127.0.0.1:4173/` for the landing, `http://127.0.0.1:4173/demo/guided` for
the public guided flow, or `http://127.0.0.1:4173/demo` for the full Workbench.

The backend is not required for this deterministic UI demo. To run it separately, use the root
repository setup and start `ctrl-api` after PostgreSQL and Alembic are ready.

## Quality gates

```powershell
Set-Location <repo-worktree>\apps\web
npm run typecheck
npm run lint
npm test
npm run build
```

The production bundle is generated in ignored `apps/web/dist/`. To inspect that bundle locally:

```powershell
npm run preview
```

## Deploy with Cloudflare Workers Static Assets

Create or connect the Cloudflare Worker named `ctrldoc`, then enter these exact values under
**Settings → Builds**:

- Production branch: `product/public-launch-v1`
- Root directory: `apps/web`
- Build command: `npm run build`
- Deploy command: `npx wrangler deploy`
- Build variables and secrets: none

Vite writes the production bundle to `dist`. The `wrangler.jsonc` file deploys `./dist` as Workers
Static Assets. Its `single-page-application` fallback serves `index.html` for browser navigation to
unmatched asset paths, so `/demo` and `/demo/guided` work when opened directly or refreshed.

No Worker entry point, API handler, runtime binding, secret, environment variable, or legacy
Cloudflare Pages configuration is required for this static-only deployment.

## Scope boundary

The landing's product reconstruction and Workbench use synthetic-safe data. Approval, escalation,
evidence search, decision edits, and access-request feedback are explicitly non-authoritative local
interactions. Production auth, RLS, storage, policy, and HumanReview writes are unchanged.

## Pilot request handoff

The pilot form never pretends that a server accepted a request. By default it prepares a readable
application that the visitor can review and copy, and explicitly states that automatic submission
is not connected. If a monitored mailbox is available, set `VITE_PILOT_EMAIL` at build time; the
prepared state then offers an `Открыть в почте` link, and the visitor still sends the message from
their own mail client.

Before a production launch, CTRL must provision and monitor that contact channel (or deliberately
implement an approved submission service) and publish the corresponding data-handling notice. No
submission endpoint or mailbox address is invented in this frontend.
