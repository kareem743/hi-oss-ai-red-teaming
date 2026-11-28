---
name: brite-login
description: Apply the standard BRITE Institute branded passwordless WorkOS AuthKit login to a BRITE research portal. Use when creating, migrating, fixing or standardizing BRITE sign-in, verified-email access requests, volunteer approval, revocation, or login styling.
---

# BRITE Login (WorkOS)

Use the Medical Tool implementation as the source of truth, not a new design.

## Canonical source
- Repository: https://github.com/kareem743/Healthcare-AI-Incident-Discovery-Tool
- Pinned reference commit: 96d38a4c22639b600689df1788a0baae1f9d1edf
- `src/workos.mjs`: original WorkOS AuthKit authorization-code + PKCE implementation (preserved under references/workos.mjs).
- `src/ui.mjs`: original `login()`, `authMessage()` and split-screen login CSS.
- `src/brand.mjs`: existing BRITE shield and Urbanist typeface; use the project's existing authorized assets.
- `docs/workos-authkit.md`: original configuration guide.
- Red Teaming adapter: `brite-cloudflare/src/workos.py`, `src/app.py`, `frontend/src/scenario.js`, and migration `0009_brite_workos.sql` in the red-team repository.

## Implementation procedure
1. Inspect the destination project's identity boundary and role/approval database. Preserve existing administrators, volunteer assignments, records, roles and security policies. Never make a verified identity an administrator automatically.
2. Copy the Medical Tool split-screen layout: actual BRITE shield, Urbanist, navy #092f46, coral #f34551, left mission statement and right sign-in panel. Use the exact shared CSS in references/login.css; adapt only project name and wording. Display Continue with WorkOS, secure verified email sign-in, and access-request status.
3. In JavaScript Workers reuse the reference WorkOS flow and adapt its database/session callbacks. In Python Workers use the Red Teaming adapter instead of copying JS into Python. AuthKit handles the email verification; the app never collects OTP codes or passwords.
4. Register the destination application's exact HTTPS /auth/workos/callback in WorkOS. Set WORKOS_CLIENT_ID, WORKOS_REDIRECT_URI, APP_ORIGIN, and WORKOS_API_KEY as a Worker secret. Keep credentials out of GitHub, chat, logs and frontend. Do not extract or copy credentials from another application. Configure WorkOS for verified-email passwordless authentication (email OTP/magic auth, no password sign-in) and permitted signup. Confirm the actual hosted flow.
5. Use state + PKCE S256, a short-lived Secure/HttpOnly/SameSite=Lax flow cookie, one-use state, server-side code exchange at the fixed WorkOS endpoint, verified email, and a hashed opaque session cookie with expiry. Use only the trusted exchanged identity. Do not trust browser-supplied emails, role claims or unverified tokens.
6. Recheck active account status and local role on every protected API. Unknown verified emails may submit one pending access request; administrator approves/rejects. Blacklist or removal revokes app access immediately; preserve research transcripts. Do not leak data to pending/rejected users. Use same-origin mutation checks, prepared SQL, escaped output, audit events, logout revocation and bounded authentication attempts.
7. Test the new provider without removing existing protection: BRITE_AUTH_MODE=workos-preview retains Cloudflare Access, only a same-email WorkOS callback passes. Then verify actual OTP, callback, sessions, approval queue, blacklist, logout, invalid/expired/replayed states, permissions and an administrator recovery path. Switch to BRITE_AUTH_MODE=workos only after real testing and explicit readiness; edge Access must then be reconfigured for the exact app so the branded login is reachable. Do not disable existing Access policies before successful preview, credential configuration and rollback plan. Incorrect configuration must fail closed, never silently fall back to trusting headers.
8. Run backend, frontend, database, browser, dependency security and Worker packaging checks. Push commits; deploy the exact successful SHA. Verify live release and callback, and report any missing configuration. Do not claim live WorkOS sign-in from mock tests.

## Acceptance checklist
- Original BRITE design and mobile layout.
- WorkOS email verification, no password requested.
- Existing administrator sign-in and direct preapproved volunteer sign-in.
- Verified new volunteer gets pending approval, not research access.
- Admin approve/reject/remove/blacklist; denied account remains denied.
- State mismatch, replay, expired flow, unverified email and invalid credentials rejected.
- CSRF protection, session expiry/logout, no keys or tokens exposed.
- No changes to unrelated BRITE applications or shared subscription.
