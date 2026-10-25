"""On-demand transient recovery must retain pinned trust and one query identity."""
import logging
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import DataUsageRequest, ExecutionReceipt, LocalSubjectNode, PrivacyComputeJob, TrustedQueryTask, utc_now
from app.routers import trusted_query
from test_trusted_query_async import _execute, _prepare_authorization, _public_key, _query_body, _signed_connector_response


def _clock(monkeypatch, budget=12):
    clock = SimpleNamespace(now=0.0, sleeps=[])
    def sleep(seconds):
        assert 0 < seconds <= budget
        clock.sleeps.append(seconds)
        clock.now += seconds
    monkeypatch.setattr(trusted_query, "time", SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep), raising=False)
    monkeypatch.setattr(trusted_query, "settings", replace(trusted_query.settings, connector_timeout_seconds=budget))
    return clock


def _health(private_key, **changes):
    return {"connector_id": "local-node-org-generator-t01", "organization_id": "org-generator-t01",
            "energy_domain": "electricity", "public_key": _public_key(private_key), **changes}


def _pending_then_retry(client, auth_headers, task_id):
    with SessionLocal() as db:
        pending = db.get(TrustedQueryTask, task_id)
        assert pending.status == "PENDING_RETRY" and pending.attempt == 1
        pending.next_attempt_at = utc_now() - timedelta(seconds=1)
        db.commit()
    client.get(f"/api/trust-space/query/tasks/{task_id}", headers=auth_headers["exchange"])


def test_cached_key_transient_post_waits_for_matching_health_then_retries_same_query(client, auth_headers, monkeypatch):
    authorization_id, key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    clock = _clock(monkeypatch)
    posts, gets, nonces = [], [], []
    heartbeats = []
    heartbeat = trusted_query._heartbeat_query_task
    def record_heartbeat(db, **kwargs):
        heartbeats.append(clock.now)
        return heartbeat(db, **kwargs)
    monkeypatch.setattr(trusted_query, "_heartbeat_query_task", record_heartbeat)
    def post(url, *, json, headers, timeout):
        posts.append(json)
        nonces.append(headers["X-Request-Nonce"])
        if len(posts) == 1:
            return httpx.Response(429, content=b"upstream rate limit", headers={"Retry-After": "2"})
        return _signed_connector_response(json, key)
    def get(url, *, timeout):
        gets.append((url, timeout, clock.now))
        if len(gets) == 1:
            return httpx.Response(503, content=b"not yet ready")
        return httpx.Response(200, json=_health(key))
    monkeypatch.setattr(trusted_query.httpx, "post", post)
    monkeypatch.setattr(trusted_query.httpx, "get", get)
    accepted = _execute(client, auth_headers["exchange"], body, "cached-cold-start")
    assert accepted.status_code == 202
    assert len(posts) == 1 and gets == [] and clock.sleeps == []
    clock.now = 2
    _pending_then_retry(client, auth_headers, accepted.json()["task_id"])
    assert len(posts) == 2 and posts[0] == posts[1] and nonces[0] != nonces[1]
    assert len(gets) == 2 and gets[0][2] >= 2 and clock.sleeps
    assert heartbeats[:2] == [0, 2] and heartbeats[-1] == clock.now > 2, "Long readiness waits need lease renewal before and after"
    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, accepted.json()["task_id"])
        assert task.status == "SUCCEEDED" and task.attempt == 2
        node = db.scalar(select(LocalSubjectNode).where(LocalSubjectNode.org_id == "org-generator-t01"))
        assert node.public_key == _public_key(key)
        assert db.scalar(select(func.count(ExecutionReceipt.receipt_id)).where(ExecutionReceipt.task_id == task.task_id)) == 1


