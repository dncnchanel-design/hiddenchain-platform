# Workstreams and File Ownership

## Current settlement sample batch — 2026-08-22

| Workstream | Execution boundary | Evidence | Status |
| --- | --- | --- | --- |
| Raw simulation fixture | Main agent; `demo-data/2026-08-full-settlement-simulation.json` and expected-result companion | Six input assets; deterministic formula and final amount documented | IMPLEMENTED_LOCAL_DATA |
| Chinese operation runbook | Main agent; `docs/FULL_SETTLEMENT_SIMULATION_RUNBOOK.md` and `demo-data/README.md` | Covers startup, import, role handoff, audit gate, confirmation, archive and troubleshooting | IMPLEMENTED_LOCAL_DOCS |
| Full-flow regression | Main agent; `backend/tests/test_platform.py` | Focused 3-test run passed; standalone flow reached AUDITED with 8 evidence records | VERIFIED_LOCAL_BACKEND |
| Release/deployment | Main agent retains commit, push, Render and final convergence ownership | Not requested for this data/runbook task | NOT_REQUESTED |

## Current frontend batch — 2026-08-22 (翡翠绿系统栏)

| Workstream | Execution boundary | Evidence | Status |
| --- | --- | --- | --- |
| Main shell system bar | Main agent; `frontend/src/styles.css`, `frontend/index.html` | 48px system bar uses `#0B7768`; browser theme color and favicon aligned; neutral sidebar/work surface retained | IMPLEMENTED_LOCAL_FRONTEND |
| Trusted Space system bar | Main agent; `frontend/src/features/trusted-energy/trusted-energy.css` | Trusted Space top bar and login brand bar use the same `#0B7768` token | IMPLEMENTED_LOCAL_FRONTEND |
| Theme audit and documentation | Main agent; production guard, `DESIGN.md`, `BRAND_THEME_AUDIT.md` | Token guard, contrast note and Chinese visual specification updated | VERIFIED_LOCAL_FRONTEND |
| Verification | Main agent | Production guard, brand audit, typecheck, ESLint, 66 frontend tests, Vite build, browser desktop/390px checks and backend compileall passed | VERIFIED_LOCAL |
| Release/deployment | Main agent retains commit, push, Render and final convergence ownership | Application commit and hosted review/test deployment pending | PENDING |

## Current backend batch — 2026-08-21 (Trusted Space residual closure; local only)

| Workstream | Execution boundary | Evidence | Status |
| --- | --- | --- | --- |
| Scoped notifications and event publication | `/root/luna_worker`; `backend/app/models.py`, `backend/app/migrations.py`, `backend/app/services/notifications.py`, data/trust-space/workflow/audit services | Migration `20260821_004`; user/org scoped inbox, unread/read actions, dedupe; authorization, contract, TTC, result and audit events publish best-effort notifications after primary commits | IMPLEMENTED_LOCAL_BACKEND_ONLY |
| Contextual help | `/root/luna_worker`; `backend/app/services/trust_space.py`, `backend/app/routers/trust_space.py` | Versioned allowlist `GET /api/trust-space/help`; arbitrary view/file paths rejected; capability boundaries remain truthful | IMPLEMENTED_LOCAL_BACKEND_ONLY |
| Workbench quick actions and TTC list/action envelope | `/root/luna_worker`; `backend/app/services/trust_space.py`, `backend/app/routers/trust_space.py` | Structured `quick_action_items`; scoped `/api/trust-space/ttc` pagination/status filter; state-machine-derived transition actions with role/scope/If-Match enforcement | IMPLEMENTED_LOCAL_BACKEND_ONLY |
| Verification | `/root/luna_worker`; `backend/tests/test_trust_space_notifications.py` plus existing backend groups | Residual 4; combined 36; backend full pytest 146 passed, 2 warnings; compileall passed | VERIFIED_LOCAL_BACKEND |
| Frontend integration | Out of scope for this batch; no frontend files changed | Existing frontend still consumes legacy `quick_actions`; notifications/help/TTC list controls remain for the next frontend batch | NOT_STARTED |
| Release/deployment | `/root` retains commit, push, Render and final convergence ownership | No commit/push/deploy performed | PENDING |

