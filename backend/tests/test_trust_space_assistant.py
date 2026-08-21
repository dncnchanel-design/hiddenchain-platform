from __future__ import annotations

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import AssistantMessage, AssistantPlan, AssistantPlanStep, AuditLog, BlockchainEvidence, DataUsageRequest
from app.trust_models import DataAsset, DataAssetVersion


ASSISTANT_PREFIX = "/api/trust-space/assistant"


def _asset_id(owner_org_id: str = "org-generator-t01") -> str:
    with SessionLocal() as db:
        asset = db.scalar(
            select(DataAsset)
            .where(DataAsset.owner_org_id == owner_org_id)
            .order_by(DataAsset.created_at.asc())
        )
        assert asset is not None
        return asset.asset_id


def _asset_version(asset_id: str) -> str:
    with SessionLocal() as db:
        version = db.scalar(
            select(DataAssetVersion)
            .where(DataAssetVersion.asset_id == asset_id)
            .order_by(DataAssetVersion.version_no.desc())
        )
        assert version is not None
        return version.version_id


def _session(client, headers, *, entity_type: str | None = None, entity_id: str | None = None, key: str | None = None):
    request_headers = dict(headers)
    if key:
        request_headers["Idempotency-Key"] = key
    response = client.post(
        f"{ASSISTANT_PREFIX}/sessions",
        headers=request_headers,
        json={
            "page_path": "/trusted-space/workbench",
            "entity_type": entity_type,
            "entity_id": entity_id,
        },
    )
    assert response.status_code in {200, 201}, response.text
    return response


def _message(client, headers, session_id: str, content: str, version: int, *, key: str | None = None):
    request_headers = {**headers, "If-Match": f'"{version}"'}
    if key:
        request_headers["Idempotency-Key"] = key
    return client.post(
        f"{ASSISTANT_PREFIX}/sessions/{session_id}/messages",
        headers=request_headers,
        json={"content": content},
    )


def _execute(client, headers, session_id: str, plan_id: str, version: int, *, step_id: str | None = None):
    return client.post(
        f"{ASSISTANT_PREFIX}/sessions/{session_id}/plans/{plan_id}/execute",
        headers={**headers, "If-Match": f'"{version}"'},
        json={"step_id": step_id},
    )


