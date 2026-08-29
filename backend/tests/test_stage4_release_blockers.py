from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.database import SessionLocal
from app.models import (
    AnomalyEvent,
    AuditReport,
    BlockchainEvidence,
    NotificationOutbox,
    SettlementTask,
    User,
    UserNotification,
    utc_now,
)
from app.routers import audit as audit_router
from app.security import create_access_token, hash_password
from app.services import notifications
from app.services.adapters import LocalEvidenceLedgerAdapter
from app.services.trust_domain import TrustDomainError
from app.trust_models import TtcAttempt


def _auth(user_id: str, role: str, org_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id, role, org_id)}"}


def test_regulator_evidence_verification_requires_permission_and_task_scope(client):
    with SessionLocal() as db:
        db.add_all(
            [
                User(
                    user_id="regulator-no-audit",
                    org_id="org-regulator-t01",
                    username="regulator_no_audit",
                    password_hash=hash_password("unused"),
                    display_name="无审计权限监管员",
                    role_code="REGULATOR",
                    permissions_json=[],
                ),
                User(
                    user_id="regulator-no-task-scope",
                    org_id="org-regulator-t01",
                    username="regulator_no_task_scope",
                    password_hash=hash_password("unused"),
                    display_name="无任务范围监管员",
                    role_code="REGULATOR",
                    permissions_json=["VIEW_AUDIT"],
                ),
                User(
                    user_id="regulator-task-scope",
                    org_id="org-regulator-t01",
                    username="regulator_task_scope",
                    password_hash=hash_password("unused"),
                    display_name="任务范围监管员",
                    role_code="REGULATOR",
                    permissions_json=["VIEW_AUDIT", "VIEW_AUDIT:TASK:task-ready-t01"],
                ),
            ]
        )
        evidence = LocalEvidenceLedgerAdapter().anchor(
            db,
            task_id="task-ready-t01",
            stage="STAGE4_SCOPE",
            biz_type="STAGE4_SCOPE",
            biz_id="stage4-evidence-scope",
            payload={"scope": "task-ready-t01"},
        )
        db.commit()
        evidence_id = evidence.evidence_id

    url = f"/api/trust-space/evidence/{evidence_id}/verify"
    assert client.get(
        url,
        headers=_auth("regulator-no-audit", "REGULATOR", "org-regulator-t01"),
    ).status_code == 403
    assert client.get(
        url,
        headers=_auth("regulator-no-task-scope", "REGULATOR", "org-regulator-t01"),
    ).status_code == 404
    allowed = client.get(
        url,
        headers=_auth("regulator-task-scope", "REGULATOR", "org-regulator-t01"),
    )
    assert allowed.status_code == 200 and allowed.json()["matched"] is True


def test_notification_recipient_resolution_never_targets_admin_users():
    with SessionLocal() as db:
        db.add(
            User(
                user_id="admin-inside-business-org",
                org_id="org-generator-t01",
                username="admin_inside_business_org",
                password_hash=hash_password("unused"),
                display_name="业务组织平台运维",
                role_code="ADMIN",
                permissions_json=[],
            )
        )
        db.commit()
        created = notifications.publish(
            db,
            notification_type="STAGE4_ADMIN_BOUNDARY",
            title="组织业务标题",
            body="组织业务正文",
            entity_type="SETTLEMENT_TASK",
            entity_id="task-ready-t01",
            dedupe_key="stage4-admin-boundary",
            org_ids=["org-generator-t01"],
            user_ids=["admin-inside-business-org"],
        )
        db.commit()
        assert created >= 1
        assert db.scalar(select(func.count(NotificationOutbox.outbox_id)).where(
            NotificationOutbox.dedupe_key == "stage4-admin-boundary",
            NotificationOutbox.recipient_user_id == "admin-inside-business-org",
        )) == 0


