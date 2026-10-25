# Workstreams and File Ownership

## 业务助手普通数据问法与恢复 — 2026-10-24

| 工作项 | 文件范围与所有权 | 证据 |
| --- | --- | --- |
| 本方目录与角色边界 | assistant.py、新目录测试、旧助手回归；协调Agent | 后端67通过；12业务角色目录元数据，ADMIN正确403 |
| 结果与恢复 | AgentSheet、AssistantPlanView、assistant-state、相关测试/标签/样式；协调Agent | 前端217、lint、构建；原话真实查询、缺编号选择、草稿保留 |
| 独立只读审查 | assistant_catalog_review；无写权限 | 无目录扩权；核验结果与复核回执两项展示回归已修复确认 |
| 持续验收与发布 | verify-deep-workflows.py、进度记录、GitHub/Render；协调Agent | 本地121项/644请求0 FAIL；线上同提交证据 runtime/assistant-catalog-release.json |

## 完整账号与交互复验 — 2026-10-24

| 工作项 | 文件所有权 | 完成与证据 |
| --- | --- | --- |
| 功能清单、真实 HTTP 验收 | 12_FULL_FUNCTION_ACCEPTANCE.md、tools/verify-deep-workflows.py；功能复核 Agent，已交协调 Agent | 新鲜栈 109 项 / 596 请求，0 FAIL；5 不可达状态不计成功 |
| 旧主体/能源/运维隔离 | dependencies、workflow、trade/trust/trust_domain/execution/energy/evidence；权限复核 Agent | 79 新范围测试、合法创建/执行/确认/监管回归通过，最终冻结 |
| 比较、签名、节点预算与日期 | connector main、trusted_query、privacy_attestation、query_periods、self_owned_query；计算复核 Agent | 节点 85、平台组合 180、日期 43 等通过，最终冻结 |
| 助手目标与跨页会话 | assistant、AgentSheet、assistant-context；功能复核 Agent | 后端组合 39、前端 context 4，通过真实 job/资产切页复验 |
| 页面操作与恢复 | data_usage_requests、trust_space、connector_ingestion、查询/申请/目录/合同/连接/风险页面；协调 Agent | 13 账号真实使用，前端最终 206 项及生产构建通过，界面证据保留于独立 JSON |
| 正式发布 | 三份进度记录、GitHub、Render；仅协调 Agent | 以 runtime/account-release-evidence.json 的检查结果与八服务 build_sha 为准 |

## 查询授权入口与历史虚拟数据 — 2026-10-24

| 工作项 | 文件范围 | 状态 |
| --- | --- | --- |
| 未授权查询入口 | QueryPage、query-authorization、usage request API、前端测试；协调 Agent | 前端 192 项、真实普通申请/批准/9 月计算/耗尽再申请、桌面/手机与独立复核通过 |
| 真实额度投影 | data_usage_requests 与 test_usage_request_budget；授权复核 Agent | 18 项新增预算与 12 项既有授权接口定向通过；只投影真实额度，不改审批/执行边界 |
| 2021–2026-09 虚拟数据 | connector main / synthetic_data、demo_seed 及专用测试；数据修复 Agent | 七节点 37 组共 2,124,188 行、平台 29 资产；52 项连接器与签名登记、保留上传/旧版、冷启动定向通过；独立只读复核通过 |
| 验收与发布 | 三份进度记录、最终测试、GitHub 与 Render；协调 Agent | 本地 13 账号/249 次读取/49 业务组与 20 历史查询通过；负责最终同提交 CI 及八服务线上复核 |

## 全账号功能故障排查与修复 — 2026-10-24

