from datetime import date, timedelta

from fastapi.testclient import TestClient
import pytest

from app.database import SessionLocal, engine
from app.main import app
from app.models import AssistantPlanStep, AuditReport, Base, DataUsageRequest, DidIdentity, Organization, PrivacyComputeJob, SettlementRule, SettlementTask, User, utc_now
from app.security import create_access_token
from app.services.assistant import ACTION_TOOL_CODES
from app.trust_models import AgentTool, DataAsset, DataAssetVersion, DataSource


PREFIX = "/api/trust-space/assistant"


@pytest.fixture(autouse=True)
def reset_test_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for account, role in (("owner", "GENERATOR"), ("exchange", "EXCHANGE"), ("foreign", "EXCHANGE")):
            db.add(Organization(org_id=account, org_name=account, org_type=role, energy_domain="electricity"))
            db.flush()
            permissions = ["VIEW_DATA", "VIEW_COMPUTE_RESULT", "APPROVE_AUTHORIZATION"]
            if role == "EXCHANGE":
                permissions.append("VIEW_AUDIT")
            db.add(User(user_id=account, org_id=account, username=account, password_hash="unused", display_name=account, role_code=role, permissions_json=permissions))
            db.add(DidIdentity(did_id="did:test:" + account, owner_type="ORG", owner_id=account, org_id=account, public_key_fingerprint="a" * 64))
        db.add(DataSource(source_id="source", source_code="source", source_name="metadata", source_type="ENTERPRISE_CONNECTOR", owner_org_id="owner", security_domain="electricity"))
        db.flush()
        db.add(DataAsset(asset_id="asset-owner", source_id="source", owner_org_id="owner", asset_code="asset-owner", asset_name="本方资产", asset_type="ENERGY_METRIC", classification="ENTERPRISE_DATA_PRODUCT", sensitivity_level="L2", current_version_id="version", status="ACTIVE"))
        db.flush()
        db.add(DataAssetVersion(version_id="version", asset_id="asset-owner", version_no=1, schema_version="metadata", data_ref="connector://owner/value/1", data_hash="a" * 64, immutable_hash="b" * 64))
        db.add(SettlementRule(rule_id="rule", rule_name="metadata", rule_version="metadata", formula_dsl="metadata", rule_hash="c" * 64))
        db.flush()
        for suffix, creator in (("own", "exchange"), ("foreign", "foreign")):
            db.add(SettlementTask(task_id="task-" + suffix, capsule_id="capsule-" + suffix, task_name=suffix, trade_batch_no=suffix, period_start=date(2026, 6, 1), period_end=date(2026, 6, 3), rule_id="rule", creator_org_id=creator))
            db.flush()
            db.add(PrivacyComputeJob(job_id="job-" + suffix, task_id="task-" + suffix, algorithm_code="CONTROLLED_SETTLEMENT_V1", status="SUCCESS"))
            db.add(AuditReport(report_id="report-" + suffix, task_id="task-" + suffix, template_code="metadata", report_title="metadata", report_content="metadata", report_hash="d" * 64, risk_level="LOW"))
        db.add(DataUsageRequest(request_id="request-own", asset_id="asset-owner", asset_version_id="version", applicant_user_id="exchange", applicant_org_id="exchange", provider_org_id="owner", applicant_did="did:test:exchange", provider_did="did:test:owner", purpose="CONTROLLED_QUERY", usage_mode="MPC_AGGREGATE", status="SUBMITTED", duration_days=1, expires_at=utc_now() + timedelta(days=1), trace_id="metadata"))
        for code in set(ACTION_TOOL_CODES.values()):
            db.add(AgentTool(tool_code=code, tool_name=code, service_code="metadata", enabled=True))
        db.commit()
    yield
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


@pytest.fixture
def client():
    instance = TestClient(app)
    yield instance
    instance.close()


def headers(account="exchange"):
    return {"Authorization": "Bearer " + create_access_token(account, "GENERATOR" if account == "owner" else "EXCHANGE", account)}


def plan(client, entity_type, entity_id, text, account="exchange"):
    session = client.post(PREFIX + "/sessions", headers=headers(account), json={"entity_type": entity_type, "entity_id": entity_id}).json()
    response = client.post(f"{PREFIX}/sessions/{session['session_id']}/messages", headers={**headers(account), "If-Match": '"1"'}, json={"content": text})
    assert response.status_code == 201, response.text
    return session, response.json()["plan"]


def execute(client, session, value, account="exchange"):
    response = client.post(f"{PREFIX}/sessions/{session['session_id']}/plans/{value['plan_id']}/execute", headers={**headers(account), "If-Match": f'"{value["state_version"]}"'}, json={})
    assert response.status_code == 200, response.text
    return response.json()["plan"]


@pytest.mark.parametrize(("entity_type", "entity_id", "text"), [
    ("privacy_compute_job", "job-own", "检查资产完整性"),
    ("data_usage_request", "request-own", "检查资产完整性"),
    ("audit_report", "report-own", "查询授权申请状态"),
    ("settlement_task", "task-own", "查询授权申请状态"),
    ("data_asset", "asset-owner", "检查可信任务状态"),
    ("privacy_compute_job", "job-own", "提交申请"),
    ("audit_report", "report-own", "推进任务"),
])
def test_incompatible_context_requests_a_scoped_selection_before_execution(client, entity_type, entity_id, text):
    session, value = plan(client, entity_type, entity_id, text)
    assert value["status"] == "NEEDS_INPUT"
    assert "execute" not in value["allowed_actions"]
    assert value["steps"][0]["target_id"] is None
    assert value["plan"]["candidates"]
    assert value["plan"]["raw_data_accessed"] is False
    result = execute(client, session, value)
    assert result["status"] == "NEEDS_INPUT"
    assert result["steps"][0]["invocation_id"] is None
    assert not result["steps"][0]["output"].get("review_requested")


