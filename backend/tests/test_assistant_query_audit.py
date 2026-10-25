"""Query-job assistant reads use real scoped task/receipt metadata, without seed data."""
from copy import deepcopy
from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal, engine
from app.main import app
from app.models import (
    AssistantPlanStep, AuditLog, AuditReport, Base, BlockchainEvidence,
    DataRequestBatch, DataRequestItem, DataUsageRequest, DidIdentity, ExecutionReceipt,
    Organization, PrivacyComputeJob, SettlementRule, SettlementTask, TrustedQueryTask,
    User, utc_now,
)
from app.security import create_access_token, sha256_json
from app.services.assistant_catalog import read_action, target_candidates, validate_target
from app.services.rate_limit import limiter
from app.trust_models import AgentTool, DataAsset, DataAssetVersion, DataSource


PREFIX = "/api/trust-space/assistant"
AUDIT_ACTIONS = ("VERIFY_EVIDENCE_SUMMARY", "EXPLAIN_AUDIT")


def _query(db, applicant, provider):
    task_id, job_id, receipt_id, item_id, request_id, batch_id = (str(uuid4()) for _ in range(6))
    db.add(DataUsageRequest(
        request_id=request_id, asset_id="asset-" + provider, asset_version_id="version-" + provider,
        applicant_user_id=applicant, applicant_org_id=applicant, provider_org_id=provider,
        applicant_did="did:test:" + applicant, provider_did="did:test:" + provider,
        purpose="受控查询", usage_mode="MPC_AGGREGATE", duration_days=30,
        expires_at=utc_now() + timedelta(days=30), status="APPROVED", trace_id=request_id,
    ))
    db.add(DataRequestBatch(
        batch_id=batch_id, applicant_user_id=applicant, applicant_org_id=applicant,
        purpose="受控查询", confirmation_hash="c" * 64, idempotency_key=task_id,
    ))
    db.flush()
    db.add(DataRequestItem(
        request_item_id=item_id, batch_id=batch_id, provider_org_id=provider,
        asset_id="asset-" + provider, authorization_id=request_id,
        idempotency_key=task_id, status="SUCCEEDED", result_hash="b" * 64,
    ))
    db.flush()
    db.add(TrustedQueryTask(
        task_id=task_id, applicant_user_id=applicant, applicant_org_id=applicant,
        operation_namespace="ASSISTANT_QUERY_AUDIT_TEST", idempotency_key=task_id,
        request_fingerprint="f" * 64, canonical_payload_json={"resource": "登记数据"},
        authorization_id=request_id, provider_org_id=provider,
        asset_id="asset-" + provider, asset_version_id="version-" + provider,
        request_item_id=item_id, status="SUCCEEDED", result_hash="b" * 64,
        result_json={"private_aggregate": "never-return-query-result"},
    ))
    pointer = {
        "status": "VERIFIED", "pointer_verified": True, "event_hash_verified": True,
        "verification_scope": "SINGLE_SIGNED_EVENT_POINTER", "action": "LOCAL_CONTROLLED_RESULT_ISSUED",
        "connector_id": "node-" + provider, "organization_id": provider, "energy_domain": provider,
        "sequence": 7, "previous_hash": "d" * 64, "audit_hash": "e" * 64,
    }
    privacy = {
        "status": "VERIFIED", "request_hash": "a" * 64, "result_hash": "b" * 64,
        "signature_claim_verified": True, "result_scope": "AGGREGATE_ONLY",
        "raw_records_returned": False, "raw_data_exported": False,
    }
    db.add(PrivacyComputeJob(
        job_id=job_id, task_id=task_id, algorithm_code="SUM", adapter_code="LOCAL_SUBJECT_NODE_" + provider,
        output_hash="b" * 64, status="SUCCEEDED", result_json={"private_aggregate": "never-return-job-result"},
        execution_attestation_json={
            "authorization_id": request_id, "applicant_org_id": applicant, "applicant_user_id": applicant,
            "provider_org_id": provider, "request_item_id": item_id, "node_code": "node-" + provider,
            "connector_signature_verified": True, "connector_audit_event_verified": True,
            "cross_domain_non_export_verified": True, "receipt_verification_schema": "TRUSTED_QUERY_RECEIPT_V2",
            "raw_records_returned": False, "raw_data_exported": False,
            "connector_audit": pointer, "privacy_verification": privacy,
        },
    ))
    db.add(ExecutionReceipt(
        receipt_id=receipt_id, request_item_id=item_id, provider_org_id=provider, task_id=task_id,
        request_hash="a" * 64, result_hash="b" * 64, node_code="node-" + provider,
        node_signature="never-return-node-signature", visible_to_orgs_json=[applicant, provider],
        audit_sequence=7, previous_audit_hash="d" * 64, connector_audit_hash="e" * 64,
        audit_event_verified=True, result_summary_json={"signed_result": "never-reopen-signed-result"},
    ))
    db.add(AuditLog(
        actor_user_id=applicant, actor_org_id=applicant, actor_name=applicant,
        action_code="CONTROLLED_QUERY_COMPLETED", target_type="TRUSTED_QUERY_TASK", target_id=task_id,
        result="SUCCESS", trace_id=task_id, details_json={"private_body": "never-return-audit-body"},
    ))
    db.flush()
    return {"job_id": job_id, "task_id": task_id, "receipt_id": receipt_id}