| 工作项 | 文件范围 | 状态 |
| --- | --- | --- |
| 根因与线上基线 | 13 账号、249 项接口、8 服务；协调 Agent | 已复现日期覆盖与预置版本到期故障 |
| 数据日期与兼容 | demo_seed、prototype、connector 及定向测试；协调 Agent | 连接器 14 项、后端日期与签名定向回归通过 |
| 查询与权限 | trusted_query、trust_space、local_data_boundary 及独立回归文件；查询修复 Agent | 67 项查询/额度/范围定向检查通过；独立复核通过 |
| 助手与签名恢复 | assistant、did_login 及身份元数据测试；查询修复 Agent | 四类企业助手 17 项、DID 6 项红绿验证通过；写审批权限未扩大 |
| 界面业务操作 | 授权、TTC、报告、异常、助手、通知、旧路由及测试；界面修复 Agent | 前端 177 项、lint、类型与构建通过；主代理完成浏览器实点审批 |
| 验收与发布 | 协调 Agent | 49 组真实 HTTP 流程通过；13 账号与 89 页面检查；负责最终完整回归、同提交 CI 与八服务版本核验 |
| 发布依赖修复 | requirements、pnpm overrides / lock；协调 Agent | 按 OSV 的修复版本升级 OpenTelemetry 与 Zod，兼容检查通过后重新执行同提交门禁 |

## 电力交易计算聊天窗口 — 2026-10-22

| 工作项 | 文件范围 | 状态 |
| --- | --- | --- |
| 计算与权限 | 新增 electricity_calculation 服务、路由及回归测试；main.py 注册路由 | 333 项完整后端回归通过 |
| 聊天交互 | AgentSheet、ElectricityChat、电力计算 API 与独立 CSS | 150 项测试及构建通过；桌面、手机与独立审查通过 |
| 发布补丁 | 后端与连接器依赖；前端清单、锁文件与 overrides；发布边界测试 | PyJWT 2.15.1、AnyIO 4.14.2、certifi 2026.10.19、Vite 6.4.5、Vitest 4.1.12 及间接依赖安全修复；单项编译期 braces 例外到期复查，扫描保持启用 |
| 发布 | 协调 Agent 负责本次变更 commit / push 与 Render SHA 核对 | 依赖补丁定向回归后执行；最终状态见 Actions / Deployments |

既有未提交 README、RELEASE_MANIFEST、打包脚本及未跟踪文档不属于本次修改范围。

## Current test-boundary fix — 2026-08-30

| Workstream | Execution boundary | Evidence | Status |
| --- | --- | --- | --- |
| Test Vault isolation | Backend pytest bootstrap and release-hygiene regression | Session-scoped temporary Vault; normal and fixed-seed random 324-test runs pass; shared historical Vault unchanged | VERIFIED_LOCAL |
| Cross-component verification | Backend, connector and frontend toolchains | Backend 324; connector 13; frontend 149; compile, lint, typecheck, build and production/brand guards pass | VERIFIED_LOCAL |

Raw historical payloads, the demo database and unrelated untracked user work remain outside the change boundary.

## Current comprehensive system upgrade release candidate — 2026-08-29

| Workstream | Execution boundary | Evidence | Status |
| --- | --- | --- | --- |
| Cross-role product completion | Main agent; all platform and Trusted Space routes plus authenticated FastAPI services | Persisted APIs, scoped pagination, deterministic states, retry/error handling and truthful capability labels | VERIFIED_LOCAL |
| Trusted query and connector trust | Main agent; connector, query router, production restart guard and receipt model | Exact version/request/org binding, Ed25519 key fingerprint/rings, durable audit pointer, V2 replay, legacy read-only verification and metadata-only ingestion | VERIFIED_LOCAL |
| Production Agent initialization | Independent version reviewer plus main agent; strict manifest, CLI, Tool catalog and deployment docs | Blank-volume provisioning, issuer/identity/grant conflict rollback, idempotency and readiness; 10 focused tests | VERIFIED_LOCAL |
| Settlement and concurrency | Main agent; TTC attempts/snapshots/results, outbox and scoped audit paths | Historical attempts validate against their own snapshots; current pointer remains exact; CAS/fencing and pagination regressions included in full suite | VERIFIED_LOCAL |
| Frontend usability and layout | Main agent; desktop and 390×844 browser review across business, regulator and admin roles | No text collision, overflow, overlap or horizontal page overflow; 149 tests, lint/typecheck/build and visual guards pass | VERIFIED_LOCAL |
| Release safety | Independent production, configuration and publish reviewers; Git/Docker/Windows/Render boundaries | P0=0, P1=0; 324-test backend suite, 13 connector tests, static guards, secret exclusions and eight-service blueprint pass | READY_FOR_SYNC |
| Publication | Main agent only | Same non-force commit must reach both GitHub branches, pass Actions and be reported by all eight Render services | IN_PROGRESS |

