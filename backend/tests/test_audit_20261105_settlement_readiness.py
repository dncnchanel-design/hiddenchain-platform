import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import SettlementIdentityLock, SettlementTask, TaskParticipant
from app.services.settlement_guard import reserve_settlement_identity


def _payload(name):
    return {
        "task_name": name,
        "trade_batch_no": "TB-2026-07-T01",
        "period_start": "2026-07-01",
        "period_end": "2026-07-31",
        "rule_id": "rule-settlement-v1",
        "participants": [
            {"org_id": "org-generator-t01", "role_in_task": "GENERATOR"},
            {"org_id": "org-retailer-t01", "role_in_task": "RETAILER"},
        ],
    }


def _persisted_state():
    with SessionLocal() as db:
        return (
            list(db.execute(select(SettlementIdentityLock.identity_hash, SettlementIdentityLock.task_id).order_by(SettlementIdentityLock.identity_hash))),
            list(db.execute(select(SettlementTask.task_id, SettlementTask.status, SettlementTask.state_version).order_by(SettlementTask.task_id))),
        )


@pytest.mark.parametrize("historical", [False, True])
def test_duplicate_is_blocked_in_readiness_without_reserving_an_identity(client, auth_headers, historical):
    with SessionLocal() as db:
        task = db.get(SettlementTask, "task-ready-t01")
        if historical:
            task.status = "AUDITED"
        else:
            participants = list(db.scalars(select(TaskParticipant).where(TaskParticipant.task_id == task.task_id)))
            reserve_settlement_identity(db, task, participants)
        db.commit()

    created = client.post("/api/settlement/tasks", headers=auth_headers["exchange"], json=_payload(f"重复预检-{historical}"))
    assert created.status_code == 201, created.text
    task_id = created.json()["task_id"]
    before_reads = _persisted_state()
    for detail in (created, client.get(f"/api/settlement/tasks/{task_id}", headers=auth_headers["exchange"])):
        payload = detail.json()
        assert not payload["readiness"]["preflight_passed"], payload["readiness"]
        expected = "历史执行记录" if historical else "请勿重复结算"
        assert any(expected in reason for reason in payload["readiness"]["preflight_blockers"])
        assert "RUN_SETTLEMENT" not in payload["allowed_actions"]
        assert payload["next_action"]["blocked"] is True
        assert any(expected in reason for reason in payload["next_action"]["reasons"])
    assert _persisted_state() == before_reads
    with SessionLocal() as db:
        assert db.scalar(select(SettlementIdentityLock).where(SettlementIdentityLock.task_id == task_id)) is None


def test_own_reservation_does_not_block_failed_task_retry_readiness(client, auth_headers):
    with SessionLocal() as db:
        task = db.get(SettlementTask, "task-ready-t01")
        participants = list(db.scalars(select(TaskParticipant).where(TaskParticipant.task_id == task.task_id)))
        reserve_settlement_identity(db, task, participants)
        task.status = "EXCEPTION"
        db.commit()
    before = _persisted_state()
    response = client.get("/api/settlement/tasks/task-ready-t01", headers=auth_headers["exchange"])
    assert response.status_code == 200
    assert response.json()["readiness"]["preflight_passed"] is True
    assert "RUN_SETTLEMENT" in response.json()["allowed_actions"]
    assert _persisted_state() == before
