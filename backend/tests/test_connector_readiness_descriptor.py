"""Public browser readiness metadata never establishes trust or performs IO."""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from app.services import connector_readiness


@pytest.fixture(autouse=True)
def reset_test_database():
    yield


@pytest.fixture
def configured(monkeypatch):
    owner = "org-generator-t01"
    organization = SimpleNamespace(status="ACTIVE", energy_domain="electricity")
    node = {"org_id": owner, "node_id": "registered-node", "node_code": "local-node-org-generator-t01",
            "endpoint": "http://private-server-only:8000", "public_key": "never-return-this-key"}
    db = SimpleNamespace(get=lambda _model, org_id: organization if org_id == owner else None)
    monkeypatch.setattr(connector_readiness, "subject_node_config", lambda _db, org_id: node if org_id == owner else None)
    def endpoint(url, environment="test"):
        monkeypatch.setattr(connector_readiness, "settings", replace(connector_readiness.settings,
            app_env=environment, subject_node_browser_endpoints_json=json.dumps({owner: url})))
    endpoint("https://browser.example")
    return db, organization, node, endpoint


def test_only_explicit_public_health_and_identity_metadata_are_returned(configured):
    db, *_ = configured
    result = connector_readiness.browser_connector_readiness(db, "org-generator-t01", "electricity")
    assert result == {"health_url": "https://browser.example/health", "organization_id": "org-generator-t01",
                      "energy_domain": "electricity", "connector_id": "local-node-org-generator-t01", "raw_data_accessed": False}
    assert "never-return-this-key" not in str(result) and "private-server-only" not in str(result)


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "//browser.example", "ftp://browser.example", "http://browser.example",
    "http://10.0.0.1", "http://localhost.evil.example", "https://user:password@browser.example",
    "https://browser.example?token=secret", "https://browser.example#fragment", "https://browser.example:bad",
    "https://browser.example\n.evil", "https://browser.example/path with space", "https:///no-host", "",
    "https://browser.example\\path", "https://browser.example:65536", "https://browser.example:0",
])
def test_unsafe_browser_endpoint_never_produces_a_descriptor(configured, url):
    db, _org, _node, endpoint = configured
    endpoint(url)
    assert connector_readiness.browser_connector_readiness(db, "org-generator-t01", "electricity") is None


@pytest.mark.parametrize("url", ["http://127.0.0.1:8201", "http://localhost:8201", "http://[::1]:8201"])
def test_development_loopback_is_explicit_and_production_never_uses_http(configured, url):
    db, _org, _node, endpoint = configured
    endpoint(url)
    assert connector_readiness.browser_connector_readiness(db, "org-generator-t01", "electricity")["health_url"] == url + "/health"
    endpoint(url, "production")
    assert connector_readiness.browser_connector_readiness(db, "org-generator-t01", "electricity") is None


def test_no_fallback_to_server_endpoint_or_unregistered_node(configured, monkeypatch):
    db, _org, node, _endpoint = configured
    monkeypatch.setattr(connector_readiness, "settings", replace(connector_readiness.settings, subject_node_browser_endpoints_json="{}"))
    assert connector_readiness.browser_connector_readiness(db, "org-generator-t01", "electricity") is None
    monkeypatch.setattr(connector_readiness, "settings", replace(connector_readiness.settings, subject_node_browser_endpoints_json='{"org-generator-t01":"https://browser.example"}'))
    node["node_id"] = None
    assert connector_readiness.browser_connector_readiness(db, "org-generator-t01", "electricity") is None


@pytest.mark.parametrize("fault", ["inactive", "domain", "organization", "node_identity", "node_code"])
def test_inactive_or_unbound_identity_never_produces_a_descriptor(configured, fault):
    db, org, node, _endpoint = configured
    owner, domain = "org-generator-t01", "electricity"
    if fault == "inactive": org.status = "SUSPENDED"
    elif fault == "domain": domain = "oil"
    elif fault == "organization": owner = "other-org"
    elif fault == "node_identity": node["org_id"] = "other-org"
    else: node["node_code"] = ""
    assert connector_readiness.browser_connector_readiness(db, owner, domain) is None