Raw databases, Vault contents, secrets, logs, screenshots and runtime state are outside the publication boundary. Render is explicitly demo/review infrastructure and cannot be used as production evidence.

## Current privacy-proof and evidence-anchor batch — 2026-08-26

| Workstream | Execution boundary | Evidence | Status |
| --- | --- | --- | --- |
| Connector non-export verification | Main agent; connector response envelope, backend attestation validator and trusted query/dashboard routes | Request-hash-bound Ed25519 result signature, aggregate-only scope, raw-field rejection and fail-closed tests | VERIFIED_LOCAL_AND_ONLINE |
| Local privacy capability truthfulness | Main agent; Paillier, secret-sharing analysis, strategy catalog and Compute page | `LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST`, `APPLICATION_PROCESS`, plaintext visibility and `cross_domain_non_export_verified=false` are explicit | VERIFIED_LOCAL |
| FISCO BCOS evidence adapter | Main agent; FISCO relay/JSON-RPC adapter, evidence outbox, formal evidence and status UI | External signer payload, `getTransactionReceipt` verification, no private key in platform; DEMO fallback when unconfigured | IMPLEMENTED_ADAPTER |
| Verification | Main agent | Backend full pytest, connector tests, frontend 72 tests, changed-file lint, build, compileall, production guard and online smoke checks pass | VERIFIED_LOCAL_AND_RENDER |
| Release/deployment | Main agent | GitHub `main` and `agent/deep-brand-green` plus Render `hiddenchain-platform-review` converge at `91967b2bf37ea8d16a1902f7cab465bb95f5f2a7` | PUBLISHED_REVIEW_TEST |

## Current target-site parity batch — 2026-08-25

| Workstream | Execution boundary | Evidence | Status |
| --- | --- | --- | --- |
| Target shell and non-whitelist views | Main agent; trusted-space shell, Workbench, Query, Connector, Strategy Center and Audit Center | Target navigation/order, visual shell, Chinese copy and loading/error/empty states implemented | IMPLEMENTED_LOCAL_FRONTEND |
| Whitelist preservation and subtitle rule | Main agent; shared header primitives and existing whitelist routes | Data Catalog, Privacy Computing and Identity Topology routes/logic retained; explanatory subtitle rendering removed | VERIFIED_LOCAL_FRONTEND |
| Prototype backend actions | Main agent; `backend/app/routers/prototype.py`, API adapter and main router registration | Query, upload, CSV download, policy add/delete, audit verify/tamper/restore use authenticated FastAPI endpoints | IMPLEMENTED_LOCAL_BACKEND |
| Verification | Main agent | Frontend typecheck/lint/build/71 tests/production+brand guards; backend full pytest, compileall and API smoke checks pass | VERIFIED_LOCAL |
| Release/deployment | Main agent retains commit, push, Render and final convergence ownership | Final release synchronization is the next step | PENDING |

## Current Trusted Space authorization closure — 2026-08-24

| Workstream | Execution boundary | Evidence | Status |
| --- | --- | --- | --- |
| Existing five application purposes | Main agent; `ApplyPage.tsx`, `data_usage_requests.py`, authorization records | Five-purpose submit → provider approval → contract/agreement regression passes | VERIFIED_LOCAL |
| Regulatory application purposes | Main agent; `ApplyPage.tsx`, `data_usage_requests.py`, authorization detail | Energy regulation/emergency response whitelist, legal basis and authority reference are sent and displayed | IMPLEMENTED_LOCAL |
| Output-policy preservation | Main agent; `data_usage_requests.py` | Approved contract retains `AGGREGATE_ONLY` or `MASKED_QUERY` selected by the applicant | VERIFIED_LOCAL |
| Verification | Main agent | Backend full pytest; frontend 71 tests; typecheck/Vite build; diff check pass | VERIFIED_LOCAL |
| Release/deployment | Main agent | `d6e7a1e` pushed to GitHub `main` and `agent/deep-brand-green`; Render review/test trigger not available in the current workspace | GITHUB_SYNCED_RENDER_PENDING |

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

