# Deployment Runbook

Applicable service version: `0.2.0`.

## Local verification order

1. Redirect all caches/runtime outputs into the repository where supported.
2. Run backend production guard and tests.
3. Run frontend production guard, brand guard, tests, typecheck, lint and build.
4. Start the local API with the project virtual environment and a project-local database.
5. Verify liveness, readiness, version/OpenAPI and the golden path.
6. Review tracked diff and secret scan before any commit.

Required endpoint checks:

- `/api/version`: `service_version=0.2.0`; for a release, `build_sha` must equal the intended commit.
- `/api/health/live`: HTTP 200 and `status=UP`.
- `/api/health/ready`: database migrations, policy decision point and Agent Tool catalog all `READY`; otherwise HTTP 503.
- `/api/privacy/mpc/status`: `LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST`, `cross_domain_production_privacy=false`, `independent_nodes=false`.
- `/api/trust-domain/capabilities`: TTC/Rule Freeze local, EDC adapter, TEE blocked and anchor demo labels remain intact.

## Database and worker operation

- Startup applies revisions `20260820_001`–`004`. Unknown revisions and checksum mismatch are incompatible states, not conditions to bypass.
- Back up a durable database before applying migrations in a non-disposable environment. Never rewrite the migration ledger manually.
- Existing tasks without Attempts become `LEGACY_UNMIGRATED`; do not fabricate transitions/snapshots/evidence to make them appear current.
- Formal result/batch/Outbox rows are committed atomically. Anchor work is post-commit and retryable.
- The current worker entry point is an authorized on-demand local operation at `POST /api/evidence/outbox/process`. Monitor `RETRY_WAIT` and `DEAD_LETTER`; do not mutate sealed evidence to clear failures.
- A current `PUBLISHED` receipt is still `CONFIRMED_DEMO` from `LOCAL_HASH_ANCHOR_DEMO_V1`, not external blockchain finality.

## Release order

`Local Build -> Tests -> Golden Path -> Diff Review -> Secret Scan -> Commit -> Push -> Remote SHA -> Render Deploy -> Health -> Online Smoke -> Deployed SHA`

## Environment truth

- `render.yaml` currently defines a review/test service, not production.
- It uses a free plan, `APP_ENV=test`, SQLite, fixture seeding and OPA local fallback. Data may be ephemeral; no production durability, isolation, scaling or recovery claim is allowed.
- A production deployment requires secret-managed keys, exact build SHA injection, HTTPS CORS, remote fail-closed OPA, a clean/durable database, shared rate limiting/worker infrastructure, backups, observability and the documented production checks.
- Local MPC may be enabled only with its single-host experimental label. No cross-domain MPC, TEE, EDC runtime or blockchain consensus capability may be enabled in user-facing status without independent runtime evidence.
- External PostgreSQL, Redis, MinIO and Milvus remain production blockers until provisioned and verified.

## Render review/test sequence

1. Complete all local gates and commit/push through the main coordinator.
2. Verify the remote branch SHA equals the local reviewed commit.
3. Deploy the existing Render service only as review/test.
4. Verify `/api/version`, live, ready and a non-sensitive smoke path.
5. Confirm Render's deployed commit SHA equals local/GitHub SHA.
6. Record any unavailable credential, deploy identity, health failure or SHA mismatch as `BLOCKED`/not released.

Commit, push, remote SHA verification and hosted CI are `PASS` for release candidate `fa04fdc7e1d87761010fb7d2fc523d436ab54b77`. The derived Render URL currently returns `x-render-routing: no-server` / HTTP 404, so deployment, health, online smoke and deployed-SHA convergence remain `BLOCKED_NO_SERVER`; this runbook does not infer them without an active Render service/API path.