@pytest.fixture(autouse=True)
def reset_test_database():
    """No real database, Vault payloads, connector or model calls are needed."""
    limiter.reset()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for account, role, domain in (
            ("exchange_coal", "EXCHANGE", "coal"), ("exchange_oil", "EXCHANGE", "oil"),
            ("exchange_electric", "EXCHANGE", "electricity"), ("regulator", "REGULATOR", "multi_energy"),
            ("coal", "COAL_ENTERPRISE", "coal"), ("oil", "OIL_ENTERPRISE", "oil"), ("admin", "ADMIN", "electricity"),
        ):
            db.add(Organization(org_id=account, org_name=account, org_type=role, energy_domain=domain))
            db.flush()
            db.add(User(user_id=account, org_id=account, username=account, password_hash="unused",
                        display_name=account, role_code=role, permissions_json=["VIEW_DATA", "VIEW_AUDIT"]))
            db.add(DidIdentity(did_id="did:test:" + account, owner_type="ORG", owner_id=account,
                               org_id=account, public_key_fingerprint="a" * 64, credential_status="VALID"))
        db.flush()
        db.add(User(user_id="no-audit", org_id="exchange_coal", username="no-audit", password_hash="unused",
                    display_name="no-audit", role_code="EXCHANGE", permissions_json=["VIEW_DATA"]))
        for provider in ("coal", "oil"):
            db.add(DataSource(source_id="source-" + provider, source_code="source-" + provider,
                              source_name=provider, owner_org_id=provider, source_type="ENTERPRISE_CONNECTOR", security_domain=provider))
            db.flush()
            db.add(DataAsset(asset_id="asset-" + provider, asset_code="asset-" + provider, asset_name=provider,
                             source_id="source-" + provider, owner_org_id=provider, asset_type="ENERGY_METRIC",
                             classification="ENTERPRISE_DATA_PRODUCT", sensitivity_level="L2"))
            db.flush()
            db.add(DataAssetVersion(version_id="version-" + provider, asset_id="asset-" + provider, version_no=1,
                                    schema_version="metadata", data_ref="connector://metadata-only", data_hash="a" * 64,
                                    immutable_hash="b" * 64, record_count=1))
        db.flush()
        fixtures = {
            "exchange": _query(db, "exchange_coal", "coal"),
            "exchange_second": _query(db, "exchange_coal", "coal"),
            "regulator": _query(db, "regulator", "coal"),
            "foreign": _query(db, "exchange_oil", "oil"),
        }
        db.add(SettlementRule(rule_id="rule", rule_name="规则", rule_version="1", formula_dsl="{}", rule_hash="a" * 64))
        db.flush()
        db.add(SettlementTask(task_id="settlement-owned", capsule_id="settlement-owned", task_name="原交易任务",
                              trade_batch_no="settlement-owned", period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
                              creator_org_id="exchange_electric", rule_id="rule", ttc_state="INIT", status="DRAFT"))
        db.flush()
        payload = {"controlled_metadata": "settlement"}
        db.add(BlockchainEvidence(evidence_id="settlement-evidence", task_id="settlement-owned", stage="AUDIT",
                                  biz_type="AUDIT_REPORT", biz_id="settlement-report", evidence_hash=sha256_json(payload),
                                  payload_json=payload, tx_hash="local-tx", block_height=1))
        db.add(AuditReport(report_id="settlement-report", task_id="settlement-owned", template_code="AUDIT",
                           report_title="原审计报告", report_content="private-report-body", report_hash="c" * 64, risk_level="LOW"))
        for code in ("WorkflowEngine", "EvidenceGraph+LocalEvidenceLedger+RiskRuleEngine", "TemplateAuditFallback"):
            db.add(AgentTool(tool_code=code, tool_name=code, service_code="ASSISTANT_TEST"))
        db.commit()
    yield fixtures
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def http():
    # Exercise HTTP routing without starting the demo seeder or background workers.
    client = TestClient(app)
    yield client
    client.close()


