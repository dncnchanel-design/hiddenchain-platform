# Progress Ledger

## Current backend batch — 2026-08-21 (Trusted Space residual closure; local only)

### Completed in this batch

- Added migration `20260821_004` and the scoped `user_notifications` table. Notifications carry recipient user/organization, type, title/body, entity references, severity, read timestamp, creation timestamp, and a recipient-scoped dedupe key.
- Added `/api/trust-space/notifications` paginated/type/unread filtering, unread counts, mark-one-read and mark-all-read actions. Every query is scoped to the authenticated user; notification publishing runs after the primary transaction and failures are swallowed/rolled back so the business decision remains committed.
- Connected notification publication to persisted data-use submissions/decisions, contract negotiation events, TTC transitions, generated result-confirmation records, and audit report generation. Dedupe keys prevent repeated notifications on idempotent replays.
- Added allowlisted, versioned `GET /api/trust-space/help?view=...` content. Responses contain plain-text guidance, real related API paths, allowed actions, role capabilities and explicit ADAPTER/BLOCKED/DEMO boundaries; arbitrary view/file paths are rejected.
- Extended the workbench DTO with compatibility-preserving `quick_action_items` (`code`, `label`, `path`, `allowed`, `disabled_reason`, `entity_id`, capability/source fields). Existing `quick_actions: string[]` remains for the current client while new clients can use stable codes instead of localized-label routing. Empty target records are disabled with a reason.
- Added scoped `GET /api/trust-space/ttc` pagination/status filtering. TTC detail/list/action envelopes now derive manual transition actions from the current `TtcStateMachine` state and role; the existing transition endpoint remains the final If-Match and domain-state guard.

### Verification evidence

- Residual backend专项: PASS, 4 tests (`tests/test_trust_space_notifications.py`), covering migration/OpenAPI, help allowlist, notification isolation/idempotency/read state, authorization/contract/TTC/result/audit event publication, stable quick-action codes and TTC list/transition scope.
- Combined notification + authorization + Trusted Space/workflow/migration/TTC regression group: PASS, 36 tests, 2 warnings.
- Backend full pytest: PASS, 146 tests, 2 warnings, 164.26 seconds.
- Python compilation: PASS (`python -m compileall -q backend/app backend/tests/test_trust_space_notifications.py`).

### Release boundary

- This is local backend work only. No frontend file, frontend integration, commit, GitHub push, Render deployment, or online/visual claim was made by this batch. The existing frontend still consumes the legacy `quick_actions: string[]`; `quick_action_items` is the stable contract for the next frontend wiring batch.

## Current backend batch — 2026-08-21 (Trusted Space Agent assistant; local only)

### Completed in this batch

- Added migration `20260821_003` with four scoped persistence tables: `assistant_sessions`, `assistant_messages`, `assistant_plans`, and `assistant_plan_steps`. Sessions are bound to the authenticated user and organization; plans and steps carry versions, idempotency keys, capability labels, source-of-truth fields, and durable request/invocation references.
- Added `/api/trust-space/assistant` session, resume, message, message/plan listing, tool catalog, plan status, execute, cancel, and retry endpoints. The router enforces business-role authentication, user/organization scope, structured `403/404/409/412/428` errors, `If-Match`, idempotency replay, and ETags.
- Added a deterministic allowlisted local planner (`LOCAL_REAL_DETERMINISTIC`). Supported read shortcuts query persisted asset/passport/quality, usage-request, TTC, evidence-ledger, and audit records. Outputs explicitly report `raw_data_accessed=false`; unknown intents are `BLOCKED` and do not produce fabricated results.
- Write shortcuts (`SUBMIT_USAGE_REQUEST`, authorization decisions, and TTC advancement) never mutate business tables. They persist an assistant review envelope with `PENDING_REVIEW`, a durable request ID, and an audited human-review event; this batch did not invent a second execution engine or claim an existing `ControlledExecutionRequest` model that is absent from the repository.
- Tool catalog entries are sourced from the existing `agent_tools` registry and filtered by role. External EDC/TEE/MPC/chain capabilities retain their existing `ADAPTER`/`BLOCKED`/`DEMO` truth labels.

### Verification evidence