def _usage_request(client, auth_headers, asset_id: str) -> str:
    response = client.post(
        "/api/data/access-requests",
        headers={**auth_headers["exchange"], "Idempotency-Key": "assistant-fixture-access-001"},
        json={
            "asset_id": asset_id,
            "asset_version_id": _asset_version(asset_id),
            "purpose": "assistant regression verification",
            "usage_mode": "AGGREGATE_ONLY",
            "requested_scope": {"period": "2026-07"},
            "requested_fields": ["energy_mwh"],
            "duration_days": 30,
            "terms": {"raw_data_export": False},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["request_id"]


def test_assistant_openapi_scope_persistence_and_multiple_plans(client, auth_headers):
    paths = client.get("/api/openapi.json").json()["paths"]
    expected = {
        f"{ASSISTANT_PREFIX}/sessions",
        f"{ASSISTANT_PREFIX}/sessions/{{session_id}}/resume",
        f"{ASSISTANT_PREFIX}/sessions/{{session_id}}/messages",
        f"{ASSISTANT_PREFIX}/sessions/{{session_id}}/plans",
        f"{ASSISTANT_PREFIX}/sessions/{{session_id}}/plans/{{plan_id}}",
        f"{ASSISTANT_PREFIX}/sessions/{{session_id}}/plans/{{plan_id}}/execute",
        f"{ASSISTANT_PREFIX}/sessions/{{session_id}}/plans/{{plan_id}}/cancel",
        f"{ASSISTANT_PREFIX}/sessions/{{session_id}}/plans/{{plan_id}}/retry",
        f"{ASSISTANT_PREFIX}/tools",
    }
    assert expected <= set(paths)

    asset_id = _asset_id()
    created = _session(
        client,
        auth_headers["generator"],
        entity_type="data_asset",
        entity_id=asset_id,
        key="assistant-session-001",
    )
    session = created.json()
    assert created.headers["etag"] == '"1"'
    replay = _session(
        client,
        auth_headers["generator"],
        entity_type="data_asset",
        entity_id=asset_id,
        key="assistant-session-001",
    )
    assert replay.status_code == 200
    assert replay.json()["session_id"] == session["session_id"]
    assert replay.json()["idempotent_replay"] is True

    first = _message(
        client,
        auth_headers["generator"],
        session["session_id"],
        "检查资产完整性",
        1,
        key="assistant-message-001",
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["plan"]["status"] == "READY"
    assert body["plan"]["steps"][0]["mode"] == "READ"
    assert body["plan"]["capability_state"] == "LOCAL_REAL_DETERMINISTIC"
    assert body["session"]["state_version"] == 2

    message_replay = _message(
        client,
        auth_headers["generator"],
        session["session_id"],
        "检查资产完整性",
        2,
        key="assistant-message-001",
    )
    assert message_replay.status_code == 200
    assert message_replay.json()["message"]["idempotent_replay"] is True

    second = _message(
        client,
        auth_headers["generator"],
        session["session_id"],
        "检查资产完整性",
        2,
        key="assistant-message-002",
    )
    assert second.status_code == 201, second.text
    assert second.json()["session"]["state_version"] == 3
    assert second.json()["plan"]["plan_id"] != body["plan"]["plan_id"]

    listed_messages = client.get(
        f"{ASSISTANT_PREFIX}/sessions/{session['session_id']}/messages",
        headers=auth_headers["generator"],
    )
    listed_plans = client.get(
        f"{ASSISTANT_PREFIX}/sessions/{session['session_id']}/plans",
        headers=auth_headers["generator"],
    )
    assert listed_messages.status_code == 200
    assert listed_messages.json()["total"] == 4
    assert listed_plans.status_code == 200
    assert listed_plans.json()["total"] == 2
    assert {item["state_version"] for item in listed_plans.json()["items"]} == {1}

    denied = client.get(
        f"{ASSISTANT_PREFIX}/sessions/{session['session_id']}/messages",
        headers=auth_headers["retailer"],
    )
    assert denied.status_code == 403

    stale = _message(
        client,
        auth_headers["generator"],
        session["session_id"],
        "检查资产完整性",
        1,
    )
    assert stale.status_code == 412
    assert stale.json()["detail"]["code"] == "ASSISTANT_VERSION_CONFLICT"

    resumed = client.post(
        f"{ASSISTANT_PREFIX}/sessions/{session['session_id']}/resume",
        headers=auth_headers["generator"],
    )
    assert resumed.status_code == 200
    assert resumed.json()["idempotent_replay"] is True

    with SessionLocal() as db:
        assert db.scalar(select(func.count(AssistantMessage.message_id))) == 4
        assert db.scalar(select(func.count(AssistantPlan.plan_id))) == 2
        assert db.scalar(select(func.count(AssistantPlanStep.step_id))) == 2


def test_assistant_real_read_shortcuts_are_scoped_and_truthful(client, auth_headers):
    asset_id = _asset_id()
    request_id = _usage_request(client, auth_headers, asset_id)
    targets = [
        ("generator", "data_asset", asset_id, "检查资产完整性", "asset_id"),
        ("exchange", "data_usage_request", request_id, "查询授权申请状态", "request_id"),
        ("exchange", "settlement_task", "task-ready-t01", "检查TTC状态", "task_id"),
        ("regulator", "settlement_task", "task-history-t01", "核验证据摘要", "task_id"),
        ("exchange", "settlement_task", "task-history-t01", "解释审计报告", "task_id"),
    ]
    audit_actions: list[str] = []
    for index, (role, entity_type, entity_id, content, key_name) in enumerate(targets):
        session = _session(
            client,
            auth_headers[role],
            entity_type=entity_type,
            entity_id=entity_id,
            key=f"assistant-read-session-{index}",
        ).json()
        planned = _message(
            client,
            auth_headers[role],
            session["session_id"],
            content,
            1,
            key=f"assistant-read-message-{index}",
        )
        assert planned.status_code == 201, planned.text
        planned_body = planned.json()
        assert planned_body["plan"]["status"] == "READY"
        action = planned_body["plan"]["intent_code"]
        executed = _execute(
            client,
            auth_headers[role],
            session["session_id"],
            planned_body["plan"]["plan_id"],
            1,
        )
        assert executed.status_code == 200, executed.text
        plan = executed.json()["plan"]
        assert plan["status"] == "SUCCEEDED", plan
        output = plan["steps"][0]["output"]
        assert output["status"] == "SUCCEEDED"
        assert output[key_name] == entity_id
        assert output["raw_data_accessed"] is False
        assert "password_hash" not in str(output)
        assert "data_ref" not in str(output)
        assert "payload_json" not in str(output)
        audit_actions.append(action)

    assert audit_actions == [
        "CHECK_ASSET_INTEGRITY",
        "QUERY_AUTHORIZATION_STATUS",
        "CHECK_TTC_STATUS",
        "VERIFY_EVIDENCE_SUMMARY",
        "EXPLAIN_AUDIT",
    ]
    with SessionLocal() as db:
        invocations = db.scalars(
            select(AuditLog).where(AuditLog.action_code == "ASSISTANT_TOOL_INVOKE")
        ).all()
        assert len(invocations) == len(targets)
        assert all(item.details_json.get("raw_data_accessed") is False for item in invocations)

    outsider = _session(
        client,
        auth_headers["retailer"],
        entity_type="data_asset",
        entity_id=asset_id,
        key="assistant-outsider-session",
    ).json()
    outsider_plan = _message(
        client,
        auth_headers["retailer"],
        outsider["session_id"],
        "检查资产完整性",
        1,
        key="assistant-outsider-message",
    )
    assert outsider_plan.status_code == 201
    outsider_body = outsider_plan.json()
    assert outsider_body["plan"]["status"] == "READY"
    outsider_execute = _execute(
        client,
        auth_headers["retailer"],
        outsider["session_id"],
        outsider_body["plan"]["plan_id"],
        1,
    )
    assert outsider_execute.status_code == 200
    outsider_result = outsider_execute.json()["plan"]
    assert outsider_result["status"] == "BLOCKED"
    assert outsider_result["steps"][0]["error_code"] == "ASSET_SCOPE_DENIED"
    assert outsider_result["steps"][0]["output"] == {
        "status": "BLOCKED",
        "error_code": "ASSET_SCOPE_DENIED",
        "raw_data_accessed": False,
    }


def test_assistant_unknown_write_review_and_plan_controls(client, auth_headers):
    unknown_session = _session(
        client,
        auth_headers["exchange"],
        entity_type="settlement_task",
        entity_id="task-ready-t01",
        key="assistant-unknown-session",
    ).json()
    unknown = _message(
        client,
        auth_headers["exchange"],
        unknown_session["session_id"],
        "请帮我安排一场会议",
        1,
        key="assistant-unknown-message",
    )
    assert unknown.status_code == 201
    unknown_plan = unknown.json()["plan"]
    assert unknown_plan["intent_code"] == "UNKNOWN_INTENT"
    assert unknown_plan["status"] == "BLOCKED"
    assert "需要明确" in unknown_plan["plan"]["explanation"]
    unknown_id = unknown_plan["plan_id"]

    ready = client.post(
        f"{ASSISTANT_PREFIX}/sessions/{unknown_session['session_id']}/plans/{unknown_id}/retry",
        headers={**auth_headers["exchange"], "If-Match": '"1"'},
    )
    assert ready.status_code == 200, ready.text
    assert ready.json()["plan"]["status"] == "READY"
    assert ready.json()["plan"]["state_version"] == 2
    stale_cancel = client.post(
        f"{ASSISTANT_PREFIX}/sessions/{unknown_session['session_id']}/plans/{unknown_id}/cancel",
        headers={**auth_headers["exchange"], "If-Match": '"1"'},
    )
    assert stale_cancel.status_code == 412
    cancelled = client.post(
        f"{ASSISTANT_PREFIX}/sessions/{unknown_session['session_id']}/plans/{unknown_id}/cancel",
        headers={**auth_headers["exchange"], "If-Match": '"2"'},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["plan"]["status"] == "CANCELLED"
    status_response = client.get(
        f"{ASSISTANT_PREFIX}/sessions/{unknown_session['session_id']}/plans/{unknown_id}",
        headers=auth_headers["exchange"],
    )
    assert status_response.status_code == 200
    assert status_response.json()["plan"]["status"] == "CANCELLED"

    asset_id = _asset_id()
    before_requests = client.get("/api/data/access-requests", headers=auth_headers["exchange"]).json()["total"]
    write_session = _session(
        client,
        auth_headers["exchange"],
        entity_type="data_asset",
        entity_id=asset_id,
        key="assistant-write-session",
    ).json()
    write = _message(
        client,
        auth_headers["exchange"],
        write_session["session_id"],
        "提交申请",
        1,
        key="assistant-write-message",
    )
    assert write.status_code == 201, write.text
    write_plan = write.json()["plan"]
    assert write_plan["status"] == "PENDING_REVIEW"
    write_step = write_plan["steps"][0]
    assert write_step["mode"] == "WRITE"
    assert write_step["status"] == "PENDING_REVIEW"
    assert write_step["request_id"]
    assert write_plan["capability_state"] == "PENDING_REVIEW"

    review = _execute(
        client,
        auth_headers["exchange"],
        write_session["session_id"],
        write_plan["plan_id"],
        1,
    )
    assert review.status_code == 200, review.text
    review_plan = review.json()["plan"]
    assert review_plan["status"] == "PENDING_REVIEW"
    assert review_plan["state_version"] == 2
    assert review_plan["steps"][0]["output"]["business_mutation"] is False
    assert review_plan["steps"][0]["output"]["review_requested"] is True

    replay_review = _execute(
        client,
        auth_headers["exchange"],
        write_session["session_id"],
        write_plan["plan_id"],
        2,
    )
    assert replay_review.status_code == 200
    assert replay_review.json()["plan"]["idempotent_replay"] is True
    after_requests = client.get("/api/data/access-requests", headers=auth_headers["exchange"]).json()["total"]
    assert after_requests == before_requests

    denied_write = _session(
        client,
        auth_headers["generator"],
        entity_type="data_asset",
        entity_id=asset_id,
        key="assistant-denied-write-session",
    ).json()
    denied_plan = _message(
        client,
        auth_headers["generator"],
        denied_write["session_id"],
        "提交申请",
        1,
        key="assistant-denied-write-message",
    )
    assert denied_plan.status_code == 201
    assert denied_plan.json()["plan"]["status"] == "BLOCKED"

    with SessionLocal() as db:
        review_logs = db.scalars(
            select(AuditLog).where(AuditLog.action_code == "ASSISTANT_WRITE_REVIEW_REQUESTED")
        ).all()
        assert len(review_logs) == 1
        assert review_logs[0].details_json["business_mutation"] is False


def test_assistant_tool_catalog_is_role_filtered_and_real(client, auth_headers):
    exchange = client.get(f"{ASSISTANT_PREFIX}/tools", headers=auth_headers["exchange"])
    generator = client.get(f"{ASSISTANT_PREFIX}/tools", headers=auth_headers["generator"])
    assert exchange.status_code == 200
    assert generator.status_code == 200
    exchange_tools = {item["tool_code"]: item for item in exchange.json()["items"]}
    generator_tools = {item["tool_code"]: item for item in generator.json()["items"]}
    assert "TemplateAuditFallback" in exchange_tools
    assert "TemplateAuditFallback" not in generator_tools
    assert "WorkflowEngine" in generator_tools
    assert "EDCAdapter+OPAAdapter" in generator_tools
    assert all(item["source_of_truth"] == "agent_tools" for item in exchange_tools.values())
    assert all(item["capability_state"] in {"LOCAL_REAL", "ADAPTER", "DEMO"} for item in exchange_tools.values())

    with SessionLocal() as db:
        assert db.scalar(select(func.count(AssistantPlanStep.step_id))) == 0
        assert db.scalar(select(func.count(DataUsageRequest.request_id))) == 0
        assert db.scalar(select(func.count(BlockchainEvidence.evidence_id))) >= 1
