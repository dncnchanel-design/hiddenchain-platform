import pytest


def _run_journey(client, auth_headers, run):
    payload = {
        "task_name": f"闭环验收 {run}",
        "trade_batch_no": "TB-2026-07-T01",
        "period_start": "2026-07-01",
        "period_end": "2026-07-31",
        "rule_id": "rule-settlement-v1",
        "participants": [
            {"org_id": "org-generator-t01", "role_in_task": "GENERATOR"},
            {"org_id": "org-retailer-t01", "role_in_task": "RETAILER"},
        ],
        "compute_mode": "LOCAL_CONTROLLED",
        "algorithm_code": "CONTROLLED_SETTLEMENT_V1",
    }
    created = client.post("/api/settlement/tasks", headers=auth_headers["exchange"], json=payload)
    assert created.status_code == 201, created.text
    task_id = created.json()["task_id"]
    assert created.json()["readiness"]["preflight_passed"]

    def headers(role):
        task = client.get(f"/api/settlement/tasks/{task_id}", headers=auth_headers[role])
        assert task.status_code == 200, task.text
        return {**auth_headers[role], "If-Match": task.headers["etag"]}

    executed = client.post(f"/api/settlement/tasks/{task_id}/run", headers=headers("exchange"), json={"compute_mode": "LOCAL_CONTROLLED", "algorithm_code": "CONTROLLED_SETTLEMENT_V1"})
    assert executed.status_code == 200, executed.text
    result = executed.json()
    assert result["compute_job"]["status"] == "SUCCESS"
    assert result["task"]["status"] == "PENDING_CONFIRMATION"
    computed = result["compute_job"]["result_json"]
    assert computed["settlement_energy_mwh"] == 12490
    assert computed["base_amount_yuan"] == 5245800
    assert computed["deviation_mwh"] == 78.4
    assert computed["deviation_penalty_yuan"] == 0
    assert computed["service_fee_yuan"] == 39968
    assert computed["payable_amount_yuan"] == 5205832
    scoped = {item["org_id"]: item for item in result["results"] if item["result_scope"] == "ORG"}
    assert scoped["org-generator-t01"]["result_json"]["amount_direction"] == "RECEIVABLE"
    assert scoped["org-retailer-t01"]["result_json"]["amount_direction"] == "PAYABLE"
    assert all(item["result_json"]["amount_yuan"] == 5205832 for item in scoped.values())
    for role, org in [("generator", "org-generator-t01"), ("retailer", "org-retailer-t01")]:
        if role == "retailer":
            report = client.post(f"/api/audit/reports/{result['report']['report_id']}/decision", headers=auth_headers["regulator"], json={"decision": "APPROVE", "opinion": "审计复核通过"})
            assert report.status_code == 200, report.text
        confirmation = client.post(f"/api/results/{scoped[org]['result_id']}/confirm", headers=headers(role), json={"decision": "APPROVE", "opinion": "同意结算结果"})
        assert confirmation.status_code == 200, confirmation.text
        if role == "generator":
            assert confirmation.json()["task"]["status"] == "PARTIALLY_CONFIRMED"
    assert confirmation.json()["task"]["ttc"]["state"] == "ARCHIVED"
    assert confirmation.json()["formal_evidence"]["status"] == "PUBLISHED_DEMO"

    return task_id, {item["result_id"] for item in scoped.values()}


def test_archived_settlement_cannot_be_repeated(client, auth_headers):
    task_id, _ = _run_journey(client, auth_headers, 0)
    archived = client.get(f"/api/settlement/tasks/{task_id}", headers=auth_headers["exchange"])
    assert archived.status_code == 200
    assert archived.json()["ttc"]["state"] == "ARCHIVED"
    payload = {
        "task_name": "同一业务的第二个任务", "trade_batch_no": "TB-2026-07-T01",
        "period_start": "2026-07-01", "period_end": "2026-07-31", "rule_id": "rule-settlement-v1",
        "participants": [{"org_id": "org-generator-t01", "role_in_task": "GENERATOR"}, {"org_id": "org-retailer-t01", "role_in_task": "RETAILER"}],
    }
    created = client.post("/api/settlement/tasks", headers=auth_headers["exchange"], json=payload)
    assert created.status_code == 201
    second = created.json()["task_id"]
    view = client.get(f"/api/settlement/tasks/{second}", headers=auth_headers["exchange"])
    response = client.post(f"/api/settlement/tasks/{second}/run", headers={**auth_headers["exchange"], "If-Match": view.headers["etag"]}, json={"compute_mode": "LOCAL_CONTROLLED", "algorithm_code": "CONTROLLED_SETTLEMENT_V1"})
    assert response.status_code == 409