Notification publishing is intentionally post-commit and best-effort: inbox unavailability cannot roll back authorization, contract, TTC, result or audit business transactions. External EDC/TEE/MPC/chain capabilities remain `ADAPTER`/`BLOCKED`/`DEMO` as applicable.

## Current backend batch — 2026-08-21 (Trusted Space Agent assistant; local only)

| Workstream | Execution boundary | Evidence | Status |
| --- | --- | --- | --- |
| Assistant persistence and deterministic planning | `/root/luna_worker`; `backend/app/models.py`, `backend/app/migrations.py`, `backend/app/services/assistant.py`, `backend/app/schemas.py` | Migration `20260821_003`; four scoped tables; allowlisted planner and versioned/idempotent plans | IMPLEMENTED_LOCAL_BACKEND_ONLY |
| Assistant API and role boundary | `/root/luna_worker`; `backend/app/routers/assistant.py`, `backend/app/main.py` | 9 `/api/trust-space/assistant` paths for sessions, messages, tools, plan status/execute/cancel/retry; structured scope and `If-Match` errors | IMPLEMENTED_LOCAL_BACKEND_ONLY |
| Real read tools and review-gated writes | `/root/luna_worker`; assistant service plus existing `agent_tools`, Trusted Space read models and audit service | 5 real read shortcuts; write intents remain `PENDING_REVIEW` with no business-table mutation; capability/source labels preserved | VERIFIED_LOCAL_BACKEND |
| Verification | `/root/luna_worker` | Assistant 4; migration/assistant/Trusted Space gate 21; related platform/security/trust-domain 51; backend full pytest 142 passed, 2 warnings | VERIFIED_LOCAL_BACKEND |
| Frontend integration | Out of scope for this batch; no frontend files changed | Agent Sheet and other frontend controls are not connected to these endpoints | NOT_STARTED |
| Release/deployment | `/root` retains commit, push, Render and final convergence ownership | No commit/push/deploy performed | PENDING |

The assistant uses the existing `agent_tools` catalog and deterministic local query services. Write actions create only a durable assistant review envelope; no production approval, signature, external execution, TEE/MPC, or chain anchor is claimed.

## Current backend batch — 2026-08-21 (Trusted Space contract/TTC/result/audit workflows; local only)

| Workstream | Execution boundary | Evidence | Status |
| --- | --- | --- | --- |
| Contract negotiation | `/root/luna_worker`; `backend/app/models.py`, `backend/app/migrations.py`, `backend/app/services/trust_space.py`, `backend/app/routers/trust_space.py`, `backend/app/schemas.py` | `ContractNegotiationEvent`, migration `20260821_002`, event/action state machine, optimistic locking/idempotency and audit side effects covered by workflow tests | IMPLEMENTED_LOCAL_BACKEND_ONLY |
| TTC, computation and evidence read models | `/root/luna_worker`; Trusted Space service/router and existing TTC/evidence services | Real attempts/transitions/snapshots, controlled transitions, compute logs/participants, result hashes/signatures/evidence/outbox/anchor truth labels; no static external MPC/TEE/chain claim | IMPLEMENTED_LOCAL_BACKEND_ONLY |
| Audit read/export | `/root/luna_worker`; Trusted Space service/router | Scoped list/detail plus server-side JSON/CSV export and export audit records covered by workflow tests | IMPLEMENTED_LOCAL_BACKEND_ONLY |
| Verification | `/root/luna_worker` | Workflow 5; combined gate 23; related regressions 30 + 63; backend full pytest 138 passed; compile/diff-check passed | VERIFIED_LOCAL_BACKEND |
| Frontend integration | Out of scope for this batch; no frontend files changed | New APIs are not connected to frontend pages or Agent Sheet | NOT_STARTED |
| Release/deployment | `/root` retains commit, push, Render and final convergence ownership | No commit/push/deploy performed | PENDING |