@pytest.mark.parametrize("changed", ["public_key", "organization_id", "connector_id", "energy_domain"])
def test_recovery_never_replaces_a_pinned_key_or_accepts_another_subject(client, auth_headers, monkeypatch, changed):
    authorization_id, key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    _clock(monkeypatch)
    posts, gets = [], []
    wrong = _public_key(Ed25519PrivateKey.generate()) if changed == "public_key" else "another-subject"
    def post(url, **kwargs):
        posts.append(url)
        return httpx.Response(503, content=b"temporarily unavailable")
    def get(url, **kwargs):
        gets.append(url)
        return httpx.Response(200, json=_health(key, **{changed: wrong}))
    monkeypatch.setattr(trusted_query.httpx, "post", post)
    monkeypatch.setattr(trusted_query.httpx, "get", get)
    accepted = _execute(client, auth_headers["exchange"], body, "pinned-identity-" + changed)
    assert len(posts) == 1 and gets == []
    _pending_then_retry(client, auth_headers, accepted.json()["task_id"])
    assert len(posts) == len(gets) == 1
    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, accepted.json()["task_id"])
        assert task.status == "FAILED" and task.failure_code == "CONNECTOR_IDENTITY_MISMATCH"
        assert task.attempt == 2 and task.next_attempt_at is None
        node = db.scalar(select(LocalSubjectNode).where(LocalSubjectNode.org_id == "org-generator-t01"))
        assert node.public_key == _public_key(key)
        assert db.scalar(select(func.count(PrivacyComputeJob.job_id)).where(PrivacyComputeJob.task_id == task.task_id)) == 0
    client.get(f"/api/trust-space/query/tasks/{accepted.json()['task_id']}", headers=auth_headers["exchange"])
    assert len(posts) == 1


@pytest.mark.parametrize("detail,code", [("相同或近似查询次数已达到隐私保护上限", "REPEATED_QUERY_LIMIT"),
                                      ({"code": "CONNECTOR_BUDGET_EXHAUSTED"}, "CONNECTOR_BUDGET_EXHAUSTED")])
def test_known_privacy_limits_never_wait_or_probe_health(client, auth_headers, monkeypatch, detail, code):
    authorization_id, _key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    clock = _clock(monkeypatch)
    posts = []
    monkeypatch.setattr(trusted_query.httpx, "post", lambda url, **kwargs: posts.append(url) or httpx.Response(429, json={"detail": detail}, headers={"Retry-After": "9"}))
    monkeypatch.setattr(trusted_query.httpx, "get", lambda *args, **kwargs: pytest.fail("Privacy denial triggered a readiness probe"))
    accepted = _execute(client, auth_headers["exchange"], body, "privacy-no-warm-" + code)
    assert len(posts) == 1 and clock.sleeps == []
    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, accepted.json()["task_id"])
        assert task.status == "FAILED" and task.failure_code == code and task.next_attempt_at is None


def test_readiness_honors_retry_after_without_hot_loop_and_returns_unspent_delay(monkeypatch):
    clock = _clock(monkeypatch, budget=6)
    key = Ed25519PrivateKey.generate()
    calls = []
    def get(url, *, timeout):
        calls.append((clock.now, timeout))
        return httpx.Response(429, content=b"edge limit", headers={"Retry-After": "10"})
    monkeypatch.setattr(trusted_query.httpx, "get", get)
    with pytest.raises(trusted_query.TrustedQueryExecutionError) as error:
        trusted_query._wait_for_connector_readiness(endpoint="https://connector.example", node={"node_code": "local-node-org-generator-t01"},
            provider_org_id="org-generator-t01", energy_domain="electricity", expected_public_key=_public_key(key))
    assert calls == [(0, 6)] and clock.now == 6 and clock.sleeps == [6]
    assert error.value.retry_delay_seconds == 4, "The remaining server rate-limit delay must survive into the durable retry"


def test_readiness_transport_timeout_is_bounded_by_one_total_deadline(monkeypatch):
    clock = _clock(monkeypatch, budget=6)
    calls = []
    def get(url, *, timeout):
        calls.append(timeout)
        clock.now += timeout
        raise httpx.ReadTimeout("node did not start", request=httpx.Request("GET", url))
    monkeypatch.setattr(trusted_query.httpx, "get", get)
    with pytest.raises(trusted_query.TrustedQueryExecutionError) as error:
        trusted_query._wait_for_connector_readiness(endpoint="https://connector.example", node={"node_code": "local-node-org-generator-t01"},
            provider_org_id="org-generator-t01", energy_domain="electricity", expected_public_key=_public_key(Ed25519PrivateKey.generate()))
    assert clock.now == 6 and calls == [6] and clock.sleeps == [] and error.value.retry_delay_seconds is None


