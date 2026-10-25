"""Dashboard availability classification with real signed responses, no node IO."""
from dataclasses import replace
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import httpx
import pytest

from app.routers import prototype
from test_prototype_dashboard_connector_trust import _dashboard_result, _JsonResponse, _public_key


@pytest.fixture(autouse=True)
def reset_test_database():
    yield


@pytest.fixture
def subject(monkeypatch):
    key = Ed25519PrivateKey.generate()
    node = {"endpoint": "https://node.example", "node_code": "local-node-org-generator-t01", "public_key": None}
    user = SimpleNamespace(org_id="org-generator-t01")
    view = {"kind": "enterprise", "role_code": "GENERATOR", "energy_domain": "electricity", "energy_label": "电力"}
    health = {"connector_id": node["node_code"], "organization_id": user.org_id, "energy_domain": "electricity", "public_key": _public_key(key)}
    monkeypatch.setattr(prototype, "settings", replace(prototype.settings, app_env="demo", connector_timeout_seconds=20))
    monkeypatch.setattr(prototype, "subject_node_config", lambda *_args: node)
    monkeypatch.setattr(prototype, "_platform_private_key", lambda: key)
    monkeypatch.setattr(prototype.httpx, "get", lambda *_args, **_kwargs: _JsonResponse(health))
    monkeypatch.setattr(prototype.httpx, "post", lambda _url, *, json, **_kwargs: _JsonResponse(_dashboard_result(json, key)))
    return user, view, node, health, key


@pytest.mark.parametrize("status", [408, 425, 429, 500, 503])
@pytest.mark.parametrize("endpoint", ["get", "post"])
def test_only_availability_http_failures_offer_recovery(monkeypatch, subject, status, endpoint):
    user, view, *_ = subject
    monkeypatch.setattr(prototype.httpx, endpoint, lambda *_args, **_kwargs: _JsonResponse({"detail": "temporary"}, status))
    metric = prototype._load_subject_metric(None, user, view)
    assert metric["status"] == "unavailable" and metric["retryable"] is True
    assert metric["value"] is None and metric["trend"] == []


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
@pytest.mark.parametrize("endpoint", ["get", "post"])
def test_permanent_http_errors_never_offer_automatic_recovery(monkeypatch, subject, status, endpoint):
    user, view, *_ = subject
    monkeypatch.setattr(prototype.httpx, endpoint, lambda *_args, **_kwargs: _JsonResponse({"detail": "permanent"}, status))
    metric = prototype._load_subject_metric(None, user, view)
    assert metric["status"] == "unavailable" and metric["retryable"] is False
    assert metric["value"] is None


def test_cold_transport_failure_recovers_to_a_verified_metric(monkeypatch, subject):
    user, view, _node, health, key = subject
    calls = []
    def get(_url, **options):
        calls.append(options["timeout"])
        if len(calls) == 1:
            raise httpx.ReadTimeout("cold node")
        return _JsonResponse(health)
    def post(_url, *, json, **options):
        calls.append(options["timeout"])
        return _JsonResponse(_dashboard_result(json, key))
    monkeypatch.setattr(prototype.httpx, "get", get)
    monkeypatch.setattr(prototype.httpx, "post", post)
    cold = prototype._load_subject_metric(None, user, view)
    ready = prototype._load_subject_metric(None, user, view)
    assert cold["status"] == "unavailable" and cold["retryable"] is True and cold["value"] is None
    assert ready["status"] == "available" and ready["retryable"] is False and ready["value"] == 14.0
    assert ready["connector_audit"]["status"] == "VERIFIED"
    assert calls == [8.0, 8.0, 8.0]


@pytest.mark.parametrize("fault", ["identity", "signature", "audit", "malformed"])
def test_integrity_and_malformed_failures_stay_nonretryable(monkeypatch, subject, fault):
    user, view, _node, health, key = subject
    if fault == "identity":
        health["organization_id"] = "different-organization"
    elif fault == "malformed":
        monkeypatch.setattr(prototype.httpx, "get", lambda *_args, **_kwargs: _JsonResponse([]))
    else:
        def post(_url, *, json, **_kwargs):
            payload = _dashboard_result(json, key, tamper_audit_result_hash=fault == "audit")
            if fault == "signature":
                payload["signature"] = "invalid"
            return _JsonResponse(payload)
        monkeypatch.setattr(prototype.httpx, "post", post)
    metric = prototype._load_subject_metric(None, user, view)
    assert metric["status"] == "unavailable" and metric["retryable"] is False
    assert metric["value"] is None and metric["trend"] == []


def test_unconfigured_node_never_schedules_recovery(monkeypatch, subject):
    user, view, *_ = subject
    monkeypatch.setattr(prototype, "subject_node_config", lambda *_args: None)
    metric = prototype._load_subject_metric(None, user, view)
    assert metric["status"] == "not_configured" and metric["retryable"] is False
