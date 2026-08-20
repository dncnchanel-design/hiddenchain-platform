# Repository Audit

Date: 2026-08-20

## Baseline

- `PROJECT_ROOT`: `D:\桌面\大创产品\hiddenchain-platform`
- Branch: `agent/deep-brand-green`
- Local commit: `affb7ba368fb634727b5c953eb2f9be483c7176f`
- Cached upstream commit: `7e55f511851c6c3aa7e2b4bab9c443571f3c3b26`
- Local relation to cached upstream: ahead 2, behind 0
- Tracked or staged modifications at audit start: none
- Untracked files at audit start: 474, including repository Skills, screenshots, review artifacts, runtime artifacts, `AGENTS.md`, and an archive. All are treated as pre-existing user assets and excluded from automatic staging.

## Existing implementation at audit start

- Backend: FastAPI, SQLAlchemy, strict Pydantic DTOs, JWT/RBAC, OPA-compatible policy checks, deterministic local settlement, audit records, local evidence ledger, OpenAPI.
- Frontend: React 18, TypeScript, Vite, role-aware routing, shared UI system, same-origin API client, 18 protected routes, frozen green visual system.
- Data space: DCAT/Dataspace Protocol and policy/contract projections plus a local connector adapter. No Eclipse EDC Java runtime or independent Provider/Consumer nodes exist in this repository.
- Trusted execution: local controlled deterministic settlement and OpenDP aggregation are implemented. MPC, TEE, blockchain consensus, and cross-domain non-export proof are not implemented.
- Deployment: Docker/Render manifests exist. `render.yaml` describes a free review/test service with SQLite, fixtures enabled, and local OPA fallback; it is not a production deployment.

## Structural gaps found at audit start

1. No versioned schema migration ledger; startup uses `create_all` plus ad hoc additive columns.
2. No explicit DataSource/Asset/AssetVersion/Passport/Quality persistence model.
3. No persistent PolicyVersion and immutable execution snapshot covering policy, contract, data, rule, algorithm, parameters, and units.
4. SettlementTask is TTC-like but lacks attempt history, authoritative transition records, and bypass-resistant TTC state control.
5. Six Agent roles exist, but Tool schemas, least-privilege permissions, permission decisions, and Tool-call records are not explicit.
6. Evidence is per-record local hashing; there is no A/B/C classification, Merkle batch, transactional outbox, retry-safe anchor worker, or anchor receipt model.
7. No real MPC nodes, TEE attestation, EDC runtime, or blockchain network is available. These remain adapters or blockers until external runtimes and evidence exist.
8. API lacks version/readiness endpoints, command idempotency headers, and stable typed frontend business DTOs.

## Implemented working-tree delta

The current `0.2.0` working tree closes the repository-local portions of the gaps above without replacing the existing FastAPI/React foundation:

- Ordered migrations `20260820_001` through `20260820_004` add a checksum-verified schema ledger, formal trust tables, compatibility columns, truth-preserving legacy projection, idempotency indexes and Attempt-bound outcome references.
- Historical tasks without a persisted TTC Attempt are marked `LEGACY_UNMIGRATED`; migration does not invent transitions, snapshots, signatures or evidence.
- DataSource, DataAsset, DataAssetVersion, DataAssetPassport, AssetQuality, UsagePolicy/Version and DataCapsule records are persisted and projected compatibly from existing uploads.
- TTC now persists attempts, hashed transitions, state versions and abnormal branches. Rule Freeze creates an immutable execution snapshot over rule, policy, contract, data, algorithm, parameters and units.
- Agent DIDs use a registered controlled-Tool catalog, explicit active grants and audited Tool-call records. Official amounts and energy values remain owned by deterministic services.
- Formal evidence uses explicit A/B/C classification, domain-separated SHA-256 Merkle batches and a transactional Outbox with idempotency, retry, stale-lock recovery and dead-letter handling.
- Additive secret-sharing integer sum is a real protocol implementation with the exact status `LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST`; it is not an independently operated cross-domain MPC deployment.
- `/api/version`, liveness and dependency-aware readiness endpoints expose version `0.2.0`, build identity and truthful capability state.
- Frontend integration consumes authoritative state/actions and evidence metadata without redesigning navigation, layout, colors, typography or visual hierarchy.

These are working-tree facts, not a release declaration. Final test evidence, commit, push, remote SHA verification and Render state remain `PENDING` until the main coordinator records them.

## Remaining environment constraints

- Project Python virtual environment and frontend `node_modules` are present.
- Java, Docker CLI/engine, and a Render CLI are unavailable on this host.
- GitHub live connector access returned unavailable/not found during audit; cached Git refs remain usable. Remote verification must be retried through authorized Git transport later.
- Eclipse EDC remains `ADAPTER`; no Java control/data-plane runtime is present.
- TEE remains `BLOCKED`; no attestation runtime, certificate chain or key-release service is present.
- The anchor adapter remains `DEMO`; it has no independent network, consensus, timestamp authority or external finality.
- PostgreSQL, Redis, MinIO, Milvus and production high-availability infrastructure remain unavailable or unverified.
- `render.yaml` is explicitly review/test only: free plan, `APP_ENV=test`, SQLite, test fixtures and local OPA fallback.
- No host file outside `PROJECT_ROOT` was created, modified, or deleted during audit or this documentation workstream.
