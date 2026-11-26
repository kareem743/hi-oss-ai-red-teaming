# BRITE live pilot release

The full Python/FastAPI application and compiled React bundle were uploaded on 2026-11-26 to the dedicated `brite-redteam-api` Worker. The D1 database, administrator-only Cloudflare Access policy, and 15-minute cleanup Cron Trigger are configured. Cloudflare accepted the packaged release and its startup validation. The successful build is run 45818956879 (commit cbf31aab205aebcfcbf4e2051ec52fee0c86ee9c).

Portal: https://brite-redteam-api.kareem-rag-tools.workers.dev/

## Deployment adaptation

The normal Workers Static Assets upload requires session-specific authorization not supported by the connected Cloudflare API operation. As a pilot workaround, the same compiled React files are embedded as gzip/base64 content in a generated `src/ui_assets.py` module. The deployed root `entry.py` follows `entry_deployed.py`, and the original FastAPI routes and D1 schema are unchanged. This is not a change to TypeScript or a rewrite of the API. The initial plan to serve static assets through the dedicated asset service remains desirable after Cloudflare's Git integration or a scoped deployment token is configured.

To reproduce the release, unpack the successful CI artifact, copy `entry_deployed.py` to `entry.py` at the module root, and generate `src/ui_assets.py` with `python build_ui_assets.py frontend/dist src/ui_assets.py`. Use the original packaged Python dependencies and the Workers multipart upload API with root entry module `entry.py`, Python compatibility flag, D1 binding, verified Access issuer/audience and application origin. Do not commit generated assets, build dependencies or credentials. The one-time transfer used only public build artifacts; the temporary D1 staging table was removed after the upload.

## Remaining acceptance checks

No model provider credentials were configured. Sign in with the approved administrator email and OTP, verify the live application and role-scoped API, then configure the provider key(s) as Worker secrets. Test synthetic conversations, independent reviewer and volunteer accounts, exports, live D1 persistence, and resource limits before granting volunteers access. Cloudflare's deployment validation reported a startup time of 3801 ms; actual request latency and CPU use are not yet measured. No paid-plan upgrade was requested. The live HTTP smoke workflow checks the unauthenticated edge only; it does not prove an authenticated workflow works.
