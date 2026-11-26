# Humane Intelligence → BRITE pilot migration

Upstream: https://github.com/humane-intelligence/hi-oss-ai-red-teaming (Apache-2.0).
This is an independently implemented pilot based on the upstream architecture and workflow, not a line-for-line port or a full fork. Retain any required upstream license/notice if incorporating upstream source. The new source lives in the `brite-cloudflare/` directory on a separate branch of the fork. Do not replace the upstream application or deploy it over an existing site.

| Capability | Pilot implementation | Remaining work for parity |
|---|---|---|
| Authentication | Verified Cloudflare Access identity + D1 approved users | Live Access configuration/testing; application sign-up, invitations, password resets, external volunteer approval, automated email |
| Permissions | One global role per account, campaign membership, volunteer-owned conversations | Organizations, multi-role global and per-object permissions, reviewer allocation, more granular field masking |
| Evaluations | Campaigns, scenarios, tasks, models, status | Separate evaluation groups, evaluation model subsets, lifecycle transitions, editing/deletion, tags |
| Volunteer workflow | Training acknowledgment, assigned campaign, chat, saved turns, task completion, flags, submit, feedback | Formal screening, graded practice and readiness gates, reminders, accessible onboarding validation |
| Model integration | OpenAI Chat Completions + Anthropic Messages, SSE parser, model snapshot, secret keys | Runtime verification, other providers, model parameter cascade, health/warmup checks, token accounting, reproducibility metadata (finish reasons, raw events, exact provider model version) |
| Reviews | Campaign-scoped queue, urgent flag visible before submission, independent reviewer verdict | Assigned reviewers, multiple reviews and reconciliation, notifications and urgent delivery SLA |
| Data | D1 relational schema, prompt/response text, status, basic audit events | Full Postgres schema/data migration, licenses and encrypted conversation text, data retention, multi-tenant isolation, complete audit trails, backup/restore validation |
| Reports | Basic counts, bounded JSON export | Full aggregate metrics, CSV templates, R2-based export storage and large export jobs |
| Jobs | Cron reaps interrupted turns after 10 minutes | Queues/Workflows for email, reminders, long exports, retries, operational alerts |
| Frontend | New BRITE-themed React/Vite pilot | Design/branding approval, browser usability testing, accessibility and upstream UI feature parity |

## Engineering decisions
- Use a new database, no original data imported. The upstream PostgreSQL schema includes substantially more features; a data migration must be designed against a real source snapshot and verified with row counts and referential checks.
- No Docker, PostgreSQL, Redis, Celery, standalone reverse proxy or monitoring stack. No R2/Queues/Workflows in this pilot because exports are bounded synchronous downloads and no email is sent. Add them for reliable user-triggered background work rather than using cron as a substitute.
- Fixed provider endpoint URLs prevent arbitrary model endpoints from becoming an SSRF mechanism. Secrets are deployed independently, never stored with model records.
- Each completed turn is stored before a terminal SSE event; errors record partial text on a best-effort basis. Client disconnects may leave pending turns until cron marks them failed; this is not a guarantee that every partial token will survive. No automatic model retries (avoid duplicate billing and evidence). Concurrent state transitions and export snapshot consistency need stronger D1 integration tests before production.
- Pilot is for fictional/synthetic medical scenarios only. The checkbox is an acknowledgment, not a PHI detection or compliance control. Do not store real medical data without approval, applicable contracts, security assessment and retention controls.
- No automatic clinical judgments: a human decides whether a finding is confirmed. Urgent queue entries need staff monitoring; this is not an automated notification channel or emergency service.