- Assistant专项: PASS, 4 tests (`tests/test_trust_space_assistant.py`), covering session/organization isolation, durable messages/plans/steps and multi-plan versions, five real read shortcuts, unknown intent, role scope, tool filtering, write review/no business side effect, audit/invocation trace, idempotency, stale `If-Match`, cancel/retry/status, OpenAPI and sensitive-field non-leakage.
- Migration + assistant + Trusted Space read/workflow gate: PASS, 21 tests.
- Related platform/security/trust-domain regression group: PASS, 51 tests (`tests/test_platform.py`, `tests/test_security_gates.py`, `tests/test_trust_domain.py`).
- Backend full pytest: PASS, 142 tests, 2 warnings, 119.96 seconds; compile/diff checks are run after this ledger update.

### Release boundary

- This is local backend work only. No frontend file, frontend Agent Sheet integration, commit, GitHub push, Render deployment, or online/visual claim was made by this batch.

## Current backend batch — 2026-08-21 (Trusted Space contract/TTC/result/audit workflows; local only)

### Completed in this batch

- Added append-only `ContractNegotiationEvent` persistence and migration `20260821_002`. Contract detail/list and event/action APIs now expose real parties, assets/authorization references, terms, state/timeline, optimistic `If-Match`, idempotency, comment/counter/accept/reject semantics, provider/consumer scope, and audit side effects. Attachment values are controlled metadata references only; no file download or upload claim is made.
- Extended `/api/trust-space` with 24 documented paths covering contracts and negotiation actions, TTC detail/events/controlled transitions, computation detail/log polling, results, result-confirm delegation to the existing signature/state/evidence transaction, evidence verification, and audit list/task/JSON/CSV export. DTOs carry `capability_state`, `source_of_truth`, and `allowed_actions` envelopes.
- TTC read models compose persisted tasks, attempts, transitions, immutable rule-freeze snapshots and participant registrations. Manual transitions delegate to the existing `TtcStateMachine` and `If-Match` guard; normal system stages cannot be advanced by the frontend. Computation participants/logs/receipts come from persisted jobs and task data; absent cross-domain MPC/TEE returns `ADAPTER`/`BLOCKED` and empty participant data rather than static A/B/C nodes.
- Result/evidence models expose persisted hashes, signatures, local ledger evidence, evidence batches/outbox/anchors and honest chain capability labels. Missing evidence produces no invented TxHash/block height. Audit exports are server-side and export actions are themselves audited; business roles remain denied from oversight-only audit routes.

### Verification evidence

- Trusted Space workflow专项：PASS, 5 tests (`tests/test_trust_space_workflows.py`), covering negotiation persistence/state/If-Match/idempotency/scope/attachments, TTC cursor and controlled transitions, snapshot/attempt composition, computation ADAPTER/BLOCKED truth and log cursor, result/evidence hash/verify scope, and audit JSON/CSV exports.
- Combined migration + authorization + prior Trusted Space + workflow gate: PASS, 23 tests.
- Related regression groups: PASS, 30 tests (`test_trust_domain.py`, `test_evidence_outbox.py`, `test_security_gates.py`) and 63 tests (`test_platform.py`, `test_formal_backend.py`, `test_mpc.py`, `test_open_source_integrations.py`).
- Backend full pytest: PASS, 138 tests, 3 warnings; `python -m compileall -q backend/app`: PASS; `git diff --check`: PASS.

### Release boundary

- This is local backend work only. No frontend file, frontend integration, commit, GitHub push, Render deployment, or visual/online claim was made by this batch. The frontend has not been connected to these new workflows; Agent/assistant integration remains a later batch.

## Current backend batch — 2026-08-21 (Trusted Space read models; local only)

### Completed in this batch

