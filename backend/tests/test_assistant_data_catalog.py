"""Ordinary data questions use scoped catalog metadata, never node payloads."""
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.database import SessionLocal, engine
from app.main import app
from app.models import AssistantPlanStep, Base, Organization, User
from app.security import create_access_token
from app.services.assistant import ACTION_TOOL_CODES
from app.trust_models import AgentTool, DataAsset, DataAssetVersion, DataSource


PREFIX = "/api/trust-space/assistant"
ACCOUNTS = {
    "generator": ("GENERATOR", "electricity"), "retailer": ("RETAILER", "electricity"),
    "exchange": ("EXCHANGE", "electricity"), "regulator": ("REGULATOR", "electricity"),
    "admin": ("ADMIN", "electricity"),
    **{name: (role, name) for name, role in (("coal", "COAL_ENTERPRISE"), ("heat", "HEAT_ENTERPRISE"), ("gas", "GAS_ENTERPRISE"), ("oil", "OIL_ENTERPRISE"))},
    **{"exchange_" + domain: ("EXCHANGE", domain) for domain in ("coal", "heat", "gas", "oil")},
}


@pytest.fixture(autouse=True)
def reset_test_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for account, (role, domain) in ACCOUNTS.items():
            db.add(Organization(org_id=account, org_name=account, org_type=role, energy_domain=domain))
            db.flush()
            db.add(User(user_id=account, org_id=account, username=account, password_hash="unused", display_name=account, role_code=role, permissions_json=["VIEW_DATA"]))
            db.add(DataSource(source_id="source-" + account, source_code="source-" + account, source_name=account, source_type="ENTERPRISE_CONNECTOR", owner_org_id=account, security_domain=domain))
            db.flush()
            db.add(DataAsset(asset_id="asset-" + account, asset_code="asset-" + account, asset_name=account + "本方数据", asset_type="ENERGY_METRIC", classification="ENTERPRISE_DATA_PRODUCT", sensitivity_level="L2", owner_org_id=account, source_id="source-" + account, status="ACTIVE", metadata_json={"domain": domain, "private_payload": "never-disclose-this-value"}))
            db.flush()
            db.add(DataAssetVersion(version_id="version-" + account, asset_id="asset-" + account, version_no=2, schema_version="metadata-only", record_count=8396, schema_json={"period_start": "2021-01-01", "period_end": "2026-09-30"}, data_ref="connector://private-payload/" + account, data_hash="a" * 64, immutable_hash="b" * 64))
        for code in set(ACTION_TOOL_CODES.values()):
            db.add(AgentTool(tool_code=code, tool_name=code, service_code="metadata-only", enabled=True))
        db.commit()
    yield
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


@pytest.fixture
def client():
    instance = TestClient(app, raise_server_exceptions=True)
    yield instance
    instance.close()


def headers(account="exchange"):
    return {"Authorization": "Bearer " + create_access_token(account, ACCOUNTS[account][0], account)}


def ask(client, account="exchange", content="我想查询一下我现在有哪些数据", **context):
    session = client.post(PREFIX + "/sessions", headers=headers(account), json={"page_path": "/trusted-space/workbench", **context}).json()
    response = client.post(f"{PREFIX}/sessions/{session['session_id']}/messages", headers={**headers(account), "If-Match": '"1"'}, json={"content": content})
    assert response.status_code == 201, response.text
    return session, response.json()["plan"]


def execute(client, session, plan, account="exchange"):
    response = client.post(f"{PREFIX}/sessions/{session['session_id']}/plans/{plan['plan_id']}/execute", headers={**headers(account), "If-Match": f'"{plan["state_version"]}"'}, json={})
    assert response.status_code == 200, response.text
    return response.json()["plan"]


@pytest.mark.parametrize("account", ACCOUNTS)
def test_exact_user_question_lists_only_the_accounts_own_catalog_metadata(client, account):
    if account == "admin":
        session, plan = ask(client, account)
        assert plan["status"] == "BLOCKED" and plan["steps"][0]["error_code"] == "ASSISTANT_ROLE_DENIED"
        assert "execute" not in plan["allowed_actions"]
        assert execute(client, session, plan, account)["steps"][0]["invocation_id"] is None
        tools = client.get(PREFIX + "/tools", headers=headers(account))
        assert tools.status_code == 200
        assert {action for item in tools.json()["items"] for action in item["assistant_actions"]} <= {"SYSTEM_OVERVIEW", "ASSISTANT_HELP"}
        return
    session, plan = ask(client, account)
    assert plan["intent_code"] == "LIST_DATA_ASSETS"
    assert plan["status"] == "READY"
    result = execute(client, session, plan, account)
    assert result["status"] == "SUCCEEDED"
    output = result["steps"][0]["output"]
    expected = {"asset-" + account}
    assert {item["asset_id"] for item in output["items"]} == expected
    assert output["total"] == len(expected)
    assert output["organization_id"] == account
    assert output["raw_data_accessed"] is False
    assert "never-disclose" not in str(output) and "connector://" not in str(output)
    if expected:
        assert output["items"][0]["period_start"] == "2021-01-01"
        assert output["items"][0]["period_end"] == "2026-09-30"
        assert output["items"][0]["record_count"] == 8396
    replay = execute(client, session, result, account)
    assert replay["idempotent_replay"] is True
    assert replay["steps"][0]["output"] == output


