# Capability Matrix

| Capability | Current `0.2.0` state | Boundary/evidence |
| --- | --- | --- |
| FastAPI business backend | `LOCAL_REAL` | Version `0.2.0`; 117 backend tests, compile and OpenAPI gate passed |
| DID identity lifecycle | `LOCAL_REAL` local record / credential crypto `ADAPTER` | Active/revoked/expired and organization checks are local; no external VC trust fabric claim |
| Data Asset Passport | `LOCAL_REAL` | Metadata/version/passport/quality persistence; reference-only legacy projection, no raw payload import into registry |
| OPA-compatible policy | `LOCAL_REAL` local decision/fallback | Production requires remote OPA and fail-closed readiness; local fallback is non-production only |
| Contract/Agreement | `LOCAL_REAL` local state / EDC mapping `ADAPTER` | Validity windows and policy refs are enforced; no external negotiation runtime |
| Eclipse EDC | `ADAPTER` | Dataspace Protocol projection only; no Java control/data-plane nodes |
| TTC state machine | `LOCAL_REAL` | Persisted Attempts, transitions, state versions, normal/abnormal paths and bypass gates |
| Historical TTC | `LEGACY_UNMIGRATED` | Old tasks without Attempts are isolated; no fabricated trusted history |
| Rule Freeze | `LOCAL_REAL` | Immutable, hashed per-Attempt snapshot over rule/policy/contract/data/algorithm/parameters/units |
| Deterministic settlement | `LOCAL_REAL` | Official values produced by `LOCAL_CONTROLLED_SETTLEMENT_V1`, not by Agents/LLMs |
| MPC integer sum | `LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST` | Real finite-field additive sharing; no independent nodes, authenticated transport, malicious-party protection or cross-domain production privacy |
| TEE/remote attestation | `BLOCKED` | No attested hardware runtime, certificate chain or key-release service |
| Six-Agent controlled workflow | `LOCAL_REAL` local records | Registered Tools, explicit active grants and audited calls; LLM path is optional/advisory |
| Audit | `LOCAL_REAL` | TTC/Tool/failure correlation, report approval/rejection and hash-bound evidence verified |
| Evidence batch/Merkle | `LOCAL_REAL` | Fail-closed A/B/C classification and `SHA256_BINARY_DS_V1`; raw sensitive data excluded |
| Transactional Outbox | `LOCAL_REAL` | Same-transaction enqueue, idempotency, retry, stale-lock recovery and dead-letter states |
| Blockchain anchor | `DEMO` | Local deterministic hash receipt only; no consensus, independent timestamp or external finality |
| PostgreSQL/Redis/MinIO/Milvus | `BLOCKED` for production | External infrastructure, credentials and deployment evidence required |
| Render manifest | `REVIEW_TEST_ONLY` | Free plan, test mode, SQLite, fixture seeding and OPA local fallback; never label production |
| Frontend visual layer | `FROZEN_UNCHANGED` | Data/DTO integration only; brand guard, lint, typecheck, 46 tests and bundle passed |