def test_same_task_identity_with_changed_rule_or_participant_is_not_replayed(client, auth_headers):
    from app.database import SessionLocal
    from app.models import Organization, SettlementRule, SettlementTask

    with SessionLocal() as db:
        original = db.get(SettlementRule, "rule-settlement-v1")
        db.add(SettlementRule(rule_id="rule-other", rule_name="另一个规则", rule_version="other", description="测试", source_refs_json=[], formula_dsl=original.formula_dsl, parameters_json=original.parameters_json, policy_refs_json=[], approver_signatures_json=[], rule_hash="other", status="ACTIVE"))
        db.add(Organization(org_id="org-generator-other", org_name="另一发电企业", org_type="GENERATOR", energy_domain="electricity", credit_code="QA-OTHER-GENERATOR", status="ACTIVE"))
        db.commit()
    payload = {
        "task_name": "同名不同内容", "trade_batch_no": "TB-2026-07-T01",
        "period_start": "2026-07-01", "period_end": "2026-07-31", "rule_id": "rule-settlement-v1",
        "participants": [{"org_id": "org-generator-t01", "role_in_task": "GENERATOR"}, {"org_id": "org-retailer-t01", "role_in_task": "RETAILER"}],
    }
    first = client.post("/api/settlement/tasks", headers=auth_headers["exchange"], json=payload)
    assert first.status_code == 201, first.text
    replay = client.post("/api/settlement/tasks", headers=auth_headers["exchange"], json=payload)
    assert replay.status_code == 201 and replay.json()["task_id"] == first.json()["task_id"]
    for changed in [
        {**payload, "rule_id": "rule-other"},
        {**payload, "participants": [{"org_id": "org-generator-other", "role_in_task": "GENERATOR"}, payload["participants"][1]]},
    ]:
        response = client.post("/api/settlement/tasks", headers=auth_headers["exchange"], json=changed)
        assert response.status_code == 409, response.text
    with SessionLocal() as db:
        db.get(SettlementTask, first.json()["task_id"]).request_fingerprint = None
        db.commit()
    assert client.post("/api/settlement/tasks", headers=auth_headers["exchange"], json=payload).status_code == 409


def test_same_name_and_batch_can_create_distinct_periods(client, auth_headers):
    payload = {
        "task_name": "不同周期同名任务", "trade_batch_no": "TB-2026-07-T01",
        "period_start": "2026-07-01", "period_end": "2026-07-31", "rule_id": "rule-settlement-v1",
        "participants": [{"org_id": "org-generator-t01", "role_in_task": "GENERATOR"}, {"org_id": "org-retailer-t01", "role_in_task": "RETAILER"}],
    }
    first = client.post("/api/settlement/tasks", headers=auth_headers["exchange"], json=payload)
    assert first.status_code == 201, first.text
    second = client.post("/api/settlement/tasks", headers=auth_headers["exchange"], json={**payload, "period_end": "2026-07-30"})
    assert second.status_code == 201, second.text
    assert first.json()["task_id"] != second.json()["task_id"]
    assert first.json()["capsule_id"] != second.json()["capsule_id"]


@pytest.mark.parametrize("different_payload,use_key", [(False, False), (False, True), (True, True)])
def test_concurrent_creation_returns_conflict_without_server_error(client, auth_headers, monkeypatch, different_payload, use_key):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from app.database import SessionLocal
    from app.models import AuditLog, SettlementTask, TaskParticipant

    original_scalar = Session.scalar
    gate = Barrier(2, timeout=15)

    def synchronized_scalar(self, statement, *args, **kwargs):
        value = original_scalar(self, statement, *args, **kwargs)
        if "WHERE settlement_tasks.trade_batch_no =" in str(statement):
            gate.wait()
        return value

    monkeypatch.setattr(Session, "scalar", synchronized_scalar)
    payload = {
        "task_name": "并发请求", "trade_batch_no": "TB-2026-07-T01",
        "period_start": "2026-07-01", "period_end": "2026-07-31", "rule_id": "rule-settlement-v1",
        "participants": [{"org_id": "org-generator-t01", "role_in_task": "GENERATOR"}, {"org_id": "org-retailer-t01", "role_in_task": "RETAILER"}],
    }
    headers = {**auth_headers["exchange"], **({"Idempotency-Key": "concurrent-task-test"} if use_key else {})}
    second = {**payload, "business_description": "不同请求"} if different_payload else payload
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(client.post, "/api/settlement/tasks", headers=headers, json=body) for body in (payload, second)]
        responses = [future.result() for future in futures]
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert "task_id" not in next(response.json() for response in responses if response.status_code == 409)
    winner = next(response.json() for response in responses if response.status_code == 201)
    with SessionLocal() as db:
        tasks = db.scalars(select(SettlementTask).where(SettlementTask.task_name == payload["task_name"])).all()
        assert len(tasks) == 1 and tasks[0].task_id == winner["task_id"]
        participants = db.scalars(select(TaskParticipant).where(TaskParticipant.task_id == tasks[0].task_id)).all()
        assert {p.org_id for p in participants} == {"org-generator-t01", "org-retailer-t01"}
        audit = db.scalars(select(AuditLog).where(AuditLog.target_id == tasks[0].task_id, AuditLog.action_code == "CREATE_SETTLEMENT_TASK")).all()
        assert len(audit) == 1