def test_full_window_retry_after_still_probes_health_after_hint_before_next_compute(client, auth_headers, monkeypatch):
    authorization_id, key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    clock = _clock(monkeypatch, budget=6)
    posts, gets = [], []
    response = httpx.Response(429, content=b"upstream limit", headers={"Retry-After": "60"})
    assert trusted_query._connector_response_error(response).retry_delay_seconds == 60
    assert trusted_query._connector_response_error(httpx.Response(429, headers={"Retry-After": "120"})).retry_delay_seconds == 60
    def post(url, *, json, **kwargs):
        posts.append((url, clock.now))
        return response if len(posts) == 1 else _signed_connector_response(json, key)
    def get(url, **kwargs):
        assert clock.now >= 60 and len(posts) == 1, "Never probe before Retry-After or compute before readiness"
        gets.append((url, clock.now))
        return httpx.Response(200, json=_health(key))
    monkeypatch.setattr(trusted_query.httpx, "post", post)
    monkeypatch.setattr(trusted_query.httpx, "get", get)
    accepted = _execute(client, auth_headers["exchange"], body, "bounded-server-retry-hint")
    assert clock.now == 0 and clock.sleeps == [] and len(posts) == 1 and gets == []
    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, accepted.json()["task_id"])
        assert task.status == "PENDING_RETRY" and task.attempt == 1 and task.lease_owner is None
        assert task.failure_code == "CONNECTOR_TEMPORARY_FAILURE"
        assert 59 <= (task.next_attempt_at - utc_now()).total_seconds() <= 61
    client.get(f"/api/trust-space/query/tasks/{accepted.json()['task_id']}", headers=auth_headers["exchange"])
    assert len(posts) == 1, "Polling before Retry-After expires must not create another attempt"
    clock.now = 60
    _pending_then_retry(client, auth_headers, accepted.json()["task_id"])
    assert len(gets) == 1 and len(posts) == 2 and posts[1][1] >= 60
    with SessionLocal() as db:
        assert db.get(TrustedQueryTask, accepted.json()["task_id"]).status == "SUCCEEDED"


def test_lost_compute_response_reuses_one_connector_budget_receipt(client, auth_headers, monkeypatch):
    authorization_id, key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    _clock(monkeypatch)
    calls, receipts = [], {}
    def post(url, *, json, **kwargs):
        calls.append(json)
        if json["request_item_id"] not in receipts:
            receipts[json["request_item_id"]] = _signed_connector_response(json, key)
            raise httpx.ReadTimeout("response lost after one real execution", request=httpx.Request("POST", url))
        return receipts[json["request_item_id"]]
    monkeypatch.setattr(trusted_query.httpx, "post", post)
    health_calls = []
    monkeypatch.setattr(trusted_query.httpx, "get", lambda url, **kwargs: health_calls.append(url) or httpx.Response(200, json=_health(key)))
    accepted = _execute(client, auth_headers["exchange"], body, "lost-one-budget-receipt")
    assert health_calls == []
    _pending_then_retry(client, auth_headers, accepted.json()["task_id"])
    assert len(health_calls) == 1 and len(calls) == 2 and calls[0] == calls[1] and len(receipts) == 1
    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, accepted.json()["task_id"])
        assert task.status == "SUCCEEDED" and task.attempt == 2
        assert db.scalar(select(func.count(ExecutionReceipt.receipt_id)).where(ExecutionReceipt.task_id == task.task_id)) == 1


def test_authorization_revoked_during_readiness_cannot_reach_another_compute(client, auth_headers, monkeypatch):
    authorization_id, key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    _clock(monkeypatch)
    posts = []
    monkeypatch.setattr(trusted_query.httpx, "post", lambda url, **kwargs: posts.append(url) or httpx.Response(429, content=b"edge limit"))
    def get(url, **kwargs):
        with SessionLocal() as db:
            db.get(DataUsageRequest, authorization_id).status = "REVOKED"
            db.commit()
        return httpx.Response(200, json=_health(key))
    monkeypatch.setattr(trusted_query.httpx, "get", get)
    accepted = _execute(client, auth_headers["exchange"], body, "revoke-during-readiness")
    _pending_then_retry(client, auth_headers, accepted.json()["task_id"])
    assert len(posts) == 1, "A previously approved grant must be refreshed after a readiness wait"
    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, accepted.json()["task_id"])
        assert task.status == "FAILED" and task.failure_code == "AUTHORIZATION_REVOKED"
        assert task.attempt == 2 and task.next_attempt_at is None
        assert db.scalar(select(func.count(ExecutionReceipt.receipt_id)).where(ExecutionReceipt.task_id == task.task_id)) == 0