def test_explicit_asset_target_overrides_a_different_page_without_changing_type(client):
    session, value = plan(client, "privacy_compute_job", "job-own", "检查资产完整性 asset-owner", "owner")
    assert value["status"] == "READY"
    assert value["steps"][0]["target_type"] == "data_asset"
    assert value["steps"][0]["target_id"] == "asset-owner"
    assert execute(client, session, value, "owner")["status"] == "SUCCEEDED"


def test_english_command_words_are_not_misread_as_business_identifiers(client):
    _session, value = plan(client, None, None, "asset integrity")
    assert value["status"] == "NEEDS_INPUT"
    assert value["steps"][0]["target_id"] is None
    assert {item["entity_id"] for item in value["plan"]["candidates"]} == {"asset-owner"}


@pytest.mark.parametrize(("entity_type", "entity_id", "text"), [("privacy_compute_job", "job-own", "检查可信任务状态"), ("audit_report", "report-own", "解释审计报告"), ("data_usage_request", "request-own", "查询授权申请状态")])
def test_matching_job_report_and_request_contexts_read_their_actual_types(client, entity_type, entity_id, text):
    session, value = plan(client, entity_type, entity_id, text)
    assert value["status"] == "READY"
    result = execute(client, session, value)
    assert result["status"] == "SUCCEEDED"
    assert result["steps"][0]["output"]["raw_data_accessed"] is False


@pytest.mark.parametrize(("entity_type", "entity_id", "text"), [("privacy_compute_job", "job-foreign", "检查可信任务状态"), ("audit_report", "report-foreign", "解释审计报告")])
def test_typed_relations_do_not_allow_cross_organization_job_or_report_reads(client, entity_type, entity_id, text):
    session, value = plan(client, entity_type, entity_id, text)
    assert value["status"] == "BLOCKED"
    assert value["steps"][0]["error_code"] == ("COMPUTE_SCOPE_DENIED" if entity_type == "privacy_compute_job" else "AUDIT_SCOPE_DENIED")
    result = execute(client, session, value)
    assert result["status"] == "BLOCKED" and result["steps"][0]["invocation_id"] is None
    assert result["plan"]["raw_data_accessed"] is False


def test_execution_rejects_a_preexisting_wrong_type_even_when_its_id_names_a_real_asset(client):
    session, value = plan(client, "data_asset", "asset-owner", "检查资产完整性", "owner")
    with SessionLocal() as db:
        step = db.query(AssistantPlanStep).filter_by(plan_id=value["plan_id"]).one()
        step.target_type = "privacy_compute_job"
        db.commit()
    result = execute(client, session, value, "owner")
    assert result["status"] == "BLOCKED"
    assert result["steps"][0]["error_code"] == "ASSISTANT_TARGET_TYPE_MISMATCH"


def test_old_wrong_type_write_plan_does_not_create_a_review_request(client):
    session, value = plan(client, "data_usage_request", "request-own", "批准申请", "owner")
    assert value["status"] == "PENDING_REVIEW"
    with SessionLocal() as db:
        step = db.query(AssistantPlanStep).filter_by(plan_id=value["plan_id"]).one()
        step.target_type = "privacy_compute_job"
        db.commit()
    result = execute(client, session, value, "owner")
    assert result["status"] == "BLOCKED"
    assert not result["steps"][0]["output"].get("review_requested")
    with SessionLocal() as db:
        assert db.get(DataUsageRequest, "request-own").status == "SUBMITTED"


def test_retry_does_not_offer_execution_for_an_incompatible_page(client):
    session, value = plan(client, "privacy_compute_job", "job-own", "检查资产完整性")
    assert value["status"] == "NEEDS_INPUT"
    response = client.post(f"{PREFIX}/sessions/{session['session_id']}/plans/{value['plan_id']}/retry", headers={**headers(), "If-Match": f'"{value["state_version"]}"'})
    assert response.status_code == 200
    assert response.json()["plan"]["idempotent_replay"] is True
    assert response.json()["plan"]["status"] == "NEEDS_INPUT"
    current = client.get(f"{PREFIX}/sessions/{session['session_id']}/plans/{value['plan_id']}", headers=headers()).json()["plan"]
    assert current["status"] == "NEEDS_INPUT" and current["plan"]["candidates"]
    assert "execute" not in current["allowed_actions"]


def test_retry_cannot_revive_a_role_denied_evidence_command(client):
    session, value = plan(client, "settlement_task", "task-own", "核验证据摘要", "owner")
    assert value["status"] == "BLOCKED"
    response = client.post(f"{PREFIX}/sessions/{session['session_id']}/plans/{value['plan_id']}/retry", headers={**headers("owner"), "If-Match": f'"{value["state_version"]}"'})
    assert response.status_code == 200
    assert response.json()["plan"]["status"] == "BLOCKED"
