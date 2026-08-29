from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import (
    AnomalyEvent,
    AuditLog,
    AuditReport,
    MetricRecord,
    NotificationOutbox,
    SettlementTask,
    TaskParticipant,
    User,
    UserNotification,
    utc_now,
)
from app.services import notifications
from app.services.audit_scope import scoped_audit_task
from app.routers.trade import _record_ttc_run_failure
from app.trust_models import TtcAttempt, TtcStateTransition


def test_outbox_is_atomic_retryable_deduplicated_and_dead_letters(monkeypatch):
    rollback_key = "stage4-outbox-rollback"
    retry_key = "stage4-outbox-retry"
    dead_key = "stage4-outbox-dead"

    with SessionLocal() as db:
        db.add(MetricRecord(metric_code="STAGE4_ROLLBACK", metric_value=1, metric_unit="count"))
        assert notifications.publish(
            db,
            notification_type="TEST",
            title="rollback",
            body="rollback",
            dedupe_key=rollback_key,
            user_ids=["user-generator"],
        ) == 1
        db.rollback()
        assert db.scalar(select(func.count(NotificationOutbox.outbox_id)).where(
            NotificationOutbox.dedupe_key == rollback_key
        )) == 0
        assert db.scalar(select(func.count(MetricRecord.metric_id)).where(
            MetricRecord.metric_code == "STAGE4_ROLLBACK"
        )) == 0

        db.add(MetricRecord(metric_code="STAGE4_PERSISTED", metric_value=1, metric_unit="count"))
        assert notifications.publish(
            db,
            notification_type="TEST",
            title="retry",
            body="retry",
            dedupe_key=retry_key,
            user_ids=["user-generator"],
        ) == 1
        db.commit()

        materialize = notifications._materialize_notification

        def fail_materialization(*_args, **_kwargs):
            raise RuntimeError("simulated inbox failure")

        monkeypatch.setattr(notifications, "_materialize_notification", fail_materialization)
        assert notifications.process_notification_outbox(db)["retry"] == 1
        queued = db.scalar(select(NotificationOutbox).where(NotificationOutbox.dedupe_key == retry_key))
        assert queued is not None and queued.status == "RETRY" and queued.attempt_count == 1
        assert db.scalar(select(func.count(MetricRecord.metric_id)).where(
            MetricRecord.metric_code == "STAGE4_PERSISTED"
        )) == 1

        monkeypatch.setattr(notifications, "_materialize_notification", materialize)
        queued.next_attempt_at = utc_now()
        db.commit()
        assert notifications.process_notification_outbox(db)["delivered"] == 1
        assert db.scalar(select(func.count(UserNotification.notification_id)).where(
            UserNotification.user_id == "user-generator",
            UserNotification.dedupe_key == retry_key,
        )) == 1
        assert notifications.publish(
            db,
            notification_type="TEST",
            title="duplicate",
            body="duplicate",
            dedupe_key=retry_key,
            user_ids=["user-generator"],
        ) == 0
        db.commit()
        notifications.process_notification_outbox(db)
        assert db.scalar(select(func.count(UserNotification.notification_id)).where(
            UserNotification.user_id == "user-generator",
            UserNotification.dedupe_key == retry_key,
        )) == 1

        assert notifications.publish(
            db,
            notification_type="TEST",
            title="dead",
            body="dead",
            dedupe_key=dead_key,
            user_ids=["user-generator"],
            task_id="task-ready-t01",
        ) == 1
        dead_item = db.scalar(select(NotificationOutbox).where(NotificationOutbox.dedupe_key == dead_key))
        assert dead_item is not None
        dead_item.max_attempts = 1
        db.commit()
        monkeypatch.setattr(notifications, "_materialize_notification", fail_materialization)
        assert notifications.process_notification_outbox(db)["dead_letter"] == 1
        db.refresh(dead_item)
        assert dead_item.status == "DEAD_LETTER"
        anomaly = db.scalar(select(AnomalyEvent).where(
            AnomalyEvent.dedupe_key == f"notification-dead-letter:{dead_item.outbox_id}"
        ))
        assert anomaly is not None and anomaly.task_id == "task-ready-t01"
        audit = db.scalar(select(AuditLog).where(
            AuditLog.action_code == "NOTIFICATION_OUTBOX_DEAD_LETTER",
            AuditLog.target_id == dead_item.outbox_id,
        ))
        assert audit is not None


def test_audit_report_outbox_freezes_only_task_scoped_recipients():
    with SessionLocal() as db:
        report = AuditReport(
            report_id="stage4-audit-report-recipients",
            task_id="task-history-t01",
            template_code="STAGE4_SCOPE",
            report_title="stage4 scope",
            report_content="scope test",
            report_hash="stage4-scope-hash",
            risk_level="LOW",
            evidence_refs_json=[],
        )
        db.add(report)
        assert notifications.publish_audit_report(db, report) > 0
        db.commit()
        rows = db.scalars(select(NotificationOutbox).where(
            NotificationOutbox.dedupe_key == f"audit-report:{report.report_id}:GENERATED"
        )).all()
        assert rows
        actual = {row.recipient_user_id for row in rows}
        recipients = db.scalars(select(User).where(User.user_id.in_(actual))).all()
        assert all(user.role_code != "ADMIN" for user in recipients)
        task = db.get(SettlementTask, report.task_id)
        assert task is not None
        task_orgs = {
            task.creator_org_id,
            *db.scalars(select(TaskParticipant.org_id).where(TaskParticipant.task_id == task.task_id)).all(),
        }
        expected = set(db.scalars(select(User.user_id).where(
            User.status == "ACTIVE",
            User.org_id.in_(task_orgs),
        )).all())
        expected.update(
            user.user_id
            for user in db.scalars(select(User).where(
                User.status == "ACTIVE",
                User.role_code == "REGULATOR",
            )).all()
            if scoped_audit_task(db, user, report.task_id) is not None
        )
        assert actual == expected