- Added the database-backed `/api/trust-space` read-model family: `context`, `workbench`, `identity`, `catalog`, and `assets/{asset_id}`. These endpoints aggregate the authenticated actor, organization/DID, real data assets and versions, passports, quality records, usage requests, contracts/agreements, TTC tasks, compute jobs, and audit reports; they do not copy frontend fixtures or fixed demo asset IDs.
- Enforced role and organization scope in the read model: generator/retailer users see only their own assets and participant-scoped task data; exchange/regulator/admin users can read the allowed wider scope; asset detail returns `404` for an unknown or out-of-scope asset to avoid enumeration.
- Added stable pagination and backend filters for catalog search, asset type, domain, sensitivity, and provider. Workbench KPIs use full scoped counts while recent lists are bounded; empty result sets return real zero/empty values.
- Added explicit `capability_state` and `source_of_truth` fields throughout the DTOs. Identity/DID records are sourced from `did_identities`; connector control is labeled `ADAPTER` with `NOT_CONFIGURED` external EDC readiness; TEE is `BLOCKED`; blockchain is `DEMO`. No connected certificate, EDC, TEE, TxHash, or production attestation is invented.

### Verification evidence

- Trusted Space API/service matrix: PASS, 5 tests (`tests/test_trust_space.py`) covering OpenAPI contract, actor/subject isolation, workbench scope, catalog filters/pagination/empty result, honest identity readiness, real asset ID detail, and 404 boundary.
- Combined migration + authorization + Trusted Space tests: PASS, 18 tests.
- Python compilation: PASS. Backend full pytest: PASS, 133 tests collected and all passed (warnings only).

### Release boundary

- This batch is local backend work only. No frontend file, commit, GitHub push, Render deployment, or visual claim was made.

## Prior backend batch — 2026-08-21 (provider authorization workflow; local only; superseded for current work)

### Completed in this batch

- Added the persisted `DataUsageRequest` domain model and migration `20260821_001`. It records the asset/version, applicant and provider organizations/DIDs, purpose, usage mode, requested scope/fields, terms, duration/expiry, decision/revocation reason, reviewer, optimistic state version, organization-scoped idempotency key, timestamps, contract/agreement references, and capability truth fields.
- Added the provider-governed state machine `SUBMITTED → UNDER_REVIEW → APPROVED/REJECTED`, with `APPROVED → REVOKED/EXPIRED`; applicant withdrawal uses `REVOKED`. Illegal transitions return a structured `409`, stale `If-Match` returns a structured version conflict, and repeated target actions are idempotent.
- Exposed the `/api/data/access-requests` API family: create, scoped paginated list, provider inbox (`?inbox=true`), detail, review, approve, reject, applicant withdraw, and provider revoke. The backend derives applicant/provider identity and enforces organization scope; no frontend route has been connected in this batch.
- Provider approval creates a standalone nullable-task `DataContract` and `DataSpaceAgreement` in the same transaction and writes an audit event. Decisions are labeled `LOCAL_REAL`; signature is `NOT_PROVIDED` and external anchoring is `BLOCKED`. No production signature, chain transaction, or random `REQ-*` identifier is claimed.
- Existing settlement-linked contracts/agreements remain task-bound; the nullable compatibility migration preserves their existing task IDs. The SQLite legacy upgrade path was exercised, including index-safe table rebuild and repeated migration application.

### Verification evidence

- Migration readiness: PASS, 7 tests (`tests/test_migrations_readiness.py`).
- Provider authorization API/service matrix: PASS, 6 tests (`tests/test_data_usage_requests.py`), including OpenAPI paths, pagination/inbox scope, idempotency, 403/409/428 semantics, review/approve/reject/withdraw/revoke, contract/agreement/audit side effects, expiry synchronization, and approval rollback.
- Existing settlement/data/trust-domain and security/Excel/integration regression groups: PASS in the focused runs; the subsequent full backend pytest also passed all 133 collected tests.
- Frontend lint/typecheck/build/unit tests and online/Render evidence are not part of this backend batch and are not claimed as revalidated here.

### Release boundary

- This batch is local working-tree work only. No commit, GitHub push, Render deployment, or frontend visual change was made by this batch.
- The existing published/review ledger below remains historical context; it does not include this backend batch.

## Prior release checkpoint — 2026-08-21 (post-publish review/test; docs-only sync; superseded for current backend work)

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

### Published review/test evidence

