# Progress Ledger

## Current checkpoint — 2026-08-21 (pre-commit)

### Completed in this checkpoint

- Consolidated the latest product changes for controlled Excel batch upload and permission-aware routing: `ExcelUploadPage` is the upload surface, the retired `DataPage` is removed, `/data/upload` is the canonical route, and legacy data routes redirect to it.
- Preserved the frozen `trusted-energy` visual layer; changes are limited to the approved backend/API/DTO/state/auth/loading/error and route integration boundary.
- Added the product sample workbook and Excel parser tests. The deterministic generator/validator produced 10 sheets × 100 rows = 1,000 rows; parser validation passed and formula-error inspection returned zero matches.
- Verified the role/route matrix and backend permission redirects remain aligned with the frontend route map.

### Verification evidence

- Backend full `pytest`: PASS (warnings only).
- Frontend ESLint, TypeScript typecheck and production guard/build: PASS.
- Frontend unit tests: PASS, 49 tests.
- Excel upload focused tests: PASS, 3 tests.
- Local functional regression: PASS, 104 passes / 0 failures; evidence: `runtime/functional-regression-20260821-local/report.json`.
- `git diff --check`: PASS.

### Release boundary

- This checkpoint is worktree-only on base `6d0a48c`; no commit or push has been made yet.
- Render remains a review/test execution plane. No Render deployment was triggered in this checkpoint, and no new deployed SHA or deployment ID is claimed here.

## Current checkpoint — 2026-08-20

### Completed

- Read and applied `AGENTS.md`, five repository Skills, the formal task directive, and the complete design document.
- Resolved and verified `PROJECT_ROOT`.
- Audited Git, repository structure, frontend, backend, tests, data-space code, deployment manifests, and host tool availability without writes.
- Recorded architecture decisions, capability truth labels, implementation plan and workstream ownership.
- Implemented versioned migrations with checksum verification and truth-preserving `LEGACY_UNMIGRATED` projection.
- Implemented Data Asset/Passport/Quality and policy-version persistence while retaining existing upload compatibility.
- Implemented TTC Attempts, hashed transitions, abnormal paths, Rule Freeze and immutable execution snapshots.
- Implemented controlled Agent Tool catalog, explicit grants, authorization checks and Tool-call audit records.
- Implemented A/B/C evidence classification, domain-separated Merkle batches and transactional Outbox processing with retry and dead letter.
- Implemented additive secret-sharing integer sum as `LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST`.
- Added `0.2.0` version, liveness, dependency-aware readiness and structured API error/optimistic concurrency/idempotency contracts.
- Integrated authoritative backend state into the frontend data path without redesigning the frozen visual system.
- Updated trusted-execution, production-readiness, deployment and backend-implementation documentation to match the code boundary.
- Closed independent review blockers for state-machine artifact gates, organization/DID authorization, audit approval, algorithm/build binding, Vault input integrity, Merkle batch replay verification and anchor receipt validation.
- Passed 117 backend tests, 79% fixed-seed backend branch coverage, 46 frontend tests, explicit golden paths, OpenAPI serialization, production/brand guards, Python/TypeScript compilation, ESLint and Vite production build.
- Completed final cached-diff, protected-asset boundary and high-confidence secret scans, then created implementation commit `71de395bf658fa34c8d271705ace130d9abf0e24`.
- Reconciled the newly observed remote commits with a no-conflict non-fast-forward merge `562f762`; post-merge golden paths passed. Release candidate `fa04fdc` added non-root container hardening, was pushed non-force and verified with `ls-remote`; all hosted CI workflows passed.

### Current release state

- `GITHUB_CI_PASS_RENDER_REVIEW_TEST_PASS`. The non-force push, remote SHA verification, hosted CI and Render review/test health/SHA checks succeeded; no force-push or bypass was used.

### Pending release evidence

- Formal production deployment and external infrastructure evidence; Render review/test deployment, online health/smoke and deployed SHA verification are complete for `9e40ac7`, but are not production evidence.
- Local Docker image build and real PostgreSQL migration/concurrency validation remain unavailable on this host.

### Known blockers

- Eclipse EDC remains `ADAPTER`; TEE and cross-domain production MPC remain `BLOCKED`; blockchain consensus remains `DEMO` only.
- PostgreSQL, Redis, MinIO, Milvus and production high-availability infrastructure are unavailable or unverified.
- The available Render service is review/test only and cannot satisfy production acceptance; it uses test mode, SQLite, fixture seeding and local OPA fallback.
- Git transport, hosted CI and Render online checks are verified for the reviewed SHA. PostgreSQL, Redis, MinIO, Milvus and high-availability production operations remain unverified.

### Next step

- Keep the Render review/test service pinned to the verified SHA for review, and provision separate production infrastructure before any production release claim.
## Frontend delivery checkpoint — 2026-08-20

- Trusted Energy console implementation, responsive visual verification, and pure frontend tests completed; precise publication remains pending and no Render deployment was performed in this checkpoint.
