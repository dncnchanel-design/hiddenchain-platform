from __future__ import annotations

from datetime import datetime

from sqlalchemy import insert, select

from app.database import SessionLocal
from app.models import (
    AnomalyEvent,
    AuditLog,
    AuditReport,
    BlockchainEvidence,
    PrivacyComputeJob,
    SettlementResult,
    User,
)


def _audit_log(*, log_id: str, target_type: str, target_id: str, occurred_at: datetime):
    return AuditLog(
        log_id=log_id,
        occurred_at=occurred_at,
        actor_user_id="user-exchange",
        actor_org_id="org-exchange-t01",
        actor_name="交易中心验证员",
        action_code=f"SCOPE_{target_type}",
        target_type=target_type,
        target_id=target_id,
        result="SUCCESS",
        trace_id=f"trace-{log_id}",
        details_json={},
    )


def test_audit_scope_follows_core_entities_in_list_detail_and_export(client, auth_headers):
    occurred_at = datetime(2099, 2, 1, 0, 0, 0)
    with SessionLocal() as db:
        result = SettlementResult(
            result_id="result-audit-scope",
            task_id="task-ready-t01",
            org_id=None,
            result_scope="SUMMARY",
            result_json={},
            result_hash="result-audit-scope-hash",
            confirm_status="UNCONFIRMED",
            created_at=occurred_at,
        )
        anomaly = AnomalyEvent(
            event_id="anomaly-audit-scope",
            task_id="task-ready-t01",
            event_type="AUDIT_SCOPE_TEST",
            risk_level="LOW",
            title="scope test",
            description="scope test",
            evidence_json={},
            dedupe_key="audit-scope-test",
            created_at=occurred_at,
        )
        evidence = BlockchainEvidence(
            evidence_id="evidence-audit-scope",
            task_id="task-ready-t01",
            stage="POST_COMPUTE",
            biz_type="AUDIT_SCOPE_TEST",
            biz_id=result.result_id,
            evidence_hash="evidence-audit-scope-hash",
            payload_json={},
            tx_hash="tx-audit-scope",
            block_height=1,
            created_at=occurred_at,
        )
        job = PrivacyComputeJob(
            job_id="job-audit-scope",
            task_id="task-ready-t01",
            algorithm_code="AUDIT_SCOPE_TEST",
            input_hashes_json=[],
            result_json={},
            status="SUCCESS",
            progress=100,
            privacy_guarantees_json={},
            created_at=occurred_at,
        )
        report = AuditReport(
            report_id="report-audit-scope",
            task_id="task-ready-t01",
            template_code="AUDIT_SCOPE_TEST",
            report_title="scope test",
            report_content="scope test",
            report_hash="report-audit-scope-hash",
            risk_level="LOW",
            evidence_refs_json=[],
            created_at=occurred_at,
        )
        db.add_all([result, anomaly, evidence, job, report])
        db.add_all(
            [
                _audit_log(
                    log_id=f"log-{target_type.lower()}",
                    target_type=target_type,
                    target_id=target_id,
                    occurred_at=occurred_at,
                )
                for target_type, target_id in (
                    ("SETTLEMENT_RESULT", result.result_id),
                    ("ANOMALY_EVENT", anomaly.event_id),
                    ("BLOCKCHAIN_EVIDENCE", evidence.evidence_id),
                    ("PRIVACY_COMPUTE_JOB", job.job_id),
                    ("AUDIT_REPORT", report.report_id),
                )
            ]
        )
        db.commit()

    expected_actions = {
        "SCOPE_SETTLEMENT_RESULT",
        "SCOPE_ANOMALY_EVENT",
        "SCOPE_BLOCKCHAIN_EVIDENCE",
        "SCOPE_PRIVACY_COMPUTE_JOB",
        "SCOPE_AUDIT_REPORT",
    }
    listing = client.get(
        "/api/trust-space/audit?page_size=100",
        headers=auth_headers["regulator"],
    )
    assert listing.status_code == 200, listing.text
    assert expected_actions <= {item["action_code"] for item in listing.json()["items"]}

    detail = client.get(
        "/api/trust-space/audit/tasks/task-ready-t01",
        headers=auth_headers["regulator"],
    )
    assert detail.status_code == 200, detail.text
    assert expected_actions <= {item["action_code"] for item in detail.json()["audit_chain"]}

    exported = client.get(
        "/api/trust-space/audit/export?format=json",
        headers=auth_headers["regulator"],
    )
    assert exported.status_code == 200, exported.text
    assert expected_actions <= {item["action_code"] for item in exported.json()["items"]}
    assert exported.json()["exported_count"] == exported.json()["total"]
    assert exported.json()["truncated"] is False


def test_audit_export_rejects_more_than_5000_visible_records(client, auth_headers):
    occurred_at = datetime(2099, 3, 1, 0, 0, 0)
    with SessionLocal() as db:
        db.execute(
            insert(AuditLog),
            [
                {
                    "log_id": f"bulk-audit-{index:04d}",
                    "occurred_at": occurred_at,
                    "actor_user_id": "user-exchange",
                    "actor_org_id": "org-exchange-t01",
                    "actor_name": "交易中心验证员",
                    "action_code": "BULK_AUDIT_EXPORT_LIMIT",
                    "target_type": "SETTLEMENT_TASK",
                    "target_id": "task-ready-t01",
                    "result": "SUCCESS",
                    "trace_id": f"bulk-trace-{index:04d}",
                    "details_json": {},
                }
                for index in range(5001)
            ],
        )
        db.commit()

    response = client.get(
        "/api/trust-space/audit/export?format=json",
        headers=auth_headers["regulator"],
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "AUDIT_EXPORT_LIMIT_EXCEEDED"
    assert response.json()["detail"]["limit"] == 5000
    assert response.json()["detail"]["total"] > 5000

    with SessionLocal() as db:
        export_successes = db.scalar(
            select(AuditLog.log_id).where(
                AuditLog.action_code == "EXPORT_AUDIT_RECORDS",
                AuditLog.result == "SUCCESS",
            )
        )
        assert export_successes is None
