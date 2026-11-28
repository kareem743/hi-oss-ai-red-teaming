# WorkOS AuthKit login — staged integration

The deployed Cloudflare Worker includes `src/workos.mjs` and the WorkOS routes, but **WorkOS remains disabled** until the credentials and allowlist have been configured. Password login is preserved until then.

## WorkOS setup

1. Create an application in the WorkOS dashboard and configure AuthKit (including verified email sign-in, and any desired Google, Microsoft or SSO providers).
2. Register this **exact redirect URI** in WorkOS: `https://brite-incident-discovery.kareem-rag-tools.workers.dev/auth/workos/callback`.
3. Configure the Cloudflare Worker environment securely:
   - `WORKOS_ENABLED` — set to `true` **only after** all settings below are ready and an authorized owner can sign in.
   - `WORKOS_CLIENT_ID` — WorkOS application Client ID (`client_...`).
   - `WORKOS_API_KEY` — server-side secret (`sk_...`), configure as a Cloudflare secret; never commit it or put it in a browser bundle.
   - `WORKOS_OWNER_EMAIL` — verified email used by the BRITE owner, matching the WorkOS identity exactly.
   - `WORKOS_REDIRECT_URI` — exact registered URI above.
4. Only an identity whose verified email matches `WORKOS_OWNER_EMAIL`, or an enabled email in `invited_users`, can access the application. Those invited users continue to have read-only access.
5. After validating a test sign-in and the existing incident review workflows, set `WORKOS_ENABLED=true`. With WorkOS enabled, password logins are rejected and existing password sessions no longer authorize the API.

## Routes

- `GET /api/auth-config` — safe public flag showing whether WorkOS is ready.
- `GET /auth/workos/start` — authorization-code / PKCE redirect to hosted AuthKit.
- `GET /auth/workos/callback` — verifies OAuth state, exchanges code server-side, checks verified email and BRITE allowlist, and creates a provider-scoped Cloudflare D1 session.

This stage does not create a WorkOS application, configure its credentials or prove a complete WorkOS sign-in; those steps require WorkOS account access. Keep password sign-in active until the end-to-end test succeeds. Signing out currently deletes the BRITE application's session; global WorkOS logout and account provisioning can be added separately.
