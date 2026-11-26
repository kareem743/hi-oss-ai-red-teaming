# BRITE red-teaming · Cloudflare pilot

A new pilot implementation inspired by the Humane Intelligence open-source red-teaming workflow, based on its actual repository and BRITE's stated design. This is not a complete port of the upstream codebase. See [parity and gaps](docs/PARITY.md).

## Included

- FastAPI routes for administrator, volunteer and reviewer workflows; React/Vite frontend with provisional BRITE styling.
- D1 schema: approved users, campaign memberships, scenarios, tasks, model registry, conversations, turns, task completions, findings, review verdicts and audit events.
- Server-side authorization: Access-authenticated email, active user, role, campaign membership, conversation ownership. No client-supplied identity headers.
- OpenAI and Anthropic SSE adapters, full completed prompt/response storage, model configuration snapshot, one pending turn per conversation and timeout cleanup.
- Training acknowledgment, urgent flagging, reviewer feedback, aggregate counts, bounded JSON download.
- No Docker, Postgres, Redis, Celery, or standalone proxy. No storage service beyond D1 is required for the small pilot.

## Local demo (actual tested API, mock model)

Python 3.13+, Node 22+ recommended. From this directory:

```
python -m venv .venv
source .venv/bin/activate
pip install -e . pytest uvicorn
python -m pytest -q
python local_demo.py
```

In a second terminal:

