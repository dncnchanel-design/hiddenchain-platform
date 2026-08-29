from __future__ import annotations

from datetime import date

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import AnomalyEvent, AuditReport, MetricRecord, Organization, SettlementResult, SettlementRule, SettlementTask, User
from app.security import hash_password


def _login(client, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _add_scoped_subjects() -> None:
    with SessionLocal() as db:
        rule = db.scalar(select(SettlementRule).order_by(SettlementRule.created_at))
        assert rule is not None
        db.add(
            SettlementTask(
                task_id="task-coal-exchange-only",
                capsule_id="capsule-coal-exchange-only",
                task_name="煤炭交易中心隔离任务",
                trade_batch_no="COAL-SCOPE-001",
                period_start=date(2026, 8, 1),
                period_end=date(2026, 8, 2),
                rule_id=rule.rule_id,
                creator_org_id="org-exchange-coal-t01",
                status="READY",
                current_stage="待启动结算",
            )
        )
        db.add_all(
            [
                AnomalyEvent(
                    event_id="anomaly-electricity-scope",
                    task_id="task-ready-t01",
                    event_type="POLICY_DENIED",
                    risk_level="HIGH",
                    title="电力范围事件",
                    description="用于验证任务隔离",
                ),
                AnomalyEvent(
                    event_id="anomaly-coal-scope",
                    task_id="task-coal-exchange-only",
                    event_type="POLICY_DENIED",
                    risk_level="HIGH",
                    title="煤炭范围事件",
                    description="用于验证任务隔离",
                ),
            ]
        )
        db.add(
            Organization(
                org_id="org-regulator-limited",
                org_type="REGULATOR",
                org_name="受限监管主体",
                status="ACTIVE",
            )
        )
        db.add_all(
            [
                User(
                    user_id="user-regulator-limited",
                    org_id="org-regulator-limited",
                    username="regulator_limited",
                    password_hash=hash_password("limited123"),
                    display_name="受限监管账号",
                    role_code="REGULATOR",
                    permissions_json=["VIEW_AUDIT"],
                    status="ACTIVE",
                ),
                User(
                    user_id="user-regulator-task-grant",
                    org_id="org-regulator-limited",
                    username="regulator_task_grant",
                    password_hash=hash_password("granted123"),
                    display_name="任务授权监管账号",
                    role_code="REGULATOR",
                    permissions_json=["VIEW_AUDIT", "VIEW_AUDIT:TASK:task-ready-t01"],
                    status="ACTIVE",
                ),
            ]
        )
        db.commit()


def test_audit_scope_isolated_by_exchange_subject_and_individual_grant(client, auth_headers):
    _add_scoped_subjects()
    coal_exchange = _login(client, "exchange_coal", "exchange123")
    limited_regulator = _login(client, "regulator_limited", "limited123")
    granted_regulator = _login(client, "regulator_task_grant", "granted123")

    assert client.get("/api/audit/timeline/task-ready-t01", headers=coal_exchange).status_code == 404
    assert client.get("/api/trust-space/audit/tasks/task-ready-t01", headers=coal_exchange).status_code == 404
    assert client.post(
        "/api/agent/query",
        headers=coal_exchange,
        json={"task_id": "task-ready-t01", "question": "当前任务证据是否完整"},
    ).status_code == 404

    coal_anomalies = client.get("/api/anomalies", headers=coal_exchange)
    assert coal_anomalies.status_code == 200
    assert {item["event_id"] for item in coal_anomalies.json()} == {"anomaly-coal-scope"}
    assert client.post(
        "/api/anomalies/anomaly-electricity-scope/resolve",
        headers=coal_exchange,
        json={"resolution": "不应允许跨主体处置"},
    ).status_code == 403

    assert client.get("/api/trust-space/audit/tasks/task-ready-t01", headers=limited_regulator).status_code == 404
    assert client.get("/api/audit/timeline/task-ready-t01", headers=limited_regulator).status_code == 404
    assert client.get("/api/audit/lineage/task-ready-t01", headers=limited_regulator).status_code == 404
    assert client.post(
        "/api/agent/query",
        headers=limited_regulator,
        json={"task_id": "task-ready-t01", "question": "当前任务证据是否完整"},
    ).status_code == 404
    assert client.post(
        "/api/audit/reports",
        headers=limited_regulator,
        json={"task_id": "task-ready-t01", "template_code": "REGULATORY_AUDIT_V1"},
    ).status_code == 404
    limited_list = client.get("/api/trust-space/audit", headers=limited_regulator)
    assert limited_list.status_code == 200
    assert limited_list.json()["total"] == 0
    assert client.get("/api/anomalies", headers=limited_regulator).json() == []
    with SessionLocal() as db:
        out_of_scope_result = db.scalar(select(SettlementResult).where(SettlementResult.task_id == "task-history-t01"))
        out_of_scope_report = db.scalar(select(AuditReport).where(AuditReport.task_id == "task-history-t01"))
        assert out_of_scope_result is not None
        assert out_of_scope_report is not None
        out_of_scope_result_id = out_of_scope_result.result_id
        out_of_scope_report_id = out_of_scope_report.report_id
    assert client.get("/api/trust-space/results", headers=limited_regulator).json()["total"] == 0
    assert client.get(
        f"/api/trust-space/results/{out_of_scope_result_id}", headers=limited_regulator
    ).status_code == 404
    assert client.post(
        f"/api/audit/reports/{out_of_scope_report_id}/decision",
        headers=limited_regulator,
        json={"decision": "APPROVE", "opinion": "不应允许跨范围审批"},
    ).status_code == 404
    assert client.get("/api/trust-space/audit/tasks/task-ready-t01", headers=granted_regulator).status_code == 200
    assert client.get("/api/trust-space/audit/tasks/task-coal-exchange-only", headers=granted_regulator).status_code == 404
    assert client.post(
        "/api/anomalies/anomaly-coal-scope/resolve",
        headers=granted_regulator,
        json={"resolution": "不应允许跨任务授权处置"},
    ).status_code == 404

    assert client.get("/api/trust-space/audit", headers=auth_headers["admin"]).status_code == 403
    assert client.get("/api/audit/reports", headers=auth_headers["admin"]).status_code == 403


def test_metrics_summary_uses_uniform_freshness_dto_and_no_business_detail(client, auth_headers):
    response = client.get("/api/metrics/summary", headers=auth_headers["admin"])
    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {"measurement_scope", "generated_at", "metrics", "security_boundary"}
    assert payload["metrics"]
    required = {
        "code", "value", "unit", "window_start", "window_end", "cutoff_at",
        "source", "freshness", "null_reason",
    }
    assert all(set(item) == required for item in payload["metrics"])
    metric_codes = {item["code"] for item in payload["metrics"]}
    assert "SCENARIO_COUPLING_COUNT" not in metric_codes
    assert "VERIFY_RATE" not in metric_codes
    assert "task_id" not in response.text
    assert "org_id" not in response.text
    assert "authorization" not in response.text.lower()


def test_metrics_unknown_measurements_are_null_not_zero(client, auth_headers):
    with SessionLocal() as db:
        db.execute(delete(MetricRecord))
        db.commit()
    response = client.get("/api/metrics/summary", headers=auth_headers["admin"])
    assert response.status_code == 200
    measured = {
        item["code"]: item
        for item in response.json()["metrics"]
        if item["source"] == "metric_records_24h_average"
    }
    assert measured
    assert all(item["value"] is None for item in measured.values())
    assert all(item["freshness"] == "UNKNOWN" for item in measured.values())
    assert all(item["null_reason"] == "NO_MEASUREMENT" for item in measured.values())
