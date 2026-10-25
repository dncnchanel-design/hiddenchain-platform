"""Real assistant HTTP flows using the shared seeded application fixture."""
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import (
    AuditLog, DataContract, DataSpaceAgreement, DataUsageRequest, PrivacyComputeJob,
    SettlementTask, User, UserNotification, utc_now,
)
from app.security import create_access_token
from app.services import trust_space
from app.trust_models import DataAsset, DataAssetVersion


PREFIX = "/api/trust-space/assistant"
BUSINESS_ACCOUNTS = ("generator", "retailer", "coal", "heat", "gas", "oil", "exchange", "exchange_coal", "exchange_heat", "exchange_gas", "exchange_oil", "regulator")


@pytest.fixture
def accounts(auth_headers):
    """Keep the existing real-login fixture and add tokens for its other users."""
    headers = dict(auth_headers)
    with SessionLocal() as db:
        for name in (*BUSINESS_ACCOUNTS, "admin"):
            actor = db.scalar(select(User).where(User.username == name))
            assert actor is not None, name
            headers.setdefault(name, {"Authorization": "Bearer " + create_access_token(actor.user_id, actor.role_code, actor.org_id)})
    return headers


def start(client, headers, **context):
    response = client.post(PREFIX + "/sessions", headers=headers, json={"page_path": "/trusted-space/workbench", **context})
    assert response.status_code == 201, response.text
    return response.json()


def ask(client, headers, session, content):
    response = client.post(f"{PREFIX}/sessions/{session['session_id']}/messages", headers={**headers, "If-Match": f'"{session["state_version"]}"', "Idempotency-Key": "flow-message-" + uuid4().hex}, json={"content": content})
    assert response.status_code == 201, response.text
    return response.json()


def execute(client, headers, body):
    session, plan = body["session"], body["plan"]
    response = client.post(f"{PREFIX}/sessions/{session['session_id']}/plans/{plan['plan_id']}/execute", headers={**headers, "If-Match": f'"{plan["state_version"]}"'}, json={"step_id": plan["steps"][0]["step_id"]})
    assert response.status_code == 200, response.text
    return response.json()


def actor(name):
    with SessionLocal() as db:
        return db.scalar(select(User).where(User.username == name))


def owned_asset(name="generator"):
    owner = actor(name)
    with SessionLocal() as db:
        asset = db.scalar(select(DataAsset).where(DataAsset.owner_org_id == owner.org_id, DataAsset.status == "ACTIVE").order_by(DataAsset.asset_id))
        assert asset is not None
        version = db.scalar(select(DataAssetVersion).where(DataAssetVersion.asset_id == asset.asset_id).order_by(DataAssetVersion.version_no.desc()))
        assert version is not None
        return asset.asset_id, version.version_id