```
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Local demo binds to loopback and fixes the identity server-side, using `admin@example.org` by default. It is **not** Cloudflare Access, and the mock output is explicitly labeled synthetic. Do not deploy `local_demo.py` or `tests/`. As admin create `volunteer@example.org` and `reviewer@example.org`, a campaign, scenario, task and target model, then assign the users and activate the campaign. To switch roles, stop the local API and start it with `DEMO_USER=volunteer@example.org python local_demo.py` or `DEMO_USER=reviewer@example.org python local_demo.py`. Reload the browser. SQLite persists locally in `demo.sqlite`. To reset, stop local servers and remove that local file only. No real model API calls occur in this demo.

## Cloudflare deployment checklist (database prepared; application not deployed)

The provided `cloudflare.config.ts` follows the Cloudflare `cf` project configuration shape, using the `python_workers` compatibility flag and D1 binding. Treat the config as a candidate until validated by the installed Cloudflare CLI. Cloudflare's Python Workers runtime, context/ASGI adapter, HTTPX streaming, FFI result conversion and scheduling must all pass real smoke tests. Do not enable volunteers until validation is complete.

1. Install and authenticate the Cloudflare `cf` CLI according to [current installation instructions](https://developers.cloudflare.com/cf/). Confirm the installed version supports Python projects, the `cf/config` module and the config's keys. Run `cf cli search` for exact syntax of deployment, secrets, migration and routing commands; these can change with the CLI version. The Python project depends on FastAPI, HTTPX and Pydantic; ensure the current Python Workers toolchain packages these successfully. If needed, adjust packaging to the current official FastAPI template.
2. For the existing BRITE pilot account, a new D1 database named `brite-redteam-db` has already been created and `0001_pilot.sql` applied using the D1 API. The migration is recorded in `d1_migrations`; the 12 application tables and seven named indexes were verified, with no foreign-key violations and no user data. Do not recreate it or apply the initial schema again manually. For a separate account, create a new database and apply the migration normally. [D1 docs](https://developers.cloudflare.com/d1/).
3. Seed a real approved administrator through the authenticated D1 dashboard, replacing the placeholder email with the exact Access email:

   ```sql
   INSERT INTO users(email,role,trained) VALUES('ADMIN_EMAIL_HERE','admin',1);
   ```

   Never seed `admin@example.org` in production. Seed only a verified BRITE administrator email. Use D1 binding `DB` in the API configuration.
4. Set `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` and `APP_ORIGIN` using Cloudflare secrets. `APP_ORIGIN` must match the HTTPS public origin exactly, e.g. `https://redteam.example.org` (no trailing slash). Configure both secrets if required by the CLI; to use only one provider, remove the unused secret binding in config and do not register that provider. Set a low provider budget and choose the exact model ID permitted by your account. Do not put credentials in `.env` committed to Git or React variables.
5. Dry-run the API deployment, then deploy the Python Worker with the current CLI. Verify 128 MB memory/boot constraints and CPU budget in the actual Worker runtime. `ctx.access.getIdentity()` must supply verified identity for the directly routed API Worker. If it is absent, the API fails closed. No unverified email-header fallback is provided. [Python Workers](https://developers.cloudflare.com/workers/languages/python/), [Access integration](https://developers.cloudflare.com/workers/configuration/cloudflare-access/), [D1 Python example](https://developers.cloudflare.com/d1/examples/query-d1-from-python-workers/).
6. Build the frontend: `cd frontend && npm ci` if a lockfile has been generated (otherwise `npm install`), then `npm run build`. Deploy `dist/` as an asset-only Worker (`cf deploy ./dist` if supported by your CLI). The frontend uses same-origin `/api` and does not contain keys. Configure the frontend Worker on a dedicated Cloudflare-managed hostname and route `/api/*` on that same hostname directly to the API Worker, preserving Access context. Do not point at another BRITE site's domain or overwrite its routes. Confirm the SPA and API route coexist and do not expose authenticated responses via caches.
7. Configure Cloudflare Access on the **entire hostname**, including API routes, with a restrictive email allowlist or approved identity-provider group. Disable unneeded workers.dev endpoints/previews or protect them with equivalent policy. An approved Access user also needs a D1 active user and campaign assignment. Direct production calls without verified identity must return 401/403. Test Access cookies, allowed/disallowed users, correct `APP_ORIGIN`, CSRF behavior, and logout/revocation. Never use a permissive Access bypass policy.
8. Confirm the cron trigger runs every 15 minutes and reaps stale turns. Verify audit records, logs, D1 backups/recovery and costs. Add a retention policy and cap API spend before enrolling real volunteers.
9. Run the acceptance matrix below with actual separate users and real provider calls on synthetic data only. If Python runtime compatibility or free CPU budget is inadequate, first profile on the paid Workers plan; if incompatibility persists, port the backend adapter or API to TypeScript. Paid does not fix every packaging or startup limit.

**Deployment status (2026-11-26):** the pilot is committed on the fork branch `brite/cloudflare-pilot`, under `brite-cloudflare/`. The dedicated D1 database and migration are ready; neither Worker has been deployed. Cloudflare Access is not enabled on the connected account (Access API returned `access.api.error.not_enabled`). Enable Access through the Cloudflare dashboard before deploying or granting volunteer access. Choose the hostname, verify the administrator identity, and configure the provider keys privately. No users, research records, or provider keys were written. npm installation was blocked by DNS in the local build environment, so the frontend bundle and browser UI were not built or tested there. The Cloudflare Python toolchain and identity context remain unverified. The API integration test uses a SQLite test double; the live D1 schema was separately verified. No plan upgrade or paid AI call was performed.

## Acceptance matrix

| Step | Expected result |
|---|---|
| Anonymous or unapproved user | Access denied, no research data |
| Admin creates accounts and campaign | Campaign is draft until scenario and model are present |
| Volunteer without training or campaign membership | Cannot start testing |
| Volunteer acknowledges training | Can start an active assigned scenario |
| Send a synthetic prompt | SSE text appears; complete response persisted and visible after reload |
| Simulated provider failure/disconnection | Failed or pending status; cron eventually marks stale turns failed |
| Try other volunteer's conversation | Not accessible |
| Mark task complete and flag response | Finding contains explanation, expected behavior, severity, turn link |
| Urgent finding | Appears in scoped reviewer queue immediately; contact supervisor manually |
| Submit conversation | Requires completed turn and all tasks; prevents additional turns |
| Independent reviewer verdict | Volunteer sees feedback; duplicate review rejected |
| Admin export | JSON with prompts, complete responses, model snapshot, findings, reviews, tasks |
| Admin removes membership | Former member loses campaign access |
| Monitor worker and D1 metrics | No resource limit failures; budget measured before selecting tier |

## Cost and scope

Initial target $0–$5/month for a small pilot, subject to actual Worker CPU, request and D1 usage. Budget for $5/month rather than guarantee free operation. Provider inference billed separately; larger exports, mail, storage and queues may incur charges. [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/) and [D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/).

## Fork and integrate

The pilot lives alongside upstream source on the fork's `brite/cloudflare-pilot` branch under `brite-cloudflare/`. The original `main` branch and the upstream repository remain unchanged. The fork is public; never commit credentials, research records, or private configuration. If private development is required, use an approved private repository while retaining required upstream license and attribution. A pull request should document parity gaps and should not be merged or deployed to an existing site before validation.

## Validation performed

`python -m pytest -q`: 1 comprehensive end-to-end test passed (multiple positive and negative API assertions). `python -m compileall`: passed. JSX transpilation using installed TypeScript compiler: syntax passed. npm install: blocked (DNS EAI_AGAIN). No live deploy, no provider network calls, no browser screenshot claimed.

## GitHub build verification

The dedicated BRITE CI workflow checks the Python integration test and builds the React/Vite frontend in GitHub Actions. It does not deploy resources, access production secrets, or make AI provider calls. Forks may need Actions enabled explicitly; confirm the workflow run results before treating the build as verified.