## Current energy-domain application boundary — 2026-08-28

| Workstream | Execution boundary | Evidence | Status |
| --- | --- | --- | --- |
| Same-domain discovery | Enterprise and exchange users can discover metadata from other subjects in the same energy domain; raw values remain connector-local | `same_energy_domain_metadata_visible`, catalog/detail regression tests | VERIFIED_LOCAL |
| Electricity/oil application channel | Business users cannot create electricity↔oil access requests; regulator exception remains explicit | `usage_domain_pair_is_closed`, `CROSS_ENERGY_APPLICATION_DISABLED` regression test | VERIFIED_LOCAL |
| Approval to controlled settlement | Approved usage continues to require provider authorization, data commitment and usage-control gates before controlled execution | Existing settlement workflow gates plus full backend regression | VERIFIED_LOCAL |
| GitHub and Render release | Main agent retains commit, push and Render deployment ownership | GitHub `main`/`agent/deep-brand-green` and Render review service passed version, health and energy-domain rule smoke checks | PUBLISHED_REVIEW_TEST |

## 2026-08-29 全系统升级当前工作流

| 工作流 | Owner / 独占范围 | 依赖 | 状态 |
| --- | --- | --- | --- |
| 协调与发布 | `/root`；设计/计划、共享配置、进度账本、最终 Git/GitHub/Render | 全部工作流 | IN_PROGRESS |
| 生产路由边界 | `/root/backend_baseline`；`prototype.py`、`main.py`、相关后端测试 | 阶段 0 后端基线 | IN_PROGRESS |
| 前端拆包与错误恢复 | `/root/frontend_baseline`；可信空间 shell、Workbench ECharts、路由错误边界及测试 | 阶段 0 前端基线 | IN_PROGRESS |
| 秘密/生产配置 | `/root`；ignore、production guard、production compose、Render 配置 | 路由边界合并后 | PENDING |
| 连接器本地接入 | 待当前并行槽释放后分配 | 阶段 1 安全边界 | PENDING |
| 最终验证与发布 | 仅 `/root` 可执行 commit、push、Render 部署和发布账本收敛 | 全量测试与审查 | PENDING |

共享规则：不覆盖用户现有五个 tracked 修改；不提交运行数据库、Vault、密钥、截图或临时工件；原始载荷处置未经用户单独授权不执行。

## 2026-08-29 全系统升级最终候选

| 工作流 | 验收证据 | 状态 |
| --- | --- | --- |
| 后端业务与安全边界 | 270 passed、1 optional dependency skip；production guard、compileall、`pip check` 通过 | VERIFIED_LOCAL |
| 企业连接器 | 7 类主体部署配置；13 项连接器测试、compileall、签名与浏览器直连联调通过 | VERIFIED_LOCAL |
| 前端功能与版式 | 149 tests、ESLint、TypeScript、生产/品牌守卫、Vite build；桌面与 390×844 多角色浏览器 QA 通过 | VERIFIED_LOCAL |
| 发布卫生 | 敏感文件扫描、Compose 解析、Render YAML 解析、PowerShell AST、Windows 包逐文件哈希和 SHA256 通过 | VERIFIED_LOCAL |
| GitHub 同步 | 仅允许审核白名单文件；工作分支与 `main` 非强制收敛到同一待创建提交 | READY_FOR_SYNC |
| Render 评审环境 | 8 个服务声明 `main` + `checksPass`；待 GitHub 全绿后核对 Deployment SHA、平台版本与 7 个连接器健康 | READY_FOR_SYNC |

原始 Vault 与运行数据库继续留在本机并排除，不属于本次 GitHub、Render 或 Windows 交付范围。

## 2026-10-25 自然语言助手修复分工

