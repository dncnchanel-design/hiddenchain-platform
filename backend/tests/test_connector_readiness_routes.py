"""Descriptors follow existing dashboard and durable query authorization scope."""
from dataclasses import replace
from datetime import timedelta
import json

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import DataUsageRequest, LocalSubjectNode, TrustedQueryTask, User, utc_now
from app.routers import prototype, trusted_query
from app.services import connector_readiness
from test_trusted_query_async import _execute, _prepare_authorization, _query_body


@pytest.fixture
def configured(monkeypatch):
    endpoints = {"org-generator-t01": "https://generator-browser.example", "org-retailer-t01": "https://retailer-browser.example"}
    monkeypatch.setattr(connector_readiness, "settings", replace(connector_readiness.settings,
        subject_node_browser_endpoints_json=json.dumps(endpoints)))
    monkeypatch.setattr(trusted_query, "run_trusted_query_task", lambda _task_id: None)
    monkeypatch.setattr(trusted_query.httpx, "get", lambda *_args, **_kwargs: pytest.fail("Readiness descriptors never contact nodes"))
    monkeypatch.setattr(trusted_query.httpx, "post", lambda *_args, **_kwargs: pytest.fail("Readiness descriptors never perform calculations"))
    return endpoints


def _queued_task(client, auth_headers):
    authorization_id, _key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    accepted = _execute(client, auth_headers["exchange"], body, "browser-readiness-scoped")
    assert accepted.status_code == 202
    return accepted.json()["task_id"], authorization_id


@pytest.mark.parametrize("state", ["QUEUED", "RUNNING", "PENDING_RETRY"])
def test_active_query_descriptor_is_only_for_its_authorized_provider(client, auth_headers, configured, state):
    task_id, _grant = _queued_task(client, auth_headers)
    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, task_id)
        task.status = state
        task.next_attempt_at = utc_now() + timedelta(minutes=5)
        db.commit()
    response = client.get(f"/api/trust-space/query/tasks/{task_id}", headers=auth_headers["exchange"])
    assert response.status_code == 200
    assert response.json()["connector_readiness"] == {
        "health_url": "https://generator-browser.example/health", "organization_id": "org-generator-t01",
        "energy_domain": "electricity", "connector_id": "local-node-org-generator-t01", "raw_data_accessed": False,
    }
    denied = client.get(f"/api/trust-space/query/tasks/{task_id}", headers=auth_headers["retailer"])
    assert denied.status_code == 404 and "connector_readiness" not in denied.json()


@pytest.mark.parametrize("fault", ["revoked", "expired", "permission", "scope"])
def test_query_descriptor_is_omitted_when_authorization_stops_being_valid(client, auth_headers, configured, fault):
    task_id, grant_id = _queued_task(client, auth_headers)
    with SessionLocal() as db:
        grant = db.get(DataUsageRequest, grant_id)
        if fault == "revoked": grant.status = "REVOKED"
        elif fault == "expired": grant.expires_at = utc_now() - timedelta(seconds=1)
        elif fault == "scope": grant.provider_org_id = "org-retailer-t01"
        else:
            user = db.get(User, "user-exchange")
            user.permissions_json = [permission for permission in user.permissions_json if permission != "CREATE_COMPUTE_TASK"]
        db.commit()
    response = client.get(f"/api/trust-space/query/tasks/{task_id}", headers=auth_headers["exchange"])
    assert response.status_code == 200 and "connector_readiness" not in response.json()


@pytest.mark.parametrize("state,code", [("SUCCEEDED", None), ("FAILED", "REPEATED_QUERY_LIMIT"),
                                       ("FAILED", "CONNECTOR_BUDGET_EXHAUSTED"), ("FAILED", "CONNECTOR_IDENTITY_MISMATCH")])
def test_terminal_query_never_exposes_browser_activation(client, auth_headers, configured, state, code):
    task_id, _grant = _queued_task(client, auth_headers)
    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, task_id)
        task.status, task.failure_code = state, code
        db.commit()
    response = client.get(f"/api/trust-space/query/tasks/{task_id}", headers=auth_headers["exchange"])
    assert response.status_code == 200 and "connector_readiness" not in response.json()


@pytest.mark.parametrize("status,retryable", [("unavailable", True), ("unavailable", False), ("available", False), ("not_configured", False)])
def test_dashboard_activation_is_only_for_current_subject_transient_metric(client, auth_headers, configured, monkeypatch, status, retryable):
    metric = prototype._empty_subject_metric(prototype.ENTERPRISE_METRIC_SPECS["GENERATOR"],
        status=status, status_label="test-status", message="test-message", retryable=retryable)
    monkeypatch.setattr(prototype, "_load_subject_metric", lambda *_args: metric)
    response = client.get("/api/prototype/dashboard", headers=auth_headers["generator"])
    assert response.status_code == 200
    descriptor = response.json().get("connector_readiness")
    if status == "unavailable" and retryable:
        assert descriptor["organization_id"] == "org-generator-t01"
        assert descriptor["health_url"] == "https://generator-browser.example/health"
    else:
        assert descriptor is None


def test_regulator_dashboard_never_activates_business_connectors(client, auth_headers, configured, monkeypatch):
    monkeypatch.setattr(prototype, "_load_subject_metric", lambda *_args: {
        **prototype._empty_subject_metric(prototype.ENTERPRISE_METRIC_SPECS["GENERATOR"],
            status="unavailable", status_label="test-status", message="test-message", retryable=True),
    })
    response = client.get("/api/prototype/dashboard", headers=auth_headers["regulator"])
    assert response.status_code == 200 and "connector_readiness" not in response.json()


def test_dashboard_without_registered_node_does_not_expose_activation(client, auth_headers, configured, monkeypatch):
    with SessionLocal() as db:
        node = db.scalar(select(LocalSubjectNode).where(LocalSubjectNode.org_id == "org-generator-t01"))
        node.status = "SUSPENDED"
        db.commit()
    monkeypatch.setattr(prototype, "_load_subject_metric", lambda *_args: prototype._empty_subject_metric(
        prototype.ENTERPRISE_METRIC_SPECS["GENERATOR"], status="unavailable", status_label="test-status", message="test-message", retryable=True))
    response = client.get("/api/prototype/dashboard", headers=auth_headers["generator"])
    assert response.status_code == 200 and "connector_readiness" not in response.json()
