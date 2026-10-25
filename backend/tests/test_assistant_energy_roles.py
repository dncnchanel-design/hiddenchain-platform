from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from app.database import SessionLocal, engine
from app.main import app
from app.models import Base, DataContract, DataUsageRequest, Organization, PrivacyComputeJob, SettlementRule, SettlementTask, TaskParticipant, User, utc_now
from app.security import create_access_token
from app.services.assistant import ACTION_TOOL_CODES
from app.trust_models import AgentTool, DataAsset, DataAssetVersion, DataSource


PREFIX = "/api/trust-space/assistant"
ENERGY_ROLES = {"coal": "COAL_ENTERPRISE", "heat": "HEAT_ENTERPRISE", "gas": "GAS_ENTERPRISE", "oil": "OIL_ENTERPRISE"}


@pytest.fixture(autouse=True)
def reset_test_database():
    """Build only metadata, without running the shared raw-data fixture seed."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for account, role in {**ENERGY_ROLES, "outsider": "GENERATOR"}.items():
            domain = account if account != "outsider" else "electricity"
            db.add(Organization(org_id=account, org_name=account, org_type=role, energy_domain=domain))
            db.flush()
            db.add(User(user_id=account, org_id=account, username=account, password_hash="unused", display_name=account, role_code=role, permissions_json=["VIEW_DATA", "VIEW_COMPUTE_RESULT", "APPROVE_AUTHORIZATION"]))
            db.add(DataSource(source_id=f"source-{account}", source_code=f"source-{account}", source_name=f"{account}连接器", owner_org_id=account, source_type="ENTERPRISE_CONNECTOR", security_domain=domain))
            db.flush()
            db.add(DataAsset(asset_id=f"asset-{account}", source_id=f"source-{account}", owner_org_id=account, asset_code=f"metric-{account}", asset_name=f"{account}本方数据资源", asset_type="ENERGY_METRIC", classification="ENTERPRISE_DATA_PRODUCT", sensitivity_level="L2", current_version_id=f"version-{account}", status="ACTIVE"))
            db.flush()
            db.add(DataAssetVersion(version_id=f"version-{account}", asset_id=f"asset-{account}", version_no=1, schema_version="metadata-only", data_ref=f"connector://{account}/metric/versions/1", data_hash="a" * 64, immutable_hash="b" * 64))
        db.flush()
        for account in (*ENERGY_ROLES, "outsider"):
            db.add(DataUsageRequest(request_id=f"request-{account}", asset_id=f"asset-{account}", asset_version_id=f"version-{account}", applicant_user_id="outsider", applicant_org_id="outsider", provider_org_id=account, applicant_did="did:test:outsider", provider_did=f"did:test:{account}", purpose="CONTROLLED_AGGREGATE_QUERY", usage_mode="AGGREGATE_ONLY", duration_days=30, expires_at=utc_now() + timedelta(days=30), status="SUBMITTED", trace_id="assistant-role-regression"))
        db.add(SettlementRule(rule_id="rule", rule_name="元数据边界测试", rule_version="metadata-only-v1", formula_dsl="FIXED_METADATA_ONLY", rule_hash="c" * 64))
        db.flush()
        for task_id in ("task-participating", "task-foreign"):
            db.add(SettlementTask(task_id=task_id, capsule_id=f"capsule-{task_id}", task_name=task_id, trade_batch_no=task_id, period_start=date(2026, 6, 1), period_end=date(2026, 6, 30), rule_id="rule", creator_org_id="outsider"))
        db.flush()
        for account, role in ENERGY_ROLES.items():
            db.add(TaskParticipant(task_id="task-participating", org_id=account, role_in_task=role))
        for account in (*ENERGY_ROLES, "outsider"):
            db.add(PrivacyComputeJob(job_id="job-" + account, task_id="query-" + account, algorithm_code="CONTROLLED_AGGREGATE", execution_attestation_json={"request_item_id": "item-" + account, "applicant_org_id": account, "provider_org_id": account}))
        for tool_code in set(ACTION_TOOL_CODES.values()):
            db.add(AgentTool(tool_code=tool_code, tool_name=tool_code, service_code="metadata-only", enabled=True))
        db.commit()
    yield
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture
def client():
    # Schema/metadata are ready above. Avoid the lifespan's raw-data fixture seed.
    instance = TestClient(app)
    yield instance
    instance.close()


def _headers(account):
    role = ENERGY_ROLES.get(account, "GENERATOR")
    return {"Authorization": f"Bearer {create_access_token(account, role, account)}"}


def _plan(client, account, entity_type, entity_id, content):
    headers = _headers(account)
    created = client.post(f"{PREFIX}/sessions", headers=headers, json={"entity_type": entity_type, "entity_id": entity_id})
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]
    planned = client.post(f"{PREFIX}/sessions/{session_id}/messages", headers={**headers, "If-Match": '"1"'}, json={"content": content})
    assert planned.status_code == 201, planned.text
    return session_id, planned.json()["plan"]


def _execute(client, account, session_id, plan):
    response = client.post(f"{PREFIX}/sessions/{session_id}/plans/{plan['plan_id']}/execute", headers={**_headers(account), "If-Match": f'"{plan["state_version"]}"'}, json={})
    assert response.status_code == 200, response.text
    return response.json()["plan"]


@pytest.mark.parametrize("account", ENERGY_ROLES)
@pytest.mark.parametrize("own_asset", [True, False])
def test_energy_enterprise_asset_reads_obey_the_same_owner_boundary(client, account, own_asset):
    asset_id = f"asset-{account}" if own_asset else "asset-outsider"
    session_id, plan = _plan(client, account, "data_asset", asset_id, "检查资产完整性")
    assert plan["status"] == ("READY" if own_asset else "BLOCKED")
    result = _execute(client, account, session_id, plan)
    output = result["steps"][0]["output"]
    if own_asset:
        assert result["status"] == "SUCCEEDED"
        assert output["raw_data_accessed"] is False
        assert output["asset_id"] == asset_id
        assert output["integrity"]["version_present"] is True
        assert "data_ref" not in str(output) and "password_hash" not in str(output)
    else:
        assert result["status"] == "BLOCKED"
        assert result["steps"][0]["error_code"] == "ASSET_SCOPE_DENIED"
        assert result["steps"][0]["invocation_id"] is None
        assert result["plan"]["raw_data_accessed"] is False
        assert output == {}


@pytest.mark.parametrize("account", ENERGY_ROLES)
def test_new_energy_roles_keep_authorization_and_task_tenant_boundaries(client, account):
    targets = [("data_usage_request", f"request-{account}", "查询授权申请状态", "SUCCEEDED", None), ("data_usage_request", "request-outsider", "查询授权申请状态", "BLOCKED", "REQUEST_SCOPE_DENIED"), ("settlement_task", "task-participating", "检查可信任务状态", "SUCCEEDED", None), ("settlement_task", "task-foreign", "检查可信任务状态", "BLOCKED", "TTC_SCOPE_DENIED"), ("privacy_compute_job", "job-" + account, "检查可信任务状态", "SUCCEEDED", None), ("privacy_compute_job", "job-outsider", "检查可信任务状态", "BLOCKED", "COMPUTE_SCOPE_DENIED")]
    for entity_type, entity_id, content, status, error_code in targets:
        session_id, plan = _plan(client, account, entity_type, entity_id, content)
        assert plan["status"] == ("BLOCKED" if error_code else "READY")
        result = _execute(client, account, session_id, plan)
        assert result["status"] == status
        assert result["plan"]["raw_data_accessed"] is False
        if error_code:
            assert result["steps"][0]["error_code"] == error_code
            assert result["steps"][0]["invocation_id"] is None
        else:
            assert result["steps"][0]["output"]["raw_data_accessed"] is False
            assert not any(key in str(result["steps"][0]["output"]) for key in ("data_ref", "payload_json", "password_hash"))


@pytest.mark.parametrize("account", ENERGY_ROLES)
def test_new_energy_providers_can_only_record_manual_approval_review(client, account):
    session_id, plan = _plan(client, account, "data_usage_request", f"request-{account}", "批准授权")
    assert plan["status"] == "PENDING_REVIEW" and plan["steps"][0]["mode"] == "WRITE"
    result = _execute(client, account, session_id, plan)
    assert result["status"] == "PENDING_REVIEW"
    assert result["steps"][0]["output"]["review_requested"] is True
    assert result["steps"][0]["output"]["business_mutation"] is False
    with SessionLocal() as db:
        assert db.get(DataUsageRequest, f"request-{account}").status == "SUBMITTED"
        assert db.scalar(select(func.count(DataContract.contract_id))) == 0


@pytest.mark.parametrize("account", ENERGY_ROLES)
def test_provider_role_without_individual_approval_permission_cannot_record_review(client, account):
    with SessionLocal() as db:
        current = db.get(User, account)
        current.permissions_json = ["VIEW_DATA", "VIEW_COMPUTE_RESULT"]
        db.commit()
    session_id, plan = _plan(client, account, "data_usage_request", f"request-{account}", "批准授权")
    assert plan["status"] == "BLOCKED"
    assert plan["steps"][0]["error_code"] == "PROVIDER_REVIEW_REQUIRED"
    result = _execute(client, account, session_id, plan)
    assert not result["steps"][0]["output"].get("review_requested")
    with SessionLocal() as db:
        assert db.get(DataUsageRequest, f"request-{account}").status == "SUBMITTED"
        assert db.scalar(select(func.count(DataContract.contract_id))) == 0


@pytest.mark.parametrize("account", ENERGY_ROLES)
def test_provider_cannot_review_an_already_approved_request_again(client, account):
    with SessionLocal() as db:
        db.get(DataUsageRequest, f"request-{account}").status = "APPROVED"
        db.commit()
    session_id, plan = _plan(client, account, "data_usage_request", f"request-{account}", "批准授权")
    assert plan["status"] == "BLOCKED"
    assert plan["steps"][0]["error_code"] == "INVALID_REQUEST_TRANSITION"
    assert not _execute(client, account, session_id, plan)["steps"][0]["output"].get("review_requested")
    with SessionLocal() as db:
        assert db.get(DataUsageRequest, f"request-{account}").status == "APPROVED"


def test_existing_provider_write_plan_remains_a_review_request_without_business_mutation(client):
    session_id, plan = _plan(client, "outsider", "data_usage_request", "request-outsider", "批准授权")
    assert plan["status"] == "PENDING_REVIEW"
    result = _execute(client, "outsider", session_id, plan)
    assert result["status"] == "PENDING_REVIEW"
    assert result["steps"][0]["output"]["business_mutation"] is False
    with SessionLocal() as db:
        assert db.get(DataUsageRequest, "request-outsider").status == "SUBMITTED"
        assert db.scalar(select(func.count(DataContract.contract_id))) == 0
