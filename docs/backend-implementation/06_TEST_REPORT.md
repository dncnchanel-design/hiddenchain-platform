# Verification Report

Date: 2026-08-20
Version: `0.2.0`
Overall local status: `PASS`
Remote code release status: `PASS`
Hosted CI status: `PASS`
Render review/test status: `BLOCKED_NO_SERVER`

| Gate | Status | Evidence |
| --- | --- | --- |
| Build | PASS | Python `compileall`; TypeScript `tsc -b`; Vite production build, 2,198 modules |
| Unit tests | PASS | Backend collection and full run: 117 passed; frontend Vitest: 46 passed in 7 files |
| Branch coverage | PASS | coverage.py 7.15.4 fixed-seed replay: 79% total against the enforced 75% floor; local replay used the preinstalled Python 3.14 toolchain, and feature-branch CI will repeat on Python 3.12 |
| Integration tests | PASS | Full FastAPI/SQLAlchemy suite passed with fresh seeded database per test |
| Security tests | PASS | 12 dedicated security-gate cases plus full-suite authorization and integrity coverage |
| Failure/retry/idempotency | PASS | Failed anchor receipts, retry/dead-letter, stale claims, replay conflicts, rejection/rework and command idempotency covered |
| API contract | PASS | OpenAPI `0.2.0` serialized successfully with 69 paths; structured errors, ETag and idempotency metadata covered |
| E2E | PASS | Service/API import-and-run, Agent-native workflow and final confirmation-to-archive paths passed |
| Golden path | PASS | 3 explicit targeted golden-path tests passed |
| Capability-label inventory | PASS | MPC=`LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST`, EDC=`ADAPTER`, TEE=`BLOCKED`, anchor=`DEMO` |
| State-machine bypass attempts | PASS | Normal-state artifacts are checked under a task row lock; public normal transitions are denied |
| Agent over-permission | PASS | DID/Tool grants are checked before data, compute or external side effects; revoked/out-of-scope calls fail closed |
| Secret leakage | PASS | High-confidence credential scan found no private keys, cloud/PAT/API tokens; production source guard passed |
| Frontend regression | PASS | ESLint, TypeScript, 46 tests, production guard, brand guard and bundle passed; no CSS, routes, navigation or visual-system redesign |
| Local implementation commit | PASS | `71de395bf658fa34c8d271705ace130d9abf0e24`; cached scope 70 files, protected assets excluded |
| Remote-history reconciliation | PASS | Remote ref fetched; equivalent duplicate history merged without conflicts as `562f762`; post-merge golden paths passed |
| GitHub push and remote SHA | PASS | Non-force push completed; `ls-remote` returned `fa04fdc7e1d87761010fb7d2fc523d436ab54b77`, matching local HEAD |
| Hosted GitHub CI | PASS | Backend/API contract, frontend, Trivy, SBOM, OPA, SHACL, security and coverage workflows passed |

## Commands and observations

```text
backend\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp=runtime\pytest-basetemp-final-contract-20260820 -q
  PASS; 117 collected tests, full run exit 0

backend\.venv\Scripts\python.exe -m pytest <three explicit golden paths> -q
  3 passed

D:\Python\python.exe -m coverage run --branch --source=backend/app -m pytest -q --randomly-seed=20260816 -p no:cacheprovider --basetemp=backend/runtime/pytest-basetemp-coverage-final-20260820
D:\Python\python.exe -m coverage report --fail-under=75
  PASS; 117 tests; TOTAL 79%; the repository basetemp avoids the host temp-directory access restriction

backend\.venv\Scripts\python.exe -m compileall -q app tests
backend\.venv\Scripts\python.exe -m pip check
backend\.venv\Scripts\python.exe scripts\check_production.py
  PASS; no broken requirements; production guard PASS

OpenAPI serialization
  PASS; 69 paths, version 0.2.0

frontend: ESLint / Vitest / TypeScript / production guard / brand guard / Vite build
  PASS; 7 files and 46 tests; 2,198 modules built

YAML parsing: render.yaml, docker-compose.production.yml and all three modified GitHub workflows
  PASS
```

## Environment-bound checks

| Check | Status | Reason |
| --- | --- | --- |
| Real PostgreSQL migration/advisory-lock run | BLOCKED | No PostgreSQL instance is available; dialect SQL and migration behavior are covered locally |
| Docker production image build | BLOCKED | Docker is not installed on this host; source and production guards passed and CI retains the image/security gates |
| Browser/Render online smoke | BLOCKED | Derived service URL returns Render `x-render-routing: no-server` / HTTP 404; no deployed instance exists to probe |
| GitHub Python 3.12 coverage replay | PASS | `backend-tests` workflow passed on the pushed branch |
| External EDC, TEE, chain consensus and cross-domain MPC | BLOCKED | External runtimes, credentials, independent nodes and proof infrastructure are not present |

The Starlette/httpx compatibility deprecation warning is known and non-failing. It does not change the verification result.
