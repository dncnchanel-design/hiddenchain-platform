from concurrent.futures import ThreadPoolExecutor
from threading import Event

from sqlalchemy import select

from app.database import SessionLocal
from app.models import AuditLog, SettlementTask
from app.services import workflow
from app.trust_models import TtcAttempt


def test_second_run_does_not_fail_the_in_progress_attempt(client, auth_headers, monkeypatch):
    """A rejected duplicate must never mutate the worker that owns RUNNING."""
    started, release = Event(), Event()
    original_create = workflow.LocalUsagePolicyAdapter.create_contract

    def paused_create(*args, **kwargs):
        started.set()
        assert release.wait(20), "Timed out waiting for duplicate request"
        return original_create(*args, **kwargs)

    monkeypatch.setattr(workflow.LocalUsagePolicyAdapter, "create_contract", paused_create)
    task_id = "task-ready-t01"
    url = f"/api/settlement/tasks/{task_id}"
    body = {"compute_mode": "LOCAL_CONTROLLED", "algorithm_code": "CONTROLLED_SETTLEMENT_V1"}
    view = client.get(url, headers=auth_headers["exchange"])
    first_headers = {**auth_headers["exchange"], "If-Match": view.headers["etag"]}
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, url + "/run", headers=first_headers, json=body)
        try:
            assert started.wait(20), "First request did not reach the execution gate"
            current = client.get(url, headers=auth_headers["exchange"])
            assert current.json()["status"] == "RUNNING"
            duplicate = client.post(url + "/run", headers={**auth_headers["exchange"], "If-Match": current.headers["etag"]}, json=body)
            with SessionLocal() as db:
                state_after_duplicate = db.get(SettlementTask, task_id).status
                attempt_statuses = list(db.scalars(select(TtcAttempt.status).where(TtcAttempt.task_id == task_id)))
                failed_audits = list(db.scalars(select(AuditLog.log_id).where(AuditLog.target_id == task_id, AuditLog.action_code == "TRUSTED_SETTLEMENT_ATTEMPT_FAILED")))
        finally:
            release.set()
        first = future.result(timeout=30)
    assert (state_after_duplicate, duplicate.status_code) == ("RUNNING", 409)
    assert attempt_statuses == ["ACTIVE"]
    assert failed_audits == []
    assert first.status_code == 200, first.text
    assert first.json()["compute_job"]["status"] == "SUCCESS"