All new DTOs expose `capability_state`, `source_of_truth`, and `allowed_actions`. TTC transitions call the existing domain state machine; connector/TEE/blockchain boundaries remain `ADAPTER`/`BLOCKED`/`DEMO` as applicable. This ledger records local backend facts only and makes no frontend or hosted-release claim.

## Current backend batch — 2026-08-21 (Trusted Space read models; local only)

| Workstream | Execution boundary | Evidence | Status |
| --- | --- | --- | --- |
| Trusted Space read models | `/root/luna_worker`; `backend/app/services/trust_space.py`, `backend/app/routers/trust_space.py`, `backend/app/main.py`, `backend/tests/test_trust_space.py` | Five read endpoints; 5 focused tests; combined migration/authorization/read-model gate 18 passed | IMPLEMENTED_LOCAL_BACKEND_ONLY |
| Frontend integration | Out of scope for this batch; no frontend files changed | No visual, fixture, or frontend data-path claim | NOT_STARTED |
| Release/deployment | `/root` retains commit, push, Render and final convergence ownership | No commit/push/deploy performed | PENDING |

The read models are authoritative database projections with explicit `capability_state/source_of_truth` labels. Connector readiness remains `ADAPTER/NOT_CONFIGURED`, TEE remains `BLOCKED`, and blockchain remains `DEMO`; no external runtime is implied.

## Prior backend batch — 2026-08-21 (provider authorization workflow; local only; superseded for current work)

| Workstream | Execution boundary | Evidence | Status |
| --- | --- | --- | --- |
| Provider data-use authorization | `/root/luna_worker`; `backend/app/models.py`, `backend/app/services/data_usage_requests.py`, `backend/app/routers/data.py`, `backend/app/schemas.py`, `backend/app/migrations.py`, `backend/tests/test_data_usage_requests.py` | Migration readiness 7 passed; authorization API/service matrix 5 passed; existing settlement/data/trust/security/Excel focused regressions passed | IMPLEMENTED_LOCAL_BACKEND_ONLY |
| Frontend integration | Out of scope for this batch; no frontend files changed | No frontend route or visual claim made | NOT_STARTED |
| Release/deployment | `/root` retains commit, push, Render and final convergence ownership | No commit/push/deploy performed in this batch | PENDING |

The backend batch is not a published release. Approval evidence is deliberately labeled `LOCAL_REAL` with `signature=NOT_PROVIDED` and `external_anchor=BLOCKED`; real external signatures, EDC/TEE/MPC infrastructure, and chain anchoring remain outside this local capability boundary.

## Prior release checkpoint — 2026-08-21 (post-publish review/test; docs-only sync; superseded for current backend work)

| Workstream | Execution boundary | Evidence | Status |
| --- | --- | --- | --- |
| Excel batch upload and sample asset | `/root/luna_worker` under `/root` release coordination; `backend/app/services/excel_upload.py`, `backend/tests/test_excel_upload.py`, `frontend/public/sample-data/hiddenchain-excel-batch-data.xlsx`, `tools/build_excel_batch_data.mjs` | Excel focused tests PASS; deterministic 10 × 100 workbook/parser validation PASS; product payload `a8fac1aa…` published | PUBLISHED_REVIEW_TEST |
| Permission and route convergence | `/root/luna_worker` under `/root` release coordination; auth/data routers, access policy, route map, `ExcelUploadPage`, Workbench and regression scripts | Backend full pytest PASS; frontend 49 tests, lint, typecheck and build PASS; functional regression 104/0; product payload `a8fac1aa…` published | PUBLISHED_REVIEW_TEST |
| Release documentation and staging | `/root/luna_worker` performs the delegated documentation-sync checkpoint; `/root` retains commit, push, Render and final release ownership | Three release ledgers updated; this commit is docs-only and is pushed after review | COMMITTED_PUSHED |
| Render review/test verification | `/root` release owner | `hiddenchain-platform` live; liveness/readiness/version passed; deployed build SHA matches product payload; deployment identifier is retained in the external final report | PASS_PARTIAL_DESKTOP |