def test_two_outbox_workers_materialize_a_notification_at_most_once():
    dedupe_key = "stage4-outbox-concurrent"
    with SessionLocal() as db:
        assert notifications.publish(
            db,
            notification_type="TEST",
            title="concurrent",
            body="concurrent",
            dedupe_key=dedupe_key,
            user_ids=["user-generator"],
        ) == 1
        db.commit()

    def worker() -> dict[str, int]:
        with SessionLocal() as worker_db:
            return notifications.process_notification_outbox(worker_db)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=10) for future in (pool.submit(worker), pool.submit(worker))]
    assert sum(result["delivered"] for result in results) == 1
    with SessionLocal() as db:
        assert db.scalar(select(func.count(UserNotification.notification_id)).where(
            UserNotification.user_id == "user-generator",
            UserNotification.dedupe_key == dedupe_key,
        )) == 1
        outbox = db.scalar(select(NotificationOutbox).where(NotificationOutbox.dedupe_key == dedupe_key))
        assert outbox is not None and outbox.status == "DELIVERED" and outbox.attempt_count == 1


def test_anomaly_resolution_requires_cas_and_is_replayable_without_task_mutation(client, auth_headers):
    event_id = "stage4-anomaly-cas"
    with SessionLocal() as db:
        task = db.get(SettlementTask, "task-ready-t01")
        assert task is not None
        before = (task.status, task.current_stage, task.risk_level, task.ttc_state)
        db.add(AnomalyEvent(
            event_id=event_id,
            task_id=task.task_id,
            event_type="STAGE4_TEST",
            risk_level="MEDIUM",
            title="CAS test",
            description="CAS test",
        ))
        db.commit()

    url = f"/api/anomalies/{event_id}/resolve"
    assert client.post(url, headers=auth_headers["regulator"], json={"resolution": "ack"}).status_code == 428
    stale = client.post(
        url,
        headers={**auth_headers["regulator"], "If-Match": '"2"', "Idempotency-Key": "stage4-cas"},
        json={"resolution": "ack"},
    )
    assert stale.status_code == 412
    resolved = client.post(
        url,
        headers={**auth_headers["regulator"], "If-Match": '"1"', "Idempotency-Key": "stage4-cas"},
        json={"resolution": "ack"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.headers["etag"] == '"2"'
    assert resolved.json()["idempotent_replay"] is False
    replay = client.post(
        url,
        headers={**auth_headers["regulator"], "If-Match": '"1"', "Idempotency-Key": "stage4-cas"},
        json={"resolution": "ack"},
    )
    assert replay.status_code == 200 and replay.json()["idempotent_replay"] is True
    changed = client.post(
        url,
        headers={**auth_headers["regulator"], "If-Match": '"1"', "Idempotency-Key": "stage4-cas"},
        json={"resolution": "different"},
    )
    assert changed.status_code == 409

    with SessionLocal() as db:
        task = db.get(SettlementTask, "task-ready-t01")
        assert task is not None
        assert (task.status, task.current_stage, task.risk_level, task.ttc_state) == before
        assert db.scalar(select(func.count(AuditLog.log_id)).where(
            AuditLog.action_code == "RESOLVE_ANOMALY",
            AuditLog.target_id == event_id,
        )) == 1


def test_explicit_rework_uses_the_legal_ttc_transition(client, auth_headers):
    event_id = "stage4-anomaly-rework"
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
        before = (task.status, task.current_stage, task.risk_level, task.state_version)
        db.add(AnomalyEvent(
            event_id=event_id,
            task_id=task.task_id,
            event_type="STAGE4_REWORK_TEST",
            risk_level="HIGH",
            title="rework test",
            description="rework test",
        ))
        db.commit()

    response = client.post(
        f"/api/anomalies/{event_id}/resolve",
        headers={
            **auth_headers["regulator"],
            "If-Match": '"1"',
            "Idempotency-Key": "stage4-rework",
        },
        json={"resolution": "进入返工", "disposition": "REWORK"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["transition_id"]
    with SessionLocal() as db:
        task = db.get(SettlementTask, "task-history-t01")
        assert task is not None
        assert task.ttc_state == "REWORK"
        assert (task.status, task.current_stage, task.risk_level) == before[:3]
        assert task.state_version == before[3] + 1
        transition = db.get(TtcStateTransition, response.json()["transition_id"])
        assert transition is not None
        assert (transition.from_state, transition.to_state) == ("FAILED", "REWORK")


def test_formal_settlement_failure_creates_anomaly_and_audit_in_one_commit():
    with SessionLocal() as db:
        user = db.get(User, "user-exchange")
        assert user is not None
        _record_ttc_run_failure(
            db,
            task_id="task-history-t01",
            user=user,
            error=RuntimeError("stage4 formal failure"),
        )
        task = db.get(SettlementTask, "task-history-t01")
        assert task is not None and task.ttc_state in {"FAILED", "REJECTED"}
        anomaly = db.scalar(select(AnomalyEvent).where(
            AnomalyEvent.dedupe_key == f"settlement-failure:{task.task_id}:{task.current_attempt}"
        ))
        assert anomaly is not None
        audit = db.scalar(select(AuditLog).where(
            AuditLog.action_code == "TRUSTED_SETTLEMENT_ATTEMPT_FAILED",
            AuditLog.target_id == task.task_id,
        ))
        assert audit is not None
