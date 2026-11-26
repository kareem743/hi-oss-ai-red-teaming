# BRITE pilot deployment handoff

## Current infrastructure
The dedicated D1 schema is installed. The dedicated Worker hostname is protected by an Access application using email OTP and an administrator allowlist. The deployed Worker is currently a diagnostic probe only. Do not mistake the probe for the application. No model credentials are configured.

## Build and release
The CI workflow compiles the React frontend, runs Python tests, and builds Emscripten-compatible Python packages. Download the **brite-python-worker-package** artifact from a successful run on this branch. Unzip the outer GitHub Actions artifact if necessary, until you have the ZIP containing src/, python_modules/, and frontend/dist/. Use the latest checked-out branch source with the artifact.

From brite-cloudflare:
```sh
python3 -m venv .venv
source .venv/bin/activate
pip install httpx
# Set these variables using the dedicated pilot's actual Cloudflare values:
export CLOUDFLARE_ACCOUNT_ID='...'
export BRITE_D1_ID='...'
export BRITE_ACCESS_ISSUER='https://YOUR-TEAM.cloudflareaccess.com'
export BRITE_ACCESS_AUD='...'
export BRITE_ORIGIN='https://brite-redteam-api.YOUR-SUBDOMAIN.workers.dev'
python deploy.py /path/to/brite-python-worker-package.zip
```
The script asks for the scoped API token using a hidden prompt (or accepts CLOUDFLARE_API_TOKEN). Use account-scoped Workers Scripts Edit and Access Apps and Policies Read permissions; never commit the token. The script uses the official multipart asset/session APIs; it attaches the assets to the same Worker as the Python API, checks the expected Access application exists, preserves existing secret bindings, disables deployment previews, and sets the Cron schedule. This is a prepared deployment path, not a claim of a successful live release. Check the exact allowlist in the Access dashboard before use.

Set OPENAI_API_KEY and/or ANTHROPIC_API_KEY as Worker secrets in the Cloudflare dashboard after deployment. Add volunteers to the Access allowlist and the app's approved-user list only after end-to-end tests and institutional approval. Use synthetic data only. No PHI.

## Release acceptance
1. Open the hostname logged out: Access sign-in must be required.
2. Sign in as the approved administrator: React loads and /api/me identifies the approved account.
3. Verify D1 campaign creation and evidence persistence, volunteer isolation, review flow, exports, and audit events.
4. Verify direct unauthorized API calls do not return research records.
5. Add a separately authorized reviewer and volunteer and test the complete pilot workflow.
6. Check logs, scheduled event execution, provider configuration and quotas. Roll back to the diagnostic version if any security gate fails.

The Cloudflare GitHub build connection must be explicitly authorized for the fork before automated deployments can be enabled. The direct upload command is an alternative to that connection. The upstream main branch remains unchanged.
