from datetime import date

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.database import SessionLocal, engine
from app.main import app
from app.models import AgentEvent, Base, BlockchainEvidence, DidIdentity, Organization, PrivacyComputeJob, SettlementResult, SettlementRule, SettlementTask, TaskParticipant, TrustedExecutionReview, User
from app.routers import evidence, trade
from app.security import create_access_token
from app.seed import ORGS, USERS
from app.services.workflow import _scoped_task_allowed
from app.trust_models import EvidenceBatch, EvidenceOutbox, TtcAttempt


@pytest.fixture(autouse=True)
def reset_test_database():
    """Only identity/task metadata; no fixture seed, Vault or external executor."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for org_id, role, domain, name, credit in ORGS:
            db.add(Organization(org_id=org_id, org_type=role, energy_domain=domain, org_name=name, credit_code=credit))
        db.add(Organization(org_id="other-exchange", org_type="EXCHANGE", energy_domain="electricity", org_name="另一电力交易中心"))
        db.flush()
        for user_id, org_id, username, _password, name, role, permissions in USERS:
            db.add(User(user_id=user_id, org_id=org_id, username=username, password_hash="unused", display_name=name, role_code=role, permissions_json=list(permissions), is_org_owner=True))
            db.add(DidIdentity(did_id=f"did:hiddenchain:org:{org_id}", owner_type="ORG", owner_id=org_id, org_id=org_id, public_key_fingerprint="metadata-only", credential_status="VALID"))
        db.add(User(user_id="other-exchange", org_id="other-exchange", username="other_exchange", password_hash="unused", display_name="另一电力交易中心", role_code="EXCHANGE", permissions_json=["CREATE_COMPUTE_TASK"]))
        db.add(DidIdentity(did_id="did:hiddenchain:org:other-exchange", owner_type="ORG", owner_id="other-exchange", org_id="other-exchange", public_key_fingerprint="metadata-only", credential_status="VALID"))
        db.add(SettlementRule(rule_id="scope-rule", rule_name="权限边界元数据", rule_version="scope-v1", formula_dsl="METADATA_ONLY", rule_hash="a" * 64, status="ACTIVE"))
        db.flush()
        for task_id, creator in (("electric-task", "org-exchange-t01"), ("foreign-task", "other-exchange")):
            db.add(SettlementTask(task_id=task_id, capsule_id=f"capsule-{task_id}", task_name=task_id, trade_batch_no="SCOPE-METADATA", period_start=date(2026, 6, 1), period_end=date(2026, 6, 30), rule_id="scope-rule", creator_org_id=creator))
        db.flush()
        for org_id, role in (("org-generator-t01", "GENERATOR"), ("org-retailer-t01", "RETAILER")):
            db.add(TaskParticipant(task_id="electric-task", org_id=org_id, role_in_task=role))
        db.commit()
    yield
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture
def client():
    instance = TestClient(app, raise_server_exceptions=False)
    yield instance
    instance.close()


def _headers(account, **extra):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == account))
        token = create_access_token(user.user_id, user.role_code, user.org_id)
    return {"Authorization": f"Bearer {token}", **extra}


@pytest.fixture
def artifacts():
    """Synthetic metadata markers, without a compute adapter or raw payloads."""
    with SessionLocal() as db:
        for task_id, owner in (("electric-task", "org-exchange-t01"), ("foreign-task", "other-exchange")):
            task = db.get(SettlementTask, task_id)
            task.current_attempt = 1
            attempt_id = f"attempt-{task_id}"
            db.add(TtcAttempt(attempt_id=attempt_id, task_id=task_id, capsule_id=task.capsule_id, attempt_no=1, trace_id=f"scope-{task_id}"))
            db.add(PrivacyComputeJob(job_id=f"job-{task_id}", task_id=task_id, algorithm_code="METADATA_ONLY", status="SUCCESS"))
            for scope, org_id in (("SUMMARY", None), ("ORG", "org-generator-t01"), ("ORG", "org-retailer-t01")):
                db.add(SettlementResult(task_id=task_id, attempt_id=attempt_id, org_id=org_id, result_scope=scope, result_json={"scope_marker": task_id}, result_hash="a" * 64))
            db.add(BlockchainEvidence(evidence_id=f"evidence-{task_id}", task_id=task_id, stage="SCOPE_TEST", biz_type="SCOPE_TEST", biz_id=task_id, evidence_hash="b" * 64, payload_json={}, tx_hash=f"local-{task_id}", block_height=1))
            db.add(AgentEvent(task_id=task_id, sequence_no=1, agent_code="ORCHESTRATOR", agent_did="did:test:agent", message_type="SCOPE_TEST", tool_name="METADATA_ONLY", input_hash="c" * 64, output_hash="d" * 64, signed_call="metadata-only", details_json={"scope_marker": task_id}))
            db.add(EvidenceBatch(batch_id=f"batch-{task_id}", task_id=task_id, attempt_id=attempt_id, batch_type="SCOPE_TEST", merkle_root="e" * 64, leaf_count=0, sealed_by_did="did:test:actor"))
            db.add(TrustedExecutionReview(request_id=f"request-{task_id}", trace_id=f"review-{task_id}", execution_status="SUCCEEDED", result_hash="f" * 64, caller_identity_json={"organization_id": owner}))
        db.flush()
        for task_id in ("electric-task", "foreign-task"):
            db.add(EvidenceOutbox(outbox_id=f"outbox-{task_id}", aggregate_type="SCOPE_TEST", aggregate_id=task_id, task_id=task_id, batch_id=f"batch-{task_id}", event_type="SCOPE_TEST", idempotency_key=f"scope-outbox-{task_id}", payload_hash="f" * 64, status="PUBLISHED"))
        db.add(EvidenceBatch(batch_id="batch-unbound", batch_type="SCOPE_TEST", merkle_root="e" * 64, leaf_count=0, sealed_by_did="did:test:actor"))
        db.add(BlockchainEvidence(evidence_id="evidence-unbound", stage="SCOPE_TEST", biz_type="SCOPE_TEST", biz_id="unbound", evidence_hash="b" * 64, payload_json={}, tx_hash="local-unbound", block_height=1))
        db.flush()
        db.add(EvidenceOutbox(outbox_id="outbox-unbound", aggregate_type="SCOPE_TEST", aggregate_id="unbound", batch_id="batch-unbound", event_type="SCOPE_TEST", idempotency_key="scope-outbox-unbound", payload_hash="f" * 64, status="PUBLISHED"))
        db.commit()


@pytest.mark.parametrize("account", ["exchange_coal", "exchange_heat", "exchange_gas", "exchange_oil", "other_exchange"])
@pytest.mark.parametrize("operation", ["list", "read", "run"])
def test_foreign_exchange_cannot_list_read_or_run_electricity_tasks(client, monkeypatch, account, operation):
    calls = []
    monkeypatch.setattr(trade, "run_settlement_workflow", lambda *_args, **kwargs: calls.append(kwargs["task_id"]) or {"entered_execution": True})
    headers = _headers(account)
    if operation == "list":
        response = client.get("/api/settlement/tasks", headers=headers)
        assert response.status_code == 200, response.text
        assert "electric-task" not in response.text
    elif operation == "read":
        response = client.get("/api/settlement/tasks/electric-task", headers=headers)
        assert response.status_code in {403, 404}, response.text
    else:
        response = client.post("/api/settlement/tasks/electric-task/run", headers={**headers, "If-Match": '"1"', "Idempotency-Key": f"foreign-run-{account}"}, json={"compute_mode": "LOCAL_CONTROLLED", "algorithm_code": "CONTROLLED_SETTLEMENT_V1"})
        assert response.status_code in {403, 404}, response.text
    assert calls == []


@pytest.mark.parametrize("account", ["exchange_coal", "exchange_heat", "exchange_gas", "exchange_oil", "other_exchange", "admin"])
def test_shared_workflow_scope_does_not_grant_trusted_roles_global_access(account):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == account))
        assert _scoped_task_allowed(db, db.get(SettlementTask, "electric-task"), user) is False


def test_creator_participants_and_scoped_regulator_keep_legitimate_reads(client, monkeypatch):
    for account in ("exchange", "generator", "retailer", "regulator"):
        response = client.get("/api/settlement/tasks/electric-task", headers=_headers(account))
        assert response.status_code == 200, (account, response.text)
    monkeypatch.setattr(trade, "run_settlement_workflow", lambda *_args, **_kwargs: {"authorized_executor_entered": True})
    run = client.post("/api/settlement/tasks/electric-task/run", headers=_headers("exchange", **{"If-Match": '"1"', "Idempotency-Key": "own-electricity-run"}), json={"compute_mode": "LOCAL_CONTROLLED", "algorithm_code": "CONTROLLED_SETTLEMENT_V1"})
    assert run.status_code == 200, run.text


@pytest.mark.parametrize("path", ["/api/rules", "/api/algorithms/registry", "/api/privacy/analysis/jobs", "/api/trusted-execution/status", "/api/trusted-execution/reviews", "/api/agents/llm/status"])
def test_admin_has_no_legacy_business_read_access(client, path):
    response = client.get(path, headers=_headers("admin"))
    assert response.status_code == 403, response.text


@pytest.mark.parametrize(("path", "body"), [
    ("/api/agents/ORCHESTRATOR/invoke", {"task_id": "electric-task", "instruction": "权限边界检查"}),
    ("/api/agents/invoke-all", {"task_id": "electric-task"}),
    ("/api/trust-domain/tasks/electric-task/transitions", {"to_state": "CANCELLED", "trigger": "SCOPE_TEST", "reason": "权限边界检查"}),
    ("/api/trust-domain/tasks/electric-task/rule-freeze", {"contract_ids": ["missing"], "data_upload_ids": ["missing"], "algorithm": {"code": "CONTROLLED_SETTLEMENT_V1"}, "trace_id": "scope-test-freeze"}),
])
def test_admin_cannot_mutate_legacy_business_tasks(client, path, body):
    response = client.post(path, headers=_headers("admin", **{"If-Match": '"1"'}), json=body)
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("account", ["exchange_coal", "exchange_heat", "exchange_gas", "exchange_oil", "other_exchange"])
@pytest.mark.parametrize("operation", ["transitions", "rule-freeze"])
def test_legacy_ttc_alias_does_not_bypass_task_scope(client, account, operation):
    body = {"to_state": "CANCELLED", "trigger": "SCOPE_TEST", "reason": "无权主体不能取消其他交易中心任务"} if operation == "transitions" else {"contract_ids": ["missing"], "data_upload_ids": ["missing"], "algorithm": {"code": "CONTROLLED_SETTLEMENT_V1"}, "trace_id": "scope-freeze-test"}
    response = client.post(f"/api/trust-domain/tasks/electric-task/{operation}", headers=_headers(account, **{"If-Match": '"1"'}), json=body)
    assert response.status_code in {403, 404}, response.text
    with SessionLocal() as db:
        assert db.get(SettlementTask, "electric-task").ttc_state == "INIT"


def test_regulator_requires_current_audit_scope_for_legacy_tasks(client):
    with SessionLocal() as db:
        user = db.get(User, "user-regulator")
        user.permissions_json = ["VIEW_AUDIT", "VIEW_AUDIT:TASK:foreign-task"]
        db.commit()
    allowed = client.get("/api/settlement/tasks/foreign-task", headers=_headers("regulator"))
    denied = client.get("/api/settlement/tasks/electric-task", headers=_headers("regulator"))
    assert allowed.status_code == 200, allowed.text
    assert denied.status_code in {403, 404}, denied.text


@pytest.mark.parametrize("path", ["/api/admin/overview", "/api/admin/system", "/api/admin/agents", "/api/metrics/summary", "/api/audit/logs", "/api/notification-outbox/status", "/api/evidence/outbox"])
def test_admin_operational_surfaces_remain_available(client, path):
    response = client.get(path, headers=_headers("admin"))
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("account", [entry[2] for entry in USERS] + ["other_exchange"])
def test_all_accounts_keep_the_same_scope_on_related_legacy_lists(client, artifacts, account):
    allowed = account in {"exchange", "generator", "retailer", "regulator"}
    paths = ("/api/privacy/jobs", "/api/settlement/results", "/api/chain/evidence", "/api/agents/events", "/api/evidence/batches")
    for path in paths:
        response = client.get(path, headers=_headers(account))
        if account == "admin" or path == "/api/agents/events" and account in {"generator", "retailer", "coal", "heat", "gas", "oil"}:
            assert response.status_code == 403, (account, path, response.text)
        else:
            assert response.status_code == 200, (account, path, response.text)
            assert ("electric-task" in response.text) is allowed, (account, path, response.text)


def test_regulator_evidence_and_legacy_review_reads_follow_individual_scope(client, artifacts, monkeypatch):
    with SessionLocal() as db:
        user = db.get(User, "user-regulator")
        user.permissions_json = ["VIEW_AUDIT", "VIEW_AUDIT:TASK:foreign-task", "VIEW_AUDIT:ORG:other-exchange"]
        db.commit()
    for path in ("/api/evidence/batches", "/api/evidence/outbox", "/api/chain/evidence", "/api/agents/events", "/api/trusted-execution/reviews"):
        response = client.get(path, headers=_headers("regulator"))
        assert response.status_code == 200, (path, response.text)
        assert "foreign-task" in response.text and "electric-task" not in response.text, (path, response.text)
    detail = client.get("/api/trusted-execution/reviews/request-electric-task", headers=_headers("regulator"))
    audit = client.get("/api/trusted-execution/audit/request-electric-task", headers=_headers("regulator"))
    assert detail.status_code == audit.status_code == 404
    calls = []
    monkeypatch.setattr(evidence, "process_local_demo_outbox", lambda *_args, **_kwargs: calls.append(True) or [])
    denied = client.post("/api/evidence/outbox/process", headers=_headers("regulator"))
    assert denied.status_code == 403 and calls == []
    operational = client.post("/api/evidence/outbox/process", headers=_headers("admin"))
    assert operational.status_code == 200 and calls == [True]


def test_legacy_reviews_are_owned_and_admin_cannot_evaluate_business_models(client, artifacts):
    listing = client.get("/api/trusted-execution/reviews", headers=_headers("exchange"))
    assert listing.status_code == 200 and "electric-task" in listing.text and "foreign-task" not in listing.text
    foreign = client.get("/api/trusted-execution/reviews/request-foreign-task", headers=_headers("exchange"))
    assert foreign.status_code == 404
    denied = client.post("/api/energy/solar/evaluate", headers=_headers("admin"), json={"latitude": 36, "longitude": 117, "timestamp_utc": "2026-06-01T04:00:00Z", "surface_tilt": 30, "surface_azimuth": 180, "ghi_wm2": 800, "dni_wm2": 600, "dhi_wm2": 200})
    assert denied.status_code == 403, denied.text


@pytest.mark.parametrize(("account", "task_id"), [("exchange", "electric-task"), ("regulator", "electric-task"), ("regulator", "foreign-task")])
def test_legal_legacy_operator_can_cancel_an_authorized_task(client, account, task_id):
    response = client.post(f"/api/trust-domain/tasks/{task_id}/transitions", headers=_headers(account, **{"If-Match": '"1"'}), json={"to_state": "CANCELLED", "trigger": "AUTHORIZED_CANCEL", "reason": "有权业务主体取消隔离验收任务"})
    assert response.status_code == 200, response.text
    assert response.json()["ttc_state"] == "CANCELLED"


def test_only_explicit_global_audit_grant_includes_unbound_evidence(client, artifacts):
    for path in ("/api/evidence/batches", "/api/evidence/outbox", "/api/chain/evidence"):
        global_read = client.get(path, headers=_headers("regulator"))
        assert global_read.status_code == 200 and "unbound" in global_read.text, (path, global_read.text)
    with SessionLocal() as db:
        user = db.get(User, "user-regulator")
        user.permissions_json = ["VIEW_AUDIT", "VIEW_AUDIT:TASK:foreign-task"]
        db.commit()
    for path in ("/api/evidence/batches", "/api/evidence/outbox", "/api/chain/evidence"):
        limited_read = client.get(path, headers=_headers("regulator"))
        assert limited_read.status_code == 200 and "unbound" not in limited_read.text, (path, limited_read.text)


def test_run_replay_checks_tenant_scope_before_returning_an_existing_attempt(client, artifacts):
    with SessionLocal() as db:
        task = db.get(SettlementTask, "electric-task")
        task.status = "PENDING_CONFIRMATION"
        attempt = db.get(TtcAttempt, "attempt-electric-task")
        attempt.request_idempotency_key = "previous-authorized-run"
        db.commit()
    response = client.post("/api/settlement/tasks/electric-task/run", headers=_headers("other_exchange", **{"If-Match": '"1"', "Idempotency-Key": "previous-authorized-run"}), json={"compute_mode": "LOCAL_CONTROLLED", "algorithm_code": "CONTROLLED_SETTLEMENT_V1"})
    assert response.status_code in {403, 404}, response.text
    assert "scope_marker" not in response.text


@pytest.mark.parametrize("account", ["exchange_coal", "exchange_heat", "exchange_gas", "exchange_oil"])
@pytest.mark.parametrize("operation", ["create", "activate"])
def test_non_electric_exchange_cannot_change_electricity_settlement_rules(client, account, operation):
    if operation == "create":
        response = client.post("/api/rules", headers=_headers(account), json={"rule_name": "隔离权限检查", "contract_price": 400, "deviation_threshold_mwh": 0, "deviation_penalty_rate": 0, "service_fee_rate": 0})
    else:
        response = client.post("/api/rules/scope-rule/activate", headers=_headers(account))
    assert response.status_code == 403, response.text
