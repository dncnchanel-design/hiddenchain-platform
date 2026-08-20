# Frontend to Backend Matrix

| Page/domain | Existing source | Target trusted source | Status |
| --- | --- | --- | --- |
| Login/session | `/api/auth/login`, `/api/auth/me` | Existing RBAC plus structured error/trace metadata | Implemented compatibly |
| Workbench | tasks, organizations, dashboard, rules | Backend-authoritative `allowed_actions`, blockers, next action, TTC state | Implemented in task DTOs/hooks |
| Data pages | `/api/data/uploads` | DataSource, Asset, AssetVersion, Passport, Quality, controlled DataRef | Implemented; legacy upload shape retained |
| Data space | catalog and agreements | Versioned policy/contract references and explicit EDC adapter state | Local control-plane records implemented; EDC remains `ADAPTER` |
| Rules | settlement rules | Immutable execution snapshot linked to TTC Attempt | Implemented through Rule Freeze |
| Settlement create/detail | SettlementTask and workflow bundle | Idempotent TTC aggregate, attempts, transitions, snapshot and evidence/Outbox status | Implemented; old tasks report `LEGACY_UNMIGRATED` |
| Compute | PrivacyComputeJob | Algorithm registry, execution snapshot, truthful MPC/TEE labels | Implemented locally; MPC is single-host experimental, TEE `BLOCKED` |
| Results | SettlementResult | Deterministic result, snapshot/output hashes and confirmation gate | Implemented |
| Evidence | local evidence ledger | A/B/C records, Merkle batch, Outbox, anchor receipt and capability label | Implemented locally; anchor remains `DEMO` |
| Audit/reports/anomalies | audit APIs | TTC-correlated transitions, Tool calls, failures and evidence refs | Implemented additively |
| Agents | definitions/events | Agent DID, Tool schema, explicit permission, human gate and Tool-call audit | Implemented as local controlled workflow records |
| System/metrics | health and summaries | liveness, readiness, version/build SHA, dependency and capability state | Implemented for `0.2.0` |

Compatibility rule: existing array/record response shapes remain available; new fields are additive unless a test proves a safe adapter.

Frontend scope rule: this work changes API clients, DTOs, hooks, authoritative state/action consumption and compatible page data bindings only. Navigation, layout, colors, typography, component hierarchy and visual direction remain frozen. The main verification gate passed lint, typecheck, tests, production/brand guards and the production bundle.
