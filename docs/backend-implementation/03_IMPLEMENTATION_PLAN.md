# Implementation Plan

Implementation snapshot: repository-local development for stages 0–4, local verification, implementation commit, safe non-fast-forward merge, hardened non-root container images, verified non-force GitHub push and hosted CI are complete for `0.2.0`. Render review/test deployment remains unavailable because the configured service has no active server route.

## Stage 0: governance and baseline

Status: `IMPLEMENTED`.

- Complete read-only audit, protect the dirty/untracked worktree, record decisions and workstream ownership.
- Run baseline tests only after the first ledger checkpoint.

## Stage 1: trusted data space domain

Status: `IMPLEMENTED_LOCALLY`.

- Added checksum-verified migrations `20260820_001`–`004` and readiness reporting.
- Added DataSource, Asset, AssetVersion, Passport, Quality and PolicyVersion persistence.
- Projected existing DataUpload records into the explicit asset model without inventing trusted history; old tasks are `LEGACY_UNMIGRATED`.
- Exposed truthful local data-space and EDC `ADAPTER` capability metadata.

## Stage 2: TTC, trusted compute and evidence

Status: `IMPLEMENTED_LOCALLY`.

- Added idempotent TTC creation/run, attempts, transition service, immutable execution snapshot and algorithm registry.
- Enforced revoked identity, expired contract, frozen-rule immutability, stale Attempt denial and invalid-transition denial.
- Added additive secret-sharing integer sum as `LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST`; TEE remains `BLOCKED`.
- Added fail-closed A/B/C classification, domain-separated Merkle batches, transactional Outbox, retry/idempotency/stale-lock recovery/dead letter and local `DEMO` anchor receipts.

## Stage 3: Agent-native closed loop

Status: `IMPLEMENTED_LOCALLY`.

- Registered six Agent DIDs, controlled Tools, schemas and explicit least-privilege permissions.
- Recorded Tool authorization decisions/calls and explicit PASS/REWORK/HUMAN workflow outcomes.
- Kept official numbers in deterministic execution services; LLM use is optional explanatory assistance only.

## Stage 4: compatibility integration

Status: `IMPLEMENTED_LOCALLY`.

- Added trusted fields to existing workflow responses and frontend DTOs.
- Added `/api/version`, liveness, dependency-aware readiness and structured API error metadata.
- Preserved existing navigation, layout, colors, typography, visual hierarchy and user paths.

## Stage 5: verification and release

Status: `LOCAL_AND_GITHUB_CI_PASS_RENDER_NO_SERVER`.

- Build, unit, integration, security, failure, contract, service E2E and golden-path gates passed.
- The fixed-seed branch-coverage replay passed at 79% against a 75% floor; the GitHub Python 3.12 branch-coverage task also passed.
- Frontend lint, typecheck, 46 tests, production/brand guards and production bundle passed without visual-system changes.
- Diff/untracked-boundary review, explicit staging and implementation commit `71de395bf658fa34c8d271705ace130d9abf0e24` completed. The remote non-fast-forward history was fetched and merged without conflicts as `562f762`; container runtime hardening was committed as `fa04fdc`, pushed non-force and verified with `ls-remote`. All hosted CI workflows passed.

Render in this stage means review/test deployment only under the current manifest. It cannot satisfy production acceptance. External EDC, TEE, blockchain consensus, PostgreSQL, Redis, MinIO, Milvus and high-availability infrastructure remain outside the implemented local boundary.