def _headers(account):
    with SessionLocal() as db:
        user = db.get(User, account)
        return {"Authorization": "Bearer " + create_access_token(user.user_id, user.role_code, user.org_id)}


def _start(http, account, job_id=None):
    body = {"page_path": "/trusted-space/workbench"}
    if job_id:
        body.update(entity_type="privacy_compute_job", entity_id=job_id)
    response = http.post(PREFIX + "/sessions", headers=_headers(account), json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _ask(http, account, session, content):
    response = http.post(f"{PREFIX}/sessions/{session['session_id']}/messages",
                         headers={**_headers(account), "If-Match": f'"{session["state_version"]}"'}, json={"content": content})
    assert response.status_code == 201, response.text
    return response.json()


def _execute(http, account, planned):
    plan = planned["plan"]
    response = http.post(f"{PREFIX}/sessions/{planned['session']['session_id']}/plans/{plan['plan_id']}/execute",
                         headers={**_headers(account), "If-Match": f'"{plan["state_version"]}"'},
                         json={"step_id": plan["steps"][0]["step_id"]})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("account,key", [("exchange_coal", "exchange"), ("regulator", "regulator")])
@pytest.mark.parametrize("action", AUDIT_ACTIONS)
def test_query_audit_reads_real_receipts_and_reports_only_existing_facts(db, reset_test_database, account, key, action):
    fixture = reset_test_database[key]
    output = read_action(db, db.get(User, account), action, fixture["job_id"], "privacy_compute_job")
    assert output["status"] == "SUCCEEDED" and output["verification_status"] == "MATCHED"
    assert output["job_id"] == fixture["job_id"] and output["task_id"] == fixture["task_id"]
    assert output["evidence_kind"] == "EXECUTION_RECEIPT" and output["receipt_count"] == 1
    assert output["report_count"] == output["evidence_count"] == 0 and output["audit_log_count"] == 1
    assert output["raw_data_accessed"] is False
    receipt = output["items"][0]
    assert receipt["receipt_id"] == fixture["receipt_id"] and "evidence_id" not in receipt
    assert receipt["audit_event_verified"] is True and receipt["verify"]["matched"] is True
    assert receipt["request_hash"] == "a" * 64 and receipt["result_hash"] == "b" * 64
    assert all(secret not in str(output) for secret in ("never-return", "never-reopen", "private-report", "signed_result"))
    if action == "EXPLAIN_AUDIT":
        assert "暂无正式审计报告" in output["explanation"]
    assert db.scalar(select(func.count(SettlementTask.task_id))) == 1
    assert db.scalar(select(func.count(AuditReport.report_id))) == 1
    assert db.scalar(select(func.count(BlockchainEvidence.evidence_id))) == 1


@pytest.mark.parametrize("action", AUDIT_ACTIONS)
def test_audit_candidates_intersect_job_party_scope_and_real_query_audit_scope(db, reset_test_database, action):
    exchange = db.get(User, "exchange_coal")
    candidates = target_candidates(db, exchange, action)
    assert {item["entity_id"] for item in candidates} == {
        reset_test_database["exchange"]["job_id"], reset_test_database["exchange_second"]["job_id"],
    }
    assert all(set(item) == {"entity_id", "entity_type", "label", "status"} for item in candidates)
    assert candidates == target_candidates(db, exchange, action)
    regulator = db.get(User, "regulator")
    regulator.permissions_json += ["VIEW_AUDIT:ALL"]
    db.flush()
    assert {item["entity_id"] for item in target_candidates(db, regulator, action)} == {
        reset_test_database["regulator"]["job_id"], "settlement-owned",
        "settlement-report" if action == "EXPLAIN_AUDIT" else "settlement-evidence",
    }
    assert read_action(db, regulator, action, reset_test_database["foreign"]["job_id"], "privacy_compute_job")["error_code"] == "COMPUTE_SCOPE_DENIED"
    assert target_candidates(db, db.get(User, "no-audit"), action) == []
    assert read_action(db, db.get(User, "no-audit"), action, reset_test_database["exchange"]["job_id"], "privacy_compute_job")["error_code"] == "AUDIT_SCOPE_DENIED"


@pytest.mark.parametrize("action", AUDIT_ACTIONS)
def test_visible_job_cannot_bypass_query_audit_scope_or_fabricate_a_query_binding(db, reset_test_database, action):
    job = db.get(PrivacyComputeJob, reset_test_database["foreign"]["job_id"])
    job.execution_attestation_json = {**job.execution_attestation_json, "applicant_org_id": "exchange_coal"}
    db.flush()
    assert read_action(db, db.get(User, "exchange_coal"), action, job.job_id, "privacy_compute_job")["error_code"] == "AUDIT_SCOPE_DENIED"
    job.task_id = "no-real-query-task"
    db.flush()
    assert read_action(db, db.get(User, "exchange_coal"), action, job.job_id, "privacy_compute_job")["error_code"] == "AUDIT_SCOPE_DENIED"


@pytest.mark.parametrize("fault,expected", [
    ("missing_receipt", "UNVERIFIED"), ("failed_query", "UNVERIFIED"),
    ("failed_signature", "MISMATCH"), ("failed_audit", "MISMATCH"),
    ("wrong_request_hash", "MISMATCH"), ("wrong_result_hash", "MISMATCH"),
    ("wrong_item", "MISMATCH"), ("wrong_query_hash", "MISMATCH"),
    ("wrong_pointer", "MISMATCH"), ("missing_proof", "UNVERIFIED"),
    ("raw_export", "MISMATCH"),
])
def test_missing_failed_or_unbound_query_proof_never_claims_verification(db, reset_test_database, fault, expected):
    fixture = reset_test_database["exchange"]
    job, task, receipt = db.get(PrivacyComputeJob, fixture["job_id"]), db.get(TrustedQueryTask, fixture["task_id"]), db.get(ExecutionReceipt, fixture["receipt_id"])
    proof = deepcopy(job.execution_attestation_json)
    if fault == "missing_receipt":
        db.delete(receipt)
    elif fault == "failed_query":
        job.status = task.status = "FAILED"
    elif fault == "failed_signature":
        proof["connector_signature_verified"] = False
    elif fault == "failed_audit":
        receipt.audit_event_verified = False
    elif fault == "wrong_request_hash":
        receipt.request_hash = "9" * 64
    elif fault == "wrong_result_hash":
        receipt.result_hash = "9" * 64
    elif fault == "wrong_item":
        proof["request_item_id"] = db.get(TrustedQueryTask, reset_test_database["foreign"]["task_id"]).request_item_id
    elif fault == "wrong_query_hash":
        task.result_hash = "9" * 64
    elif fault == "wrong_pointer":
        receipt.connector_audit_hash = "9" * 64
    elif fault == "missing_proof":
        proof.pop("privacy_verification")
    elif fault == "raw_export":
        proof["raw_data_exported"] = True
    job.execution_attestation_json = proof
    db.flush()
    for action in AUDIT_ACTIONS:
        output = read_action(db, db.get(User, "exchange_coal"), action, job.job_id, "privacy_compute_job")
        assert output["status"] == "SUCCEEDED" and output["verification_status"] == expected
        assert all(item["verify"]["matched"] is False for item in output["items"])
        assert "不能认定核验通过" in output["explanation"] and output["raw_data_accessed"] is False
        if fault == "failed_query":
            assert "FAILED" in output["explanation"]


def test_query_status_requires_no_audit_permission_and_query_advance_is_denied_after_scope(db, reset_test_database):
    job_id = reset_test_database["exchange"]["job_id"]
    actor = db.get(User, "no-audit")
    assert read_action(db, actor, "CHECK_TTC_STATUS", job_id, "privacy_compute_job")["status_value"] == "SUCCEEDED"
    assert validate_target(db, actor, "ADVANCE_TTC_STATE", "privacy_compute_job", job_id)[0] == "COMPUTE_TRANSITION_DENIED"
    assert validate_target(db, actor, "ADVANCE_TTC_STATE", "privacy_compute_job", reset_test_database["foreign"]["job_id"])[0] == "COMPUTE_SCOPE_DENIED"
    assert validate_target(db, db.get(User, "exchange_electric"), "ADVANCE_TTC_STATE", "settlement_task", "settlement-owned") is None
    evidence = read_action(db, db.get(User, "exchange_electric"), "VERIFY_EVIDENCE_SUMMARY", "settlement-evidence", "blockchain_evidence")
    assert evidence["items"][0]["evidence_id"] == "settlement-evidence" and evidence["items"][0]["verify"]["matched"] is True
    audit = read_action(db, db.get(User, "exchange_electric"), "EXPLAIN_AUDIT", "settlement-report", "audit_report")
    assert audit["report_id"] == "settlement-report" and audit["report_count"] == audit["evidence_count"] == 1


@pytest.mark.parametrize("account,key", [("exchange_coal", "exchange"), ("regulator", "regulator")])
@pytest.mark.parametrize("question,action", [("核验这个任务的证据", "VERIFY_EVIDENCE_SUMMARY"), ("解释这个任务的审计情况", "EXPLAIN_AUDIT")])
def test_real_http_typed_query_context_plans_and_executes_a_scoped_read(http, reset_test_database, account, key, question, action):
    fixture = reset_test_database[key]
    planned = _ask(http, account, _start(http, account, fixture["job_id"]), question)
    assert planned["plan"]["status"] == "READY" and planned["plan"]["intent_code"] == action
    step = _execute(http, account, planned)["plan"]["steps"][0]
    assert step["status"] == "SUCCEEDED" and step["output"]["verification_status"] == "MATCHED"
    assert step["output"]["job_id"] == fixture["job_id"] and step["request_id"] is None


@pytest.mark.parametrize("when", ["candidate", "execution"])
def test_real_http_old_candidates_and_ready_plans_recheck_revoked_audit_permission(http, reset_test_database, when):
    account = "exchange_coal"
    session = _start(http, account)
    planned = _ask(http, account, session, "核验证据")
    assert planned["plan"]["status"] == "NEEDS_INPUT"
    choices = planned["plan"]["plan"]["candidates"]
    assert len(choices) == 2 and all(item["entity_type"] == "privacy_compute_job" for item in choices)
    if when == "execution":
        planned = _ask(http, account, planned["session"], "第二个")
        assert planned["plan"]["status"] == "READY"
        assert planned["plan"]["steps"][0]["target_id"] == choices[1]["entity_id"]
    with SessionLocal() as db:
        db.get(User, account).permissions_json = ["VIEW_DATA"]
        db.commit()
    result = _ask(http, account, planned["session"], choices[1]["label"]) if when == "candidate" else _execute(http, account, planned)
    step = result["plan"]["steps"][0]
    assert result["plan"]["status"] == "BLOCKED" and step["error_code"] == "AUDIT_SCOPE_DENIED"
    assert step["request_id"] is None and step["invocation_id"] is None


def test_real_http_query_advance_never_creates_review_and_foreign_query_rejects_scope_first(http, reset_test_database):
    for fixture_key, error in (("exchange", "COMPUTE_TRANSITION_DENIED"), ("foreign", "COMPUTE_SCOPE_DENIED")):
        fixture = reset_test_database[fixture_key]
        planned = _ask(http, "exchange_coal", _start(http, "exchange_coal", fixture["job_id"]), "推进这个任务")
        assert planned["plan"]["status"] == "BLOCKED"
        step = _execute(http, "exchange_coal", planned)["plan"]["steps"][0]
        assert step["error_code"] == error and step["request_id"] is None and step["invocation_id"] is None
    with SessionLocal() as db:
        assert db.scalar(select(func.count(AssistantPlanStep.step_id)).where(AssistantPlanStep.request_id.is_not(None))) == 0
        assert db.scalar(select(func.count(AuditLog.log_id)).where(AuditLog.action_code == "ASSISTANT_WRITE_REVIEW_REQUESTED")) == 0
