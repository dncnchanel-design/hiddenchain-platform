# Workstreams and File Ownership

## Current execution checkpoint — 2026-08-21 (pre-commit)

| Workstream | Execution boundary | Evidence | Status |
| --- | --- | --- | --- |
| Excel batch upload and sample asset | `/root/luna_worker` under `/root` release coordination; `backend/app/services/excel_upload.py`, `backend/tests/test_excel_upload.py`, `frontend/public/sample-data/hiddenchain-excel-batch-data.xlsx`, `tools/build_excel_batch_data.mjs` | Excel focused tests PASS; deterministic 10 × 100 workbook/parser validation PASS | LOCAL_VERIFIED |
| Permission and route convergence | `/root/luna_worker` under `/root` release coordination; auth/data routers, access policy, route map, `ExcelUploadPage`, Workbench and regression scripts | Backend full pytest PASS; frontend 49 tests, lint, typecheck and build PASS; functional regression 104/0 | LOCAL_VERIFIED |
| Release documentation and staging | `/root/luna_worker` performs the delegated documentation/staging checkpoint; `/root` retains commit, push, Render and final release ownership | Three release ledgers updated; exact staging is pending this checkpoint | PRE_COMMIT_REVIEW |
| Render review/test verification | `/root` release owner | No deployment attempted in this checkpoint | NOT_RUN_THIS_ROUND |

The existing ownership and historical release entries below remain unchanged. No commit, push, Render action or production-release claim is made by this checkpoint.

Date: 2026-08-20

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
## Frontend delivery checkpoint — 2026-08-20

- Trusted Energy console routes, twelve views, scoped primitives, capability truth fixtures, responsive Agent sheet, and pure tests are complete; precise stage/commit/push remains with `/root`, and Render is out of scope for this checkpoint.