@pytest.mark.parametrize("materialization_fails", [False, True])
def test_stale_outbox_worker_cannot_overwrite_a_reassigned_lease(
    monkeypatch,
    materialization_fails: bool,
):
    dedupe_key = f"stage4-stale-worker-{materialization_fails}"
    takeover_owner = "notification-new-owner"
    with SessionLocal() as db:
        assert notifications.publish(
            db,
            notification_type="STAGE4_LEASE",
            title="lease",
            body="lease",
            dedupe_key=dedupe_key,
            user_ids=["user-generator"],
        ) == 1
        db.commit()

    original_materialize = notifications._materialize_notification

    def take_over_then_finish(worker_db, item):
        with SessionLocal() as takeover_db:
            takeover_db.execute(
                update(NotificationOutbox)
                .where(NotificationOutbox.outbox_id == item.outbox_id)
                .values(
                    status="PROCESSING",
                    lease_owner=takeover_owner,
                    lease_expires_at=utc_now() + timedelta(minutes=5),
                )
            )
            takeover_db.commit()
        if materialization_fails:
            raise RuntimeError("old worker failed after lease takeover")
        original_materialize(worker_db, item)

    monkeypatch.setattr(notifications, "_materialize_notification", take_over_then_finish)
    with SessionLocal() as db:
        result = notifications.process_notification_outbox(db)
    assert result == {"delivered": 0, "retry": 0, "dead_letter": 0}
    with SessionLocal() as db:
        item = db.scalar(select(NotificationOutbox).where(NotificationOutbox.dedupe_key == dedupe_key))
        assert item is not None
        assert item.status == "PROCESSING"
        assert item.lease_owner == takeover_owner
        assert item.lease_expires_at is not None and item.lease_expires_at > utc_now()
        assert db.scalar(select(func.count(UserNotification.notification_id)).where(
            UserNotification.dedupe_key == dedupe_key
        )) == 0


def test_legacy_audit_reads_are_bounded_and_hide_persistence_only_fields(client, auth_headers):
    with SessionLocal() as db:
        task = db.get(SettlementTask, "task-history-t01")
        assert task is not None
        attempt = db.scalar(select(TtcAttempt).where(
            TtcAttempt.task_id == task.task_id,
            TtcAttempt.attempt_no == task.current_attempt,
        ))
        assert attempt is not None
        db.add(AuditReport(
            report_id="stage4-dto-report",
            task_id=task.task_id,
            attempt_id=attempt.attempt_id,
            template_code="STAGE4_DTO",
            report_title="字段白名单报告",
            report_content="可审计业务内容",
            report_hash="a" * 64,
            risk_level="LOW",
            evidence_refs_json=[],
        ))
        db.add_all([
            AnomalyEvent(
                event_id=f"stage4-bounded-anomaly-{index:03d}",
                task_id=task.task_id,
                event_type="STAGE4_BOUNDED",
                risk_level="LOW",
                title=f"bounded {index}",
                description="bounded pagination",
                evidence_json={"payload_json": "must-not-leak"},
                resolution_idempotency_key="must-not-leak",
                resolution_fingerprint="must-not-leak",
                resolution_response_json={"secret": "must-not-leak"},
            )
            for index in range(105)
        ])
        evidence = LocalEvidenceLedgerAdapter().anchor(
            db,
            task_id=task.task_id,
            stage="STAGE4_DTO",
            biz_type="STAGE4_DTO",
            biz_id="stage4-dto-evidence",
            payload={"payload_json": "must-not-leak"},
        )
        db.commit()
        evidence_id = evidence.evidence_id

    anomalies = client.get(
        "/api/anomalies?page=1&page_size=10",
        headers=auth_headers["regulator"],
    )
    assert anomalies.status_code == 200, anomalies.text
    assert len(anomalies.json()) == 10
    second_page = client.get(
        "/api/anomalies?page=2&page_size=10",
        headers=auth_headers["regulator"],
    )
    assert second_page.status_code == 200 and len(second_page.json()) == 10
    assert {item["event_id"] for item in anomalies.json()}.isdisjoint(
        {item["event_id"] for item in second_page.json()}
    )
    forbidden_anomaly_fields = {
        "evidence_json",
        "resolution_idempotency_key",
        "resolution_fingerprint",
        "resolution_response_json",
        "dedupe_key",
    }
    assert forbidden_anomaly_fields.isdisjoint(anomalies.json()[0])

    reports = client.get(
        "/api/audit/reports?page=1&page_size=1",
        headers=auth_headers["regulator"],
    )
    assert reports.status_code == 200 and len(reports.json()) == 1
    assert set(reports.json()[0]) == {
        "report_id", "task_id", "attempt_id", "template_code", "report_title",
        "report_content", "report_hash", "risk_level", "evidence_refs_json",
        "status", "created_at", "updated_at",
    }

    timeline = client.get(
        "/api/audit/timeline/task-history-t01?page=1&page_size=100",
        headers=auth_headers["regulator"],
    )
    assert timeline.status_code == 200, timeline.text
    body = timeline.json()
    assert len(body["events"]) <= 100
    assert body["pagination"]["page_size"] == 100
    assert {
        "request_idempotency_key", "request_fingerprint", "verification_profile_json",
        "execution_snapshot_id", "execution_snapshot_hash",
    }.isdisjoint(body["task"])
    timeline_page_two = client.get(
        "/api/audit/timeline/task-history-t01?page=2&page_size=100",
        headers=auth_headers["regulator"],
    )
    assert timeline_page_two.status_code == 200, timeline_page_two.text
    matching_evidence = [
        item
        for page_body in (body, timeline_page_two.json())
        for item in page_body["evidence_records"]
        if item["evidence_id"] == evidence_id
    ]
    assert len(matching_evidence) == 1
    assert "payload_json" not in matching_evidence[0]
    assert client.get(
        "/api/anomalies?page_size=101",
        headers=auth_headers["regulator"],
    ).status_code == 422
    assert client.get(
        "/api/audit/reports?page_size=101",
        headers=auth_headers["regulator"],
    ).status_code == 422
    assert client.get(
        "/api/audit/timeline/task-history-t01?page_size=101",
        headers=auth_headers["regulator"],
    ).status_code == 422


