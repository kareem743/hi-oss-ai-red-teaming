# Required testing and release process

Every push to brite/cloudflare-pilot and every PR targeting it runs backend unit/integration tests with a coverage threshold, frontend unit tests and Vite build, local D1 binding checks using Miniflare, and Chromium end-to-end workflows against a disposable SQLite-backed FastAPI test harness. The Worker package is built only after all four prerequisite jobs succeed. The final quality-gate job fails if any required job is failed, cancelled or skipped. No production secrets, real provider calls or production database writes are used by CI.

The browser tests exercise administrator approval, private scenario creation, searchable selection, volunteer chat and flagging, administrator transcript filtering, unapproved access, and HTML escaping. The original API integration tests exercise review, export and cleanup. Provider tests mock HTTP responses; live OpenAI/Anthropic and deployed Worker authenticated operations still require separate acceptance checks. Miniflare verifies local D1 semantics, not the live Python/Pyodide adapter. Coverage percentage is a regression floor, not proof of completeness.

## Required protection
In GitHub Settings → Rules → Rulesets (or Branches → Branch protection), target exactly brite/cloudflare-pilot, require a pull request, require status check quality-gate, require branches up to date, and block force pushes/deletion. Apply to administrators as appropriate. Do not protect upstream main unless separately intended. The GitHub connector cannot configure branch protection; the repository owner must enable it.

Before any live release, verify the exact commit SHA has a successful quality-gate run. Download only the package artifact from that successful run. The current manual Cloudflare upload is not automatically blocked by GitHub checks; do not upload untested source. A separate protected deployment workflow can enforce this after a scoped Cloudflare deployment credential is configured.

Run locally: backend: python -m pytest -q --cov=src --cov-fail-under=70; frontend: npm test; D1: npm run test:db; browser: npm run build && npx playwright install chromium && npm run test:e2e (install backend dependencies first).
