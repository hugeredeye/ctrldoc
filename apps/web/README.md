# CTRL DOC landing and Intelligence Workbench

The independent Vite/React/TypeScript frontend serves the Russian CTRL DOC brand landing at `/`,
the short guided public demo at `/demo/guided`, and the preserved Intelligence Workbench at
`/demo`. All three surfaces use only deterministic synthetic fixtures and local assets. They do not
call the CTRL API, OpenAI, DeepSeek, or any model service. Human demo actions update local component
state only. The public demo does not accept arbitrary text or document uploads. The only production
network action is the landing's same-origin pilot application endpoint described below.

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
unmatched asset paths, so `/demo` and `/demo/guided` work when opened directly or refreshed. Static
requests bypass the Worker; only `/api/*` runs the Worker first. No legacy Cloudflare Pages
configuration, secret, or environment variable is used.

The deployed configuration is:

- Worker name: `ctrldoc`
- Worker entry point: `./worker/index.ts`
- Static asset binding: `ASSETS`
- Static asset directory: `./dist`
- SPA fallback: `single-page-application`
- Worker-first routes: `/api/*`
- Email binding: `PILOT_EMAIL`
- Allowed sender: `pilot@ctrldoc.tech`
- Recipient: the single verified Cloudflare Destination Address declared in `wrangler.jsonc`
- Worker-only recipient variable: `PILOT_DESTINATION_ADDRESS`

## Scope boundary

The landing's product reconstruction and Workbench use synthetic-safe data. Approval, escalation,
evidence search, and decision edits are explicitly non-authoritative local interactions. Production
auth, RLS, storage, policy, and HumanReview writes are unchanged. No product backend or
document-processing API is exposed by this Worker.

## Pilot application delivery

The form sends JSON to the same-origin `POST /api/pilot` endpoint. The Worker validates the request,
then awaits Cloudflare's native `send_email` binding before returning success. It sends one plain-text
message from `pilot@ctrldoc.tech` directly to the verified Destination Address configured for the
binding. The Worker reads that recipient from deployment configuration; it is never included in the
frontend bundle or public UI. If Cloudflare rejects delivery, the form reports an error and keeps the
public `mailto:pilot@ctrldoc.tech` fallback visible.

The endpoint accepts only `name`, `email`, `company`, `scenario`, and the hidden `website` honeypot.
It rejects oversized or malformed bodies, unsupported content types, unknown fields, invalid email
addresses, and scenarios outside the fixed list. Tests replace the email binding with a fake; they do
not send real messages.

Before the first production deployment, confirm that `PILOT_EMAIL.destination_address` and the
Worker-only `PILOT_DESTINATION_ADDRESS` value in `wrangler.jsonc` match the verified Cloudflare
Destination Address. The public Email Routing alias must not be used as the notification recipient.
Keep dashboard build variables and secrets empty; `wrangler.jsonc` is the binding source of truth.