def test_production_readiness_may_compare_a_registered_key_but_never_bootstrap_one(monkeypatch):
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(trusted_query, "settings", replace(trusted_query.settings, app_env="production"))
    calls = []
    monkeypatch.setattr(trusted_query.httpx, "get", lambda url, **kwargs: calls.append(url) or httpx.Response(200, json=_health(key)))
    arguments = {"endpoint": "https://connector.example", "node": {"node_code": "local-node-org-generator-t01"},
                 "provider_org_id": "org-generator-t01", "energy_domain": "electricity"}
    with pytest.raises(trusted_query.TrustedQueryExecutionError) as error:
        trusted_query._discover_connector_public_key(**arguments)
    assert error.value.code == "CONNECTOR_KEY_NOT_REGISTERED" and calls == []
    assert trusted_query._discover_connector_public_key(**arguments, expected_public_key=_public_key(key)) == _public_key(key)
    assert len(calls) == 1
    with pytest.raises(trusted_query.TrustedQueryExecutionError) as insecure:
        trusted_query._discover_connector_public_key(**{**arguments, "endpoint": "http://connector.example"}, expected_public_key=_public_key(key))
    assert insecure.value.code == "CONNECTOR_DISCOVERY_ENDPOINT_INVALID" and len(calls) == 1


def test_readiness_cannot_establish_a_new_key_even_in_demo(monkeypatch):
    monkeypatch.setattr(trusted_query.httpx, "get", lambda *args, **kwargs: pytest.fail("Readiness cannot bootstrap a key"))
    with pytest.raises(trusted_query.TrustedQueryExecutionError) as error:
        trusted_query._wait_for_connector_readiness(endpoint="https://connector.example", node={"node_code": "local-node-org-generator-t01"},
            provider_org_id="org-generator-t01", energy_domain="electricity", expected_public_key="")
    assert error.value.code == "CONNECTOR_KEY_NOT_REGISTERED" and error.value.retryable is False


@pytest.mark.parametrize("status,media_type,category,code", [
    (429, "text/plain; private=header-secret", "other", "CONNECTOR_DISCOVERY_UNAVAILABLE"),
    (200, "text/html; private=header-secret", "html", "CONNECTOR_IDENTITY_INVALID"),
])
def test_readiness_response_diagnostics_include_only_metadata(monkeypatch, caplog, status, media_type, category, code):
    monkeypatch.setattr(trusted_query.httpx, "get", lambda *args, **kwargs: httpx.Response(
        status, content=b"private-body-secret", headers={"Content-Type": media_type, "X-Private": "private-header-secret"},
    ))
    caplog.set_level(logging.WARNING, logger=trusted_query.__name__)
    with pytest.raises(trusted_query.TrustedQueryExecutionError) as error:
        trusted_query._discover_connector_public_key(
            endpoint="https://connector.example/private-path?secret=query-secret#fragment-secret",
            node={"node_code": "local-node-org-generator-t01"}, provider_org_id="org-generator-t01", energy_domain="electricity",
            expected_public_key=_public_key(Ed25519PrivateKey.generate()),
        )
    assert error.value.code == code
    assert [record.getMessage() for record in caplog.records if record.name == trusted_query.__name__] == [
        f"trusted_query_connector_readiness_response provider_org_id=org-generator-t01 endpoint_host=connector.example http_status={status} content_category={category}"
    ]


@pytest.mark.parametrize("hint", ["garbage", "-3", "nan", "1e9", "0", "9" * 50])
def test_unsafe_retry_after_values_do_not_control_waits_or_escape_into_errors(monkeypatch, hint):
    _clock(monkeypatch, budget=6)
    error = trusted_query._connector_response_error(httpx.Response(429, content=b"private body", headers={"Retry-After": hint}))
    assert error.code == "CONNECTOR_TEMPORARY_FAILURE" and error.retryable is True
    assert error.retry_delay_seconds is None and hint not in error.summary and "private body" not in error.summary