def usage_request(client, accounts, *, applicant="exchange", purpose="集成回归 A"):
    asset_id, version_id = owned_asset()
    payload = {
        "asset_id": asset_id, "asset_version_id": version_id, "purpose": purpose,
        "usage_mode": "AGGREGATE_ONLY", "requested_scope": {"period": "2026-07"},
        "requested_fields": ["energy_mwh"], "duration_days": 30, "terms": {"raw_data_export": False},
    }
    if applicant == "regulator":
        payload.update(purpose="REGULATORY_CROSS_ENERGY_REVIEW", usage_mode="MPC_AGGREGATE",
                       terms={"raw_data_export": False, "regulatory_basis": "ENERGY_REGULATION", "authority_ref": "assistant-regression", "output_mode": "AGGREGATE_ONLY"})
    response = client.post("/api/data/access-requests", headers={**accounts[applicant], "Idempotency-Key": "flow-request-" + uuid4().hex}, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["request_id"]


@pytest.mark.parametrize("account", BUSINESS_ACCOUNTS)
def test_business_list_reads_use_real_scoped_catalogs_for_all_twelve_accounts(client, accounts, account):
    headers, current = accounts[account], actor(account)
    session = start(client, headers)
    for text, expected_action in (
        ("看看本方数据清单", "LIST_DATA_ASSETS"),
        ("我想知道有哪些数据可以申请", "LIST_VISIBLE_DATA_ASSETS"),
        ("列出我的授权申请列表", "LIST_AUTHORIZATIONS"),
        ("查看任务列表", "LIST_TASKS"),
        ("查看通知", "LIST_NOTIFICATIONS"),
    ):
        planned = ask(client, headers, session, text)
        plan = planned["plan"]
        assert plan["intent_code"] == expected_action, (account, plan)
        assert plan["status"] == "READY" and plan["steps"][0]["mode"] == "READ", (account, plan)
        result = execute(client, headers, planned)
        assert result["plan"]["status"] == "SUCCEEDED", (account, result)
        output = result["plan"]["steps"][0]["output"]
        assert output["raw_data_accessed"] is False and len(output["items"]) <= 20
        assert not any(key in str(output) for key in ("password_hash", "data_ref", "payload_json", "endpoint_ref"))
        if expected_action in {"LIST_DATA_ASSETS", "LIST_VISIBLE_DATA_ASSETS"}:
            path = "/api/trust-space/catalog?page_size=100"
            if expected_action == "LIST_DATA_ASSETS":
                path += "&provider_org_id=" + current.org_id
            expected = client.get(path, headers=headers)
            assert expected.status_code == 200, expected.text
            expected_ids = {item["asset_id"] for item in expected.json()["items"]}
            assert output["total"] == expected.json()["total"]
            assert {item["asset_id"] for item in output["items"]} <= expected_ids
            if len(expected_ids) <= 20:
                assert {item["asset_id"] for item in output["items"]} == expected_ids
        with SessionLocal() as db:
            if expected_action == "LIST_AUTHORIZATIONS":
                for row in output["items"]:
                    request = db.get(DataUsageRequest, row["entity_id"])
                    assert current.org_id in {request.applicant_org_id, request.provider_org_id}
            if expected_action == "LIST_TASKS":
                allowed = set(db.scalars(trust_space._task_scope_query(db, current).with_only_columns(SettlementTask.task_id)).all())
                for row in output["items"]:
                    if row["entity_type"] == "settlement_task":
                        assert row["entity_id"] in allowed
                    else:
                        job = db.get(PrivacyComputeJob, row["entity_id"])
                        if db.get(SettlementTask, job.task_id):
                            assert job.task_id in allowed
                        else:
                            evidence = job.execution_attestation_json or {}
                            assert evidence.get("request_item_id")
                            assert current.org_id in {evidence.get("applicant_org_id"), evidence.get("provider_org_id")}
            if expected_action == "LIST_NOTIFICATIONS":
                for row in output["items"]:
                    notice = db.get(UserNotification, row["entity_id"])
                    assert notice.user_id == current.user_id and notice.org_id == current.org_id
        session = result["session"]


def test_admin_assistant_only_exposes_ops_and_help_and_never_business_sessions(client, accounts):
    headers = accounts["admin"]
    session = start(client, headers, page_path="/system")
    system = ask(client, headers, session, "系统运行情况")
    assert system["plan"]["status"] == "READY"
    result = execute(client, headers, system)
    output = result["plan"]["steps"][0]["output"]
    assert output["scope"] == "OPERATIONS_ONLY" and output["raw_data_accessed"] is False
    assert not any(key in str(output) for key in ("asset_id", "request_id", "task_id", "data_ref", "password_hash", "public_key", "endpoint_ref"))
    help_plan = ask(client, headers, result["session"], "你能做什么")
    help_result = execute(client, headers, help_plan)
    assert {item["action_code"] for item in help_result["plan"]["steps"][0]["output"]["help_actions"]} == {"SYSTEM_OVERVIEW"}
    tools = client.get(PREFIX + "/tools", headers=headers)
    assert tools.status_code == 200
    assert {action for tool in tools.json()["items"] for action in tool["assistant_actions"]} <= {"SYSTEM_OVERVIEW", "ASSISTANT_HELP"}
    for content in ("我有哪些数据", "查看授权列表", "查看任务列表", "查看通知", "列出所有审计报告", "帮我测算电费"):
        plan = ask(client, headers, help_result["session"], content)
        assert plan["plan"]["status"] == "BLOCKED" and "execute" not in plan["plan"]["allowed_actions"]
        assert plan["plan"]["steps"][0]["request_id"] is None
        help_result = plan
    business = start(client, accounts["generator"])
    assert client.get(f"{PREFIX}/sessions/{business['session_id']}/messages", headers=headers).status_code == 403


def test_missing_target_candidates_second_choice_and_previous_reference_are_real_scoped_reads(client, accounts):
    expected = {usage_request(client, accounts, purpose="集成回归 A"), usage_request(client, accounts, purpose="集成回归 B")}
    headers = accounts["exchange"]
    session = start(client, headers)
    missing = ask(client, headers, session, "我的申请批下来没有")
    plan = missing["plan"]
    assert plan["status"] == "NEEDS_INPUT" and "execute" not in plan["allowed_actions"]
    choices = plan["plan"]["candidates"]
    assert {item["entity_id"] for item in choices} == expected
    assert all(item["entity_type"] == "data_usage_request" for item in choices)
    selected_id = choices[1]["entity_id"]
    selected = ask(client, headers, missing["session"], "第二个")
    assert selected["plan"]["status"] == "READY"
    assert selected["plan"]["steps"][0]["target_id"] == selected_id
    finished = execute(client, headers, selected)
    assert finished["plan"]["steps"][0]["output"]["request_id"] == selected_id
    reference = ask(client, headers, finished["session"], "刚才那个呢")
    assert reference["plan"]["status"] == "READY"
    assert execute(client, headers, reference)["plan"]["steps"][0]["output"]["request_id"] == selected_id


@pytest.mark.parametrize("prefix", ["不要批准申请", "暂时不要批准申请", "请先不要批准申请", "我不想批准申请"])
def test_negated_writes_never_create_review_requests(client, accounts, prefix):
    request_id = usage_request(client, accounts)
    headers = accounts["generator"]
    body = ask(client, headers, start(client, headers), f"{prefix} {request_id}")
    assert body["plan"]["status"] != "PENDING_REVIEW", body["plan"]
    assert all(step["mode"] != "WRITE" and step["request_id"] is None for step in body["plan"]["steps"])
    with SessionLocal() as db:
        assert db.get(DataUsageRequest, request_id).status == "SUBMITTED"
        assert db.scalar(select(func.count(AuditLog.log_id)).where(AuditLog.action_code == "ASSISTANT_WRITE_REVIEW_REQUESTED")) == 0


def test_negated_approval_followed_by_explicit_status_question_stays_a_read(client, accounts):
    request_id = usage_request(client, accounts)
    headers = accounts["generator"]
    body = ask(client, headers, start(client, headers), f"不要批准申请，只查询授权申请状态 {request_id}")
    assert body["plan"]["intent_code"] == "QUERY_AUTHORIZATION_STATUS" and body["plan"]["status"] == "READY"
    result = execute(client, headers, body)
    assert result["plan"]["steps"][0]["output"]["status_value"] == "SUBMITTED"
    with SessionLocal() as db:
        assert db.get(DataUsageRequest, request_id).status == "SUBMITTED"


def test_explicit_approval_only_records_one_durable_manual_review_envelope(client, accounts):
    request_id = usage_request(client, accounts)
    with SessionLocal() as db:
        before = (db.get(DataUsageRequest, request_id).state_version, db.scalar(select(func.count(DataContract.contract_id))), db.scalar(select(func.count(DataSpaceAgreement.agreement_id))))
    headers = accounts["generator"]
    planned = ask(client, headers, start(client, headers), f"批准授权申请 {request_id}")
    assert planned["plan"]["status"] == "PENDING_REVIEW" and planned["plan"]["steps"][0]["mode"] == "WRITE"
    result = execute(client, headers, planned)
    output = result["plan"]["steps"][0]["output"]
    assert output["review_requested"] is True and output["business_mutation"] is False and output["request_id"]
    replay = execute(client, headers, result)
    assert replay["plan"]["idempotent_replay"] is True
    with SessionLocal() as db:
        request = db.get(DataUsageRequest, request_id)
        assert request.status == "SUBMITTED" and request.contract_id is None and request.agreement_id is None
        assert (request.state_version, db.scalar(select(func.count(DataContract.contract_id))), db.scalar(select(func.count(DataSpaceAgreement.agreement_id)))) == before
        assert db.scalar(select(func.count(AuditLog.log_id)).where(AuditLog.action_code == "ASSISTANT_WRITE_REVIEW_REQUESTED")) == 1


def test_multiple_identifiers_require_choice_and_cannot_execute_the_first_one(client, accounts):
    request_ids = [usage_request(client, accounts, purpose="集成回归 A"), usage_request(client, accounts, purpose="集成回归 B")]
    headers = accounts["exchange"]
    body = ask(client, headers, start(client, headers), "查询授权申请状态 " + " 和 ".join(request_ids))
    plan = body["plan"]
    assert plan["status"] == "NEEDS_INPUT" and plan["steps"][0]["target_id"] is None
    assert "execute" not in plan["allowed_actions"]
    rejected = execute(client, headers, body)
    assert rejected["plan"]["status"] == "NEEDS_INPUT"
    assert rejected["plan"]["steps"][0]["invocation_id"] is None


def test_explicit_foreign_assets_requests_and_review_targets_are_rejected_during_planning(client, accounts):
    foreign_request = usage_request(client, accounts, applicant="retailer")
    asset_id, _ = owned_asset()
    for account, text, code in (
        ("exchange", f"查询授权申请状态 {foreign_request}", "REQUEST_SCOPE_DENIED"),
        ("exchange_coal", f"检查资产完整性 {asset_id}", "ASSET_SCOPE_DENIED"),
        ("exchange", f"批准授权申请 {foreign_request}", "REQUEST_SCOPE_DENIED"),
    ):
        headers = accounts[account]
        body = ask(client, headers, start(client, headers), text)
        assert body["plan"]["status"] == "BLOCKED", body["plan"]
        assert body["plan"]["steps"][0]["error_code"] == code
        assert body["plan"]["steps"][0]["request_id"] is None
        assert execute(client, headers, body)["plan"]["steps"][0]["invocation_id"] is None


def test_execution_rechecks_target_scope_after_a_ready_read_was_planned(client, accounts):
    request_id = usage_request(client, accounts)
    headers = accounts["exchange"]
    planned = ask(client, headers, start(client, headers), f"查询授权申请状态 {request_id}")
    assert planned["plan"]["status"] == "READY"
    with SessionLocal() as db:
        request = db.get(DataUsageRequest, request_id)
        other = db.scalar(select(User).where(User.username == "retailer"))
        request.applicant_org_id, request.applicant_user_id = other.org_id, other.user_id
        db.commit()
    result = execute(client, headers, planned)
    assert result["plan"]["status"] == "BLOCKED"
    assert result["plan"]["steps"][0]["error_code"] == "REQUEST_SCOPE_DENIED"
    assert result["plan"]["steps"][0]["invocation_id"] is None


def test_unread_notification_filter_survives_language_planning_and_execution(client, accounts):
    owner = actor("generator")
    with SessionLocal() as db:
        for notice in db.scalars(select(UserNotification).where(UserNotification.user_id == owner.user_id)).all():
            notice.read_at = utc_now()
        for index in range(25):
            db.add(UserNotification(notification_id=f"flow-read-{index:02}", user_id=owner.user_id, org_id=owner.org_id, notification_type="TEST", title=f"A 已读通知 {index:02}", body="metadata only", read_at=utc_now(), dedupe_key=f"flow-read-{index}"))
        db.add(UserNotification(notification_id="flow-unread", user_id=owner.user_id, org_id=owner.org_id, notification_type="TEST", title="Z 未读通知", body="metadata only", dedupe_key="flow-unread"))
        db.commit()
    headers = accounts["generator"]
    planned = ask(client, headers, start(client, headers), "查看未读通知")
    assert planned["plan"]["plan"]["understanding"]["status_filter"] == "UNREAD"
    result = execute(client, headers, planned)
    output = result["plan"]["steps"][0]["output"]
    assert output["total"] == 1 and [item["entity_id"] for item in output["items"]] == ["flow-unread"]


def test_regulatory_audit_grant_does_not_expand_transaction_or_computation_scope(client, accounts):
    headers = accounts["regulator"]
    session = start(client, headers, entity_type="settlement_task", entity_id="task-history-t01")
    task_plan = ask(client, headers, session, "检查可信任务状态")
    assert task_plan["plan"]["status"] == "BLOCKED"
    assert task_plan["plan"]["steps"][0]["error_code"] == "TTC_SCOPE_DENIED"
    audit_plan = ask(client, headers, task_plan["session"], "解释审计报告")
    assert audit_plan["plan"]["status"] == "READY"
    audit = execute(client, headers, audit_plan)
    assert audit["plan"]["steps"][0]["output"]["task_id"] == "task-history-t01"
    assert audit["plan"]["steps"][0]["output"]["raw_data_accessed"] is False


def test_regulator_can_request_review_of_own_withdrawal_without_revoking_it(client, accounts):
    request_id = usage_request(client, accounts, applicant="regulator")
    headers = accounts["regulator"]
    planned = ask(client, headers, start(client, headers), f"撤销授权申请 {request_id}")
    assert planned["plan"]["intent_code"] == "REVOKE_USAGE_AUTHORIZATION"
    assert planned["plan"]["status"] == "PENDING_REVIEW"
    result = execute(client, headers, planned)
    assert result["plan"]["steps"][0]["output"]["review_requested"] is True
    assert result["plan"]["steps"][0]["output"]["business_mutation"] is False
    with SessionLocal() as db:
        current = db.get(DataUsageRequest, request_id)
        assert current.status == "SUBMITTED" and current.state_version == 1 and current.revoked_at is None
    foreign_id = usage_request(client, accounts)
    denied = ask(client, headers, result["session"], f"撤销授权申请 {foreign_id}")
    assert denied["plan"]["status"] == "BLOCKED" and denied["plan"]["steps"][0]["error_code"] == "REQUEST_SCOPE_DENIED"
    assert denied["plan"]["steps"][0]["request_id"] is None


@pytest.mark.parametrize(("question", "status"), [("列出已经批准的授权申请", "APPROVED"), ("列出被拒绝的申请", "REJECTED")])
def test_listing_past_authorization_decisions_is_a_filtered_read_not_a_new_write(client, accounts, question, status):
    selected_id = usage_request(client, accounts, purpose="历史决定")
    pending_id = usage_request(client, accounts, purpose="待处理申请")
    with SessionLocal() as db:
        db.get(DataUsageRequest, selected_id).status = status
        db.commit()
    headers = accounts["exchange"]
    planned = ask(client, headers, start(client, headers), question)
    assert planned["plan"]["intent_code"] == "LIST_AUTHORIZATIONS", planned["plan"]
    assert planned["plan"]["status"] == "READY" and planned["plan"]["steps"][0]["mode"] == "READ"
    result = execute(client, headers, planned)
    output = result["plan"]["steps"][0]["output"]
    assert output["total"] == 1 and {item["request_id"] for item in output["items"]} == {selected_id}
    with SessionLocal() as db:
        assert db.get(DataUsageRequest, selected_id).status == status
        assert db.get(DataUsageRequest, pending_id).status == "SUBMITTED"
        assert db.scalar(select(func.count(AuditLog.log_id)).where(AuditLog.action_code == "ASSISTANT_WRITE_REVIEW_REQUESTED")) == 0


def test_negated_quoted_candidate_does_not_override_the_positive_target(client, accounts):
    first_id = usage_request(client, accounts, purpose="申请A")
    second_id = usage_request(client, accounts, purpose="申请B")
    headers = accounts["exchange"]
    missing = ask(client, headers, start(client, headers), "我的申请批下来没有")
    assert missing["plan"]["status"] == "NEEDS_INPUT"
    assert {item["entity_id"] for item in missing["plan"]["plan"]["candidates"]} == {first_id, second_id}
    selected = ask(client, headers, missing["session"], "不要查看“申请A”，查看“申请B”的状态")
    assert selected["plan"]["intent_code"] == "QUERY_AUTHORIZATION_STATUS"
    assert selected["plan"]["status"] == "READY"
    assert selected["plan"]["steps"][0]["target_id"] == second_id
    result = execute(client, headers, selected)
    assert result["plan"]["steps"][0]["output"]["request_id"] == second_id
    assert result["plan"]["steps"][0]["output"]["raw_data_accessed"] is False
    with SessionLocal() as db:
        assert db.get(DataUsageRequest, first_id).status == "SUBMITTED"
        assert db.get(DataUsageRequest, second_id).status == "SUBMITTED"
        assert db.scalar(select(func.count(AuditLog.log_id)).where(AuditLog.action_code == "ASSISTANT_WRITE_REVIEW_REQUESTED")) == 0


def test_historical_who_and_trailing_which_questions_never_create_review_envelopes(client, accounts):
    approved_id = usage_request(client, accounts, purpose="已有审批决定")
    pending_id = usage_request(client, accounts, purpose="仍待审批")
    with SessionLocal() as db:
        db.get(DataUsageRequest, approved_id).status = "APPROVED"
        db.commit()
    headers = accounts["generator"]
    session = start(client, headers, entity_type="data_usage_request", entity_id=pending_id)
    historical = ask(client, headers, session, "谁批准了这条申请")
    assert historical["plan"]["intent_code"] == "QUERY_AUTHORIZATION_STATUS"
    assert historical["plan"]["status"] == "READY"
    assert historical["plan"]["steps"][0]["mode"] == "READ"
    assert historical["plan"]["steps"][0]["request_id"] is None
    history_result = execute(client, headers, historical)
    assert history_result["plan"]["steps"][0]["output"]["request_id"] == pending_id
    assert history_result["plan"]["steps"][0]["output"]["status_value"] == "SUBMITTED"
    listed = ask(client, headers, history_result["session"], "已经批准的授权申请有哪些")
    assert listed["plan"]["intent_code"] == "LIST_AUTHORIZATIONS" and listed["plan"]["status"] == "READY"
    assert listed["plan"]["steps"][0]["mode"] == "READ" and listed["plan"]["steps"][0]["request_id"] is None
    output = execute(client, headers, listed)["plan"]["steps"][0]["output"]
    assert output["total"] == 1 and {item["request_id"] for item in output["items"]} == {approved_id}
    with SessionLocal() as db:
        assert db.get(DataUsageRequest, approved_id).status == "APPROVED"
        assert db.get(DataUsageRequest, pending_id).status == "SUBMITTED"
        assert db.scalar(select(func.count(AuditLog.log_id)).where(AuditLog.action_code == "ASSISTANT_WRITE_REVIEW_REQUESTED")) == 0