| 范围 | 所有权 | 验证方式 |
| --- | --- | --- |
| 意图解析、既有模型调用与权限收敛 | 主协调 agent | 严格输出、否定、多意图、缺参、模型异常回退回归 |
| 范围只读目录与有效授权 | assistant_catalog_review | 独立数据库，主体/审计/版本/额度边界与无副作用测试 |
| 问法验收语料和 HTTP 全账号矩阵 | language_acceptance | 56 个问法含 20 个独立保留问法，13 个原有账号，不读取数据库或 Vault |
| 助手列表、候选、导航和管理员入口 | impeccable_finish_reviewer | 原视觉层，实际桌面/窄屏与单元回归 |
| 最终测试、白名单提交、GitHub/Render | 主协调 agent | 精确提交 SHA、Actions 与 8 服务健康 |

所有运行夹具、数据库、日志、凭证与截图留在忽略目录；不纳入发布提交。

### 线上模型失败的第二轮闭环

语言验收保持56条语料、721个适用实例不变，所有初轮FAIL保留；修复由主协调agent收敛。范围审查补充模型误判注入的真实HTTP测试6项，确保候选绑定、旧ID失权、同名消歧、目录范围和运维权限拒绝；另修正独立元数据fixture在HTTP客户端启动前遗留非演示主体的问题，避免随机顺序测试依赖模块次序。

主协调补跑完整离线矩阵，发现同类入门提问13处失败后修复组合识别；范围审查只读复核其不抢占业务查询。另补12个业务账号的真实计算与作业详情/助手读取闭环，本地127通过、ADMIN两项正确拒绝，线上最终版本仍须独立重复。

### 46项前置闭环分工

- assistant_catalog_review：助手query job证据/审计与范围校验、专用回归；不写验收构建器。
- connector_rates：正常HTTP前置构建器及纯单元；不写后端和原问法语料。
- language_acceptance：原harness的显式前置开关、typed对象与严格写守卫及单元；原56/721不变。
- 主协调：结果视图、只读并行worker边界、完整性校验、全功能实测、文档和最终发布。仅协调者提交推送与部署；数据库、Vault、密钥与运行凭据继续留在Git外。
- 补齐前置收口：查询审计69目标、fixture12纯测试、harness30纯测试、合同15新增+7原工作流、前端241及连接器85通过。只读复查还找到正常中断前置与CONSUMED协商漏洞；合同状态/评论策略修复由独立owner完成，native验收器由另一owner补真实中断和aggregate-only PSI公式，主协调者完成121 HTTP与721真实模型候选实跑。最终提交、推送与Render核验仅由主协调者执行。


### 2026-10-25 最后浏览器恢复验收

主协调负责最后浏览器恢复闭环：单组件保留独立目录/案例加载结果；旧会话历史404保持原服务器检查和清除流程。其他产品源文件冻结，运行证据保留，a9c2e61不标最终完成。


### 2026-10-25 返工操作实际闭环

最后覆盖核对由finish_harness只读识别缺口并独占ignored supplemental脚本；主协调实跑发现返工假成功，独占workflow.py及security_gates回归；finish_query_audit只读review共享修复通过。仅主协调提交部署，补充脚本不改权限/预算/seed或创建伪状态。


### 2026-10-25 CI随机签名误判修正

cc06ccb主分支全量983项通过、80%覆盖率，另一分支同源码失败于接入测试把随机公钥中raw子串误判为原始数据。已用合法固定公钥metadata-key-regression-387稳定复现旧误报；将ticket/claims/envelope、持久回执和资源行改为闭合字段集合断言，保留真实签名验证、篡改/跨主体/raw_records请求拒绝与中央无原始记录检查。新增一项回归，最终收集984；产品204个源文件相对cc06ccb完全不变。独立只读review通过，后续最终SHA仍须完成两分支全部CI与8服务现场版本以及全套本地/线上验收；不重试随机数掩盖失败，旧证据保留。
### 2026-10-25 线上失败证据收紧

协调者负责已授权Render只读诊断、发布和单次受控复现；并行子任务仅负责trusted_query安全日志及目标回归、原121验收器三项负例契约。字段边界与错误分类保持不变，45项目标测试及39错误证据拒绝自检通过。保留fd49eff线上30失败报告；尚未宣布最终同步验收完成。