The existing ownership and historical release entries below remain unchanged. The product payload is `a8fac1aa06647dc5e1343d5a269af475ae333d1a`; this docs-only synchronization head is the next `SYNC_TARGET` for Render before final three-way SHA convergence is claimed. No production-release claim is made.

## Historical execution checkpoint — 2026-08-20 (superseded by the 2026-08-21 post-publish checkpoint)

| Workstream | Owner | Exclusive files | Dependencies | Status |
| --- | --- | --- | --- | --- |
| Coordination/integration | `/root` | Shared backend/frontend integration, deployment manifests, final verification and release ledgers | All streams | LOCAL_AND_GITHUB_CI_PASS; Render review/test verified; production blocked |
| Trust domain core | `/root/domain_core` | `backend/app/trust_models.py`, trust-domain service/router/tests | Existing SQLAlchemy models | IMPLEMENTED_AND_REVIEWED |
| Evidence and privacy compute | `/root/evidence_compute` | evidence Outbox, MPC service and focused tests | Trust models | IMPLEMENTED_AND_REVIEWED |
| Frontend contract compatibility | `/root/frontend_contract` | frontend API/types/hooks/settlement model and tests | Stable backend DTO additions | IMPLEMENTED; regression PASS |
| Documentation convergence | `/root/docs_release` | `README.md`, trusted-execution/production-readiness docs and backend implementation docs except `06_TEST_REPORT.md`/`10_RELEASE_SYNC.md` | Current working-tree implementation | COMPLETED_AND_REVIEWED |
| Independent review | `/root`-assigned reviewers | Read-only security, migration/API and frontend/release review | Integrated diff | COMPLETED; no residual P0/P1/P2 blocker in local scope |
| Final verification and release | `/root` | `06_TEST_REPORT.md`, `10_RELEASE_SYNC.md`, Git staging/commit/push/Render | Review resolution | LOCAL_AND_GITHUB_CI_PASS; RENDER_REVIEW_TEST_PASS; PRODUCTION_BLOCKED |

Rules:

- No agent may edit another owner's files without coordination.
- Shared files are modified only by `/root`.
- Commit, push, GitHub, Render and release convergence are owned only by `/root`.
- All writes and generated outputs remain inside `PROJECT_ROOT`.
- `docs_release` does not edit `06_TEST_REPORT.md` or `10_RELEASE_SYNC.md` and does not assert final test counts, commit, push or deployment outcomes.
## Historical frontend delivery checkpoint — 2026-08-20 (superseded by the 2026-08-21 post-publish checkpoint)

- Trusted Energy console routes, twelve views, scoped primitives, capability truth fixtures, responsive Agent sheet, and pure tests were complete at that historical checkpoint; precise stage/commit/push remained with `/root`, and Render was out of scope for that checkpoint.
## Current UI authorization-record correction — 2026-08-22

| Workstream | Execution boundary | Evidence | Status |
| --- | --- | --- | --- |
| Authorization record scopes and labels | Main agent; `frontend/src/features/trusted-energy/pages/AuthorizationsPage.tsx`, `ApplyPage.tsx`, shared labels/API, `backend/app/services/data_usage_requests.py`, `backend/app/routers/data.py` | Applicant-owned `mine=true` scope, Chinese labels and distinct review/application actions implemented | VERIFIED_LOCAL_FRONTEND_AND_CODE |
| Verification | Main agent; frontend typecheck, ESLint, 65 tests, Vite build, detector, diff check, mocked 1440×900 browser QA and 7 focused backend authorization tests passed; host lacks `defusedxml`, so backend test used an in-memory test-only alias | Production code was not altered for the environment workaround | VERIFIED_LOCAL |
| Release/deployment | Main agent retains commit, push, deployment and release-ledger convergence ownership | Not requested | NOT_STARTED |

## Current end-to-end settlement workflow — 2026-08-22