- The product payload is committed as `a8fac1aa06647dc5e1343d5a269af475ae333d1a` on `agent/deep-brand-green`; the GitHub push and exact code-payload SHA verification passed.
- Render service `hiddenchain-platform` is live at `https://hiddenchain-platform.onrender.com` for review/test use. Public liveness/readiness and `/api/version` checks passed, and the reported `build_sha` matches the product payload commit.
- `ONLINE_SMOKE = PASS_PARTIAL_DESKTOP`: the live desktop smoke covered login, Dashboard, identity center, data catalog, Excel batch upload, asset passport, use-application wizard, contract/negotiation, TTC, MPC, and results/evidence. The observed Chrome viewport was about 1707px wide; covered pages had no root horizontal overflow and no captured console error/warning.
- Online smoke evidence retained outside the release staging set: `runtime/online-smoke-a8fac1aa/desktop/dashboard-1707x842.png`, `asset-passport-1707x842.png`, `excel-upload-1707x842.png`, and `mpc-task-1707x842.png`.
- Audit center and the global Agent Sheet were not completed because the Chrome form/control channel timed out; IAB was unavailable, and 390px mobile was not verified online in this round. No complete twelve-module or mobile-online pass is claimed.

### Release boundary

- The current product payload is published as `a8fac1aa06647dc5e1343d5a269af475ae333d1a`; this checkpoint adds only release-ledger synchronization and does not change product code, tests, or configuration.
- Render remains a review/test execution plane, not production evidence. The dynamic deployment identifier is intentionally kept in the external final release report rather than this docs-only synchronization commit, so it cannot become stale or create a self-referential release cycle.
- `CODE_PAYLOAD_COMMIT` remains the stable application SHA, while `SYNC_TARGET = CURRENT_BRANCH_HEAD` identifies the documentation-sync head that must be deployed before claiming final three-way convergence for that head.

## Historical checkpoint — 2026-08-20 (superseded by the 2026-08-21 post-publish checkpoint)

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
## Historical frontend delivery checkpoint — 2026-08-20 (superseded by the 2026-08-21 post-publish checkpoint)

- Trusted Energy console implementation, responsive visual verification, and pure frontend tests completed; precise publication remains pending and no Render deployment was performed in this checkpoint.
## Current UI authorization-record correction — 2026-08-22

### Current work

- Correcting the Trusted Space authorization-record surface so “待我审核” uses provider-inbox scope while “我的申请” uses current-applicant scope.
- Replacing user-facing authorization status, purpose, usage-mode, capability, policy-source and optimistic-version English codes with professional Chinese labels; internal IDs and protocol payload values remain unchanged.

### Scope and verification state

- Frontend scope: `frontend/src/features/trusted-energy/pages/AuthorizationsPage.tsx`, `ApplyPage.tsx`, shared trusted-space labels/API query typing.
- Backend scope: access-request list query adds an explicit applicant-owned scope; service import and Python compilation passed. The focused authorization pytest passed with a temporary in-memory test-only alias for the host's missing `defusedxml` package; production code and test files were not changed for that workaround.
- Frontend verification: TypeScript, ESLint, 65 unit tests, Vite production build, `git diff --check`, the Impeccable detector and mocked-response browser QA at 1440×900 all passed.
- Release/deployment: not requested and not performed.

## Current end-to-end settlement release — 2026-08-22

### Completed

- 将工作台、结算创建、结算详情、审计报告和结果页串成可重复操作的“发起 → 授权 → 执行 → 结算 → 审计 → 结果确认”流程；异常状态可回到重试或补件路径。
- 让审计报告成为中高风险结果确认的前置门槛，并在详情、审计、结果页面展示下一步动作、角色交接、证据和审计状态。
- 将主流程中的状态、能力、来源和动作改为中文可读标签；协议内部值保持兼容，未把外部适配、未核验能力伪装成已部署能力。
- 本地验证通过：前端类型检查、ESLint、66 项前端测试、生产构建与生产配置检查；后端编译及结算/安全/可信空间 20 项聚焦测试通过。
- 应用代码已提交为 `98ebed1d4222dc1c20b53146c757bba9f2ae670f`，GitHub `main` 与工作分支均已同步；Render 服务已手动从 `main` 构建该版本并通过就绪检查。

### 发布边界

- Render 仍是评审/测试环境，不构成生产发布证据；线上只确认公开健康检查、版本构建号和服务就绪状态。
- 本地未追踪的截图、运行时目录、工具缓存和压缩包均未纳入本次发布。
