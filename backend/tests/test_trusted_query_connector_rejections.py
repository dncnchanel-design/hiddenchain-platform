"""Permanent connector privacy denials must not enter the automatic retry loop."""
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import AuditLog, DataRequestItem, LocalSubjectNode, TrustedQueryTask, utc_now
from app.routers import trusted_query
from test_trusted_query_async import _execute, _prepare_authorization, _query_body


PRIVATE_DETAIL = "upstream-internal-detail-must-not-leak"
PRIVACY_LIMITS = (
    ("相同或近似查询次数已达到隐私保护上限", "REPEATED_QUERY_LIMIT"),
    ("本连接器查询预算已用尽", "CONNECTOR_BUDGET_EXHAUSTED"),
)


def _install_rejection(monkeypatch, response, phase):
    calls = []

    def reject(url, **_kwargs):
        calls.append(url)
        return response

    monkeypatch.setattr(trusted_query.httpx, "get", reject)
    monkeypatch.setattr(trusted_query.httpx, "post", reject)
    if phase == "discovery":
        with SessionLocal() as db:
            node = db.scalar(select(LocalSubjectNode).where(LocalSubjectNode.org_id == "org-generator-t01"))
            node.public_key = None
            db.commit()
    return calls


@pytest.mark.parametrize("phase", ["discovery", "compute"])
@pytest.mark.parametrize("detail,code", PRIVACY_LIMITS)
def test_privacy_rejection_is_terminal_after_one_real_http_task_attempt(client, auth_headers, monkeypatch, phase, detail, code):
    authorization_id, _private_key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    calls = _install_rejection(monkeypatch, httpx.Response(429, json={"detail": detail}), phase)
    accepted = _execute(client, auth_headers["exchange"], body, "terminal-privacy-limit")
    assert accepted.status_code == 202, accepted.text
    task_id = accepted.json()["task_id"]
    for _ in range(2):
        status = client.get(f"/api/trust-space/query/tasks/{task_id}", headers=auth_headers["exchange"])
        assert status.status_code == 200
        assert status.json()["status"] == "FAILED" and status.json()["failure_code"] == code
        assert "隐私" in status.json()["failure_summary"] and "稍后重试" not in status.json()["failure_summary"]
    assert len(calls) == 1 and calls[0].endswith("/health" if phase == "discovery" else "/compute")
    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, task_id)
        item = db.get(DataRequestItem, task.request_item_id)
        assert task.attempt == 1 and task.next_attempt_at is None and task.completed_at is not None
        assert item.status == "FAILED" and item.failure_code == code
        logs = db.scalars(select(AuditLog).where(AuditLog.target_id == task_id)).all()
        assert any(log.action_code == "TRUSTED_QUERY_FAILED" and log.details_json["retryable"] is False for log in logs)
        assert all(log.action_code != "TRUSTED_QUERY_RETRY_SCHEDULED" for log in logs)


@pytest.mark.parametrize("phase", ["discovery", "compute"])
def test_unknown_429_keeps_the_existing_retry_flow(client, auth_headers, monkeypatch, phase):
    authorization_id, _private_key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    calls = _install_rejection(monkeypatch, httpx.Response(429, json={"detail": PRIVATE_DETAIL}), phase)
    accepted = _execute(client, auth_headers["exchange"], body, "ordinary-429")
    task_id = accepted.json()["task_id"]
    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, task_id)
        assert task.status == "PENDING_RETRY" and task.attempt == 1
        assert task.failure_code == ("CONNECTOR_DISCOVERY_UNAVAILABLE" if phase == "discovery" else "CONNECTOR_TEMPORARY_FAILURE")
        assert PRIVATE_DETAIL not in task.failure_summary
        task.next_attempt_at = utc_now() - timedelta(seconds=1)
        db.commit()
    client.get(f"/api/trust-space/query/tasks/{task_id}", headers=auth_headers["exchange"])
    assert len(calls) == 2
    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, task_id)
        assert task.status == "PENDING_RETRY" and task.attempt == 2 and task.next_attempt_at is not None
        assert db.scalar(select(func.count(AuditLog.log_id)).where(
            AuditLog.target_id == task_id, AuditLog.action_code == "TRUSTED_QUERY_RETRY_SCHEDULED",
        )) == 2


@pytest.mark.parametrize("response,code,retryable", [
    (httpx.Response(429, json={"detail": {"code": "REPEATED_QUERY_LIMIT", "message": PRIVATE_DETAIL}}), "REPEATED_QUERY_LIMIT", False),
    (httpx.Response(429, json={"error_code": "CONNECTOR_BUDGET_EXHAUSTED", "detail": PRIVATE_DETAIL}), "CONNECTOR_BUDGET_EXHAUSTED", False),
    (httpx.Response(429, json={"detail": {"code": "UNREGISTERED_PRIVACY_LIMIT", "message": PRIVACY_LIMITS[0][0]}}), "CONNECTOR_DISCOVERY_UNAVAILABLE", True),
    (httpx.Response(429, json={"detail": {"code": ["REPEATED_QUERY_LIMIT"]}}), "CONNECTOR_DISCOVERY_UNAVAILABLE", True),
    (httpx.Response(429, content=b"<html>upstream-internal-detail-must-not-leak</html>"), "CONNECTOR_DISCOVERY_UNAVAILABLE", True),
    (httpx.Response(429, json=["REPEATED_QUERY_LIMIT"]), "CONNECTOR_DISCOVERY_UNAVAILABLE", True),
    (httpx.Response(408, json={"detail": PRIVATE_DETAIL}), "CONNECTOR_DISCOVERY_UNAVAILABLE", True),
    (httpx.Response(425, json={"detail": PRIVATE_DETAIL}), "CONNECTOR_DISCOVERY_UNAVAILABLE", True),
    (httpx.Response(500, json={"detail": PRIVACY_LIMITS[0][0]}), "CONNECTOR_DISCOVERY_UNAVAILABLE", True),
    (httpx.Response(503, content=b"invalid json"), "CONNECTOR_DISCOVERY_UNAVAILABLE", True),
    (httpx.Response(400, json={"detail": PRIVATE_DETAIL}), "CONNECTOR_DISCOVERY_REJECTED", False),
    (httpx.Response(401, json={"detail": PRIVATE_DETAIL}), "CONNECTOR_DISCOVERY_REJECTED", False),
    (httpx.Response(403, json={"detail": PRIVATE_DETAIL}), "CONNECTOR_DISCOVERY_REJECTED", False),
])
def test_discovery_classifies_only_allowlisted_429_details_and_keeps_other_statuses(monkeypatch, response, code, retryable):
    monkeypatch.setattr(trusted_query.httpx, "get", lambda *_args, **_kwargs: response)
    with pytest.raises(trusted_query.TrustedQueryExecutionError) as caught:
        trusted_query._discover_connector_public_key(endpoint="https://connector.example", node={},
                                                     provider_org_id="org-generator-t01", energy_domain="electricity")
    assert caught.value.code == code and caught.value.retryable is retryable
    assert PRIVATE_DETAIL not in caught.value.summary and "<html>" not in caught.value.summary
    compute_error = trusted_query._connector_response_error(response)
    compute_code = code if code in {"REPEATED_QUERY_LIMIT", "CONNECTOR_BUDGET_EXHAUSTED"} else (
        "CONNECTOR_TEMPORARY_FAILURE" if retryable else "CONNECTOR_REQUEST_REJECTED"
    )
    assert compute_error.code == compute_code and compute_error.retryable is retryable
    assert PRIVATE_DETAIL not in compute_error.summary and "<html>" not in compute_error.summary