| Workstream | Execution boundary | Evidence | Status |
| --- | --- | --- | --- |
| Settlement lifecycle | Main agent; `frontend/src/pages/WorkbenchPage.tsx`, `SettlementCreatePage.tsx`, `SettlementDetailPage.tsx`, `ResultsPage.tsx`, `ReportsPage.tsx`, settlement model and workflow service | Repeatable start-to-result path, role handoff, evidence, audit gate, exception/rework and retry actions are wired | VERIFIED_LOCAL |
| Chinese product language | Main agent; settlement pages, labels and status/action mappings | Main flow no longer exposes the requested English state/capability labels; internal protocol values remain compatible | VERIFIED_LOCAL |
| Verification | Main agent | Frontend 66 tests, typecheck, ESLint, Vite build, production/brand guards; backend compile and 20 focused workflow/security/trusted-space tests passed | VERIFIED_LOCAL |
| GitHub synchronization | Main agent owns release convergence | `main` and `agent/deep-brand-green` point to the same pushed release; no force push | SYNCED |
| Render review/test deployment | Main agent owns hosted deployment | `hiddenchain-platform` built the current `main` commit, passed the production guard and readiness probe | LIVE_REVIEW_TEST |

This entry records the current application flow and hosted review/test synchronization. It does not claim production infrastructure, external finality, or a fully deployed cross-domain privacy-compute network.

## Current brand color refresh — 2026-08-22

| Workstream | Execution boundary | Evidence | Status |
| --- | --- | --- | --- |
| Default theme palette | Main agent; `frontend/src/brand-theme.ts`, `styles.css`, trusted-space theme and runtime defaults | Default trusted-space-navy primary is `#1768A0`; platform operations and trusted-space shells share navy/cyan tokens, while green remains semantic success only | VERIFIED_LOCAL |
| Contrast and responsive check | Main agent | White on primary `4.86:1`; desktop and 390px local browser checks show the new color and no horizontal overflow | VERIFIED_LOCAL |
| Release synchronization | Main agent retains commit, push and Render ownership | Local checks passed; GitHub and Render publication follows after the final release commit | PENDING_RELEASE |
## 2026-08-23 当前工作流

| 工作流 | 范围 | 状态 |
| --- | --- | --- |
| 多能源组织与权限 | 五类能源、五个交易中心、监管跨能源申请、平台运维隔离、企业与个人账号权限 | 已实现并测试 |
| 企业连接器 | 五个隔离服务、企业侧 SQLite、固定函数、Ed25519、防重放与隐私阈值 | 已实现并联调 |
| 目录与授权 | 中文目录元数据、企业批准、同能源限制、监管跨能源申请 | 已实现并测试 |
| 受控查询 | 中文意图解析、固定函数执行、签名验证、结果范围和审计 | 已实现并联调 |
| 前端产品化 | 八模块导航、深蓝可信主题、资源名称中文回退、响应式登录 | 已实现并验收 |
| 发布同步 | 本地、GitHub、Render 同一提交 | 待最终测试和发布 |

## 2026-08-23 参与主体页与最终发布同步

| 工作流 | 范围 | 证据 | 状态 |
| --- | --- | --- | --- |
| 参与主体页 | 真实组织/DID目录、DID文档脱敏、动态拓扑、旧身份中心能力和响应式 UI | `IdentityPage.tsx`、身份目录接口、桌面/390px 浏览器检查 | VERIFIED_LOCAL |
| 能源域权限 | 企业/交易中心本域隔离；监管方跨能源查询；企业授权后才能使用 | 后端定向回归、线上监管/热能双角色冒烟 | VERIFIED_LOCAL_AND_ONLINE |
| 本地验证 | 前端 71 项测试、类型检查、ESLint、生产/品牌检查、Vite 构建；后端 157 通过/1 跳过 | GitHub CI 全部成功 | PASS |
| GitHub 同步 | `main` 与 `agent/deep-brand-green` | 两分支均指向 `7828be0afa1d20da733d2b0470b7ff0644653233` | SYNCED |
| Render 评审环境 | `hiddenchain-platform-review.onrender.com` | `/api/health/live` 200、`/api/health/ready` READY、`/api/version` 匹配；身份目录/DID文档/跨域权限冒烟通过 | LIVE_REVIEW_TEST |

Render 仍是公开演示/评审环境，不代表生产部署；企业交付后自行部署到内网。