@pytest.mark.parametrize("content", ["我有哪些数据？", "查一下我的数据", "我的数据列表", "本方数据目录", "我有什么数据", "查看我拥有的数据"])
def test_ordinary_personal_data_phrasings_are_recognized(client, content):
    _, plan = ask(client, content=content)
    assert plan["intent_code"] == "LIST_DATA_ASSETS"
    assert plan["status"] == "READY"


def test_catalog_question_ignores_unrelated_page_or_supplied_foreign_target(client):
    session, plan = ask(client, content="我有哪些数据，资产编号 asset-coal", entity_type="privacy_compute_job", entity_id="job-foreign")
    result = execute(client, session, plan)
    assert {item["asset_id"] for item in result["steps"][0]["output"]["items"]} == {"asset-exchange"}


def test_catalog_is_bounded_and_reports_more_instead_of_silently_truncating(client):
    with SessionLocal() as db:
        for index in range(24):
            db.add(DataAsset(asset_id=f"asset-more-{index}", asset_code=f"asset-more-{index}", asset_name=f"本方数据{index}", asset_type="ENERGY_METRIC", classification="ENTERPRISE_DATA_PRODUCT", sensitivity_level="L2", owner_org_id="exchange", source_id="source-exchange", status="ACTIVE"))
        db.commit()
    session, plan = ask(client)
    output = execute(client, session, plan)["steps"][0]["output"]
    assert output["total"] == 25 and len(output["items"]) == 20
    assert output["has_more"] is True


def test_unknown_intent_cannot_be_revived_by_retrying_the_same_unsupported_plan(client):
    session, plan = ask(client, content="请帮我安排一场会议")
    assert plan["status"] == "NEEDS_INPUT"
    assert "retry" not in plan["allowed_actions"]
    assert "数据" in plan["plan"]["explanation"] and "execute" not in plan["allowed_actions"]
    response = client.post(f"{PREFIX}/sessions/{session['session_id']}/plans/{plan['plan_id']}/retry", headers={**headers(), "If-Match": '"1"'})
    assert response.status_code == 200
    assert response.json()["plan"]["idempotent_replay"] is True
    assert response.json()["plan"]["status"] == "NEEDS_INPUT"
    current = client.get(f"{PREFIX}/sessions/{session['session_id']}/plans/{plan['plan_id']}", headers=headers()).json()["plan"]
    assert current["status"] == "NEEDS_INPUT" and "execute" not in current["allowed_actions"]


def test_disabled_data_tool_remains_unavailable(client):
    with SessionLocal() as db:
        tool = db.scalar(select(AgentTool).where(AgentTool.tool_code == "EDCAdapter+OPAAdapter"))
        tool.enabled = False
        db.commit()
    _, plan = ask(client)
    assert plan["status"] == "BLOCKED"
    assert "execute" not in plan["allowed_actions"]


def test_own_catalog_scope_is_rechecked_at_execution(client):
    session, plan = ask(client)
    with SessionLocal() as db:
        step = db.scalar(select(AssistantPlanStep).where(AssistantPlanStep.plan_id == plan["plan_id"]))
        step.target_id = "coal"
        db.commit()
    result = execute(client, session, plan)
    assert result["status"] == "BLOCKED"
    assert result["steps"][0]["error_code"] == "ASSISTANT_CATALOG_SCOPE_DENIED"


@pytest.mark.parametrize("content", ["删除我的数据", "导出我的数据", "上传我的数据"])
def test_catalog_question_does_not_claim_to_execute_unsupported_business_writes(client, content):
    _, plan = ask(client, content=content)
    assert plan["intent_code"] == "UNKNOWN_INTENT" and plan["status"] == "BLOCKED"


def test_catalog_alias_does_not_override_a_specific_authorization_question(client):
    _, plan = ask(client, content="查询我的数据授权申请状态")
    assert plan["intent_code"] == "QUERY_AUTHORIZATION_STATUS"
