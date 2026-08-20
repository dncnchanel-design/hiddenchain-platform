# Architecture Decisions

## ADR-001: Extend the existing modular monolith

Status: accepted, 2026-08-20.

The repository's FastAPI/SQLAlchemy backend and React frontend are retained. The design document recommends Java/Spring Boot when no reasonable implementation exists, but the current repository already has substantial tested equivalent behavior. Replacing it would discard working assets and conflict with the repository guardrails.

## ADR-002: Preserve frontend visuals and API compatibility

Status: accepted.

Existing navigation, layouts, colors, typography, page hierarchy, and primary actions are frozen. New trusted facts are added to existing DTOs and compatible endpoints. Frontend changes are limited to typed contracts, command metadata, loading/error behavior, and authoritative backend state consumption.

## ADR-003: SettlementTask is the compatibility aggregate for TTC

Status: accepted.

`SettlementTask.task_id` remains the existing aggregate key and `capsule_id` remains its public TTC identifier. Attempt, transition, snapshot, evidence batch and Outbox tables reference this aggregate instead of introducing a second competing task system. Existing tasks without a persisted Attempt are explicitly `LEGACY_UNMIGRATED`; compatibility never fabricates trusted history.

## ADR-004: Versioned project-local migrations without a new dependency

Status: accepted.

A small SQLAlchemy migration runner and schema-version ledger replace ad hoc startup DDL. Revisions are ordered, checksum-verified and idempotent, with a PostgreSQL transaction-scoped advisory lock and readiness-safe status. This avoids adding an unreviewed network dependency while supporting the repository's SQLite path and PostgreSQL-compatible DDL.

## ADR-005: Control and execution planes remain separate in code and authority

Status: accepted.

Agent/orchestration code may propose structured commands and call controlled Tools. Only deterministic services may create official energy, amount, settlement, state-transition, evidence, or anchor records. No LLM output is persisted as an official numeric fact.

## ADR-006: Capability labels are evidence-based

Status: accepted.

- Deterministic settlement and local policy execution may be `LOCAL_REAL` after tests.
- The implemented additive secret-sharing sum uses the precise status `LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST`; the generic capability family may be `LOCAL_REAL`, but no response or document may present it as cross-domain production privacy.
- EDC and TEE remain `ADAPTER` or `BLOCKED` without external runtimes and attestation.
- Local hash-chain/Merkle anchoring remains `DEMO`; it is not blockchain consensus.

## ADR-007: Business result and anchor request are transactionally coupled, anchor execution is not

Status: accepted.

Final trusted result/evidence staging and the corresponding outbox row are committed in one database transaction. Anchor processing is idempotent and asynchronous/retryable. Anchor failure never rewrites an already verified result.

## ADR-008: Evidence classes and anchor policy fail closed

Status: accepted.

A-class trust-boundary evidence is mandatory for anchoring, B-class anomaly/risk evidence is conditionally anchored from policy inputs, and C-class process evidence stays off-chain while contributing to the Merkle root. Unknown evidence types require an explicit class rather than silently defaulting to C. Raw sensitive records are excluded from evidence items and Outbox payloads.

## ADR-009: Normal TTC progress belongs to domain services

Status: accepted.

The public manual transition endpoint is limited to explicit human/exception targets. Normal progress is advanced only by the owning deterministic domain service after identity, authorization, snapshot and evidence gates pass. `ETag`/`If-Match` protects state versions and `Idempotency-Key` protects create/run replay bindings.

## ADR-010: Review/test deployment is not production

Status: accepted.

`render.yaml` is a convenient review/test deployment only. Its free plan, test environment, SQLite database, fixture seeding and OPA local fallback violate formal production requirements. Production readiness remains blocked until independent infrastructure and online evidence are supplied, irrespective of review deployment success.