def test_anomaly_resolution_rejects_oversized_idempotency_key(client, auth_headers):
    event_id = "stage4-oversized-idempotency"
    with SessionLocal() as db:
        db.add(AnomalyEvent(
            event_id=event_id,
            task_id="task-ready-t01",
            event_type="STAGE4_OVERSIZED_KEY",
            risk_level="LOW",
            title="oversized key",
            description="oversized key",
        ))
        db.commit()

    response = client.post(
        f"/api/anomalies/{event_id}/resolve",
        headers={
            **auth_headers["regulator"],
            "If-Match": '"1"',
            "Idempotency-Key": "k" * 161,
        },
        json={"resolution": "ack"},
    )
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        event = db.get(AnomalyEvent, event_id)
        assert event is not None and event.status == "OPEN" and event.resolution_idempotency_key is None


def test_rework_transition_conflict_is_409_and_rolls_back_transaction(
    client,
    auth_headers,
    monkeypatch,
):
    event_id = "stage4-rework-conflict"
    with SessionLocal() as db:
        task = db.get(SettlementTask, "task-history-t01")
        assert task is not None
        attempt = db.scalar(select(TtcAttempt).where(
            TtcAttempt.task_id == task.task_id,
            TtcAttempt.attempt_no == task.current_attempt,
        ))
        assert attempt is not None
        task.ttc_state = "FAILED"
        attempt.current_state = "FAILED"
        attempt.status = "FAILED"
        db.add(AnomalyEvent(
            event_id=event_id,
            task_id=task.task_id,
            event_type="STAGE4_REWORK_CONFLICT",
            risk_level="HIGH",
            title="rework conflict",
            description="rework conflict",
        ))
        db.commit()

    def conflicting_transition(db, task, *_args, **_kwargs):
        task.ttc_state = "REWORK"
        db.flush()
        raise TrustDomainError("TTC_CONCURRENT_TRANSITION", "状态已被并发更新")

    monkeypatch.setattr(audit_router.TtcStateMachine, "transition", conflicting_transition)
    response = client.post(
        f"/api/anomalies/{event_id}/resolve",
        headers={
            **auth_headers["regulator"],
            "If-Match": '"1"',
            "Idempotency-Key": "stage4-rework-conflict",
        },
        json={"resolution": "进入返工", "disposition": "REWORK"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "TTC_CONCURRENT_TRANSITION"
    with SessionLocal() as db:
        task = db.get(SettlementTask, "task-history-t01")
        event = db.get(AnomalyEvent, event_id)
        assert task is not None and task.ttc_state == "FAILED"
        assert event is not None and event.status == "OPEN" and event.state_version == 1
