from __future__ import annotations

import base64
import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from app.database import SessionLocal
from app.models import LocalSubjectNode, User
from app.routers import prototype
from app.security import canonical_json, sha256_json
from app.services.privacy_attestation import ConnectorAuditError, verify_dashboard_audit_pointer


class _JsonResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def json(self) -> dict[str, Any]:
        return self._payload


def _public_key(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode()


def _dashboard_result(
    request_payload: dict[str, Any],
    private_key: Ed25519PrivateKey,
    *,
    tamper_audit_result_hash: bool = False,
) -> dict[str, Any]:
    occurred_at = datetime.now(UTC).isoformat()
    connector_id = "local-node-org-generator-t01"
    request_hash = sha256_json(request_payload)
    trend = [
        {"date": request_payload["start_date"], "value": 12.5},
        {"date": request_payload["end_date"], "value": 14.0},
    ]
    envelope: dict[str, Any] = {
        "request_id": request_payload["request_id"],
        "provider_org_id": request_payload["provider_org_id"],
        "connector_id": connector_id,
        "energy_domain": "electricity",
        "resource": request_payload["resource"],
        "resource_name": "发电出力",
        "aggregation": request_payload["aggregation"],
        "unit": "MWh",
        "latest": trend[-1],
        "trend": trend,
        "record_count": 8,
        "dataset_version": 3,
        "generated_at": "2026-08-29T12:00:00+00:00",
        "privacy": {
            "granularity": "day",
            "minimum_group_size": 3,
            "raw_records_returned": False,
            "raw_data_exported": False,
            "execution_environment": "SUBJECT_CONNECTOR",
            "attestation_status": "CONNECTOR_SIGNED",
            "non_export_attestation": {
                "status": "SIGNED",
                "issuer": connector_id,
                "boundary": "CONNECTOR_LOCAL_DATA",
                "request_hash": request_hash,
                "result_scope": "AGGREGATE_ONLY",
                "raw_data_exported": False,
            },
        },
        "privacy_verification": {
            "mode": "SIGNED_CONNECTOR_NON_EXPORT",
            "request_hash": request_hash,
            "raw_data_exported": False,
            "result_scope": "AGGREGATE_ONLY",
        },
        "raw_records_returned": False,
    }
    event = {
        "action": "DASHBOARD_AGGREGATE_ISSUED",
        "request_id": request_payload["request_id"],
        "provider_org_id": request_payload["provider_org_id"],
        "resource_id": request_payload["resource"],
        "request_hash": request_hash,
        "result_payload_hash": sha256_json(envelope),
        "record_count": 8,
        "dataset_version": 3,
        "raw_records_returned": False,
        "raw_data_exported": False,
        "connector_id": connector_id,
        "organization_id": request_payload["provider_org_id"],
        "energy_domain": "electricity",
        "occurred_at": occurred_at,
    }
    if tamper_audit_result_hash:
        event["result_payload_hash"] = "f" * 64
    previous_hash = "0" * 64
    envelope.update(
        {
            "audit_sequence": 1,
            "previous_audit_hash": previous_hash,
            "audit_hash": hashlib.sha256(
                (previous_hash + canonical_json(event)).encode("utf-8")
            ).hexdigest(),
            "audit_event": event,
        }
    )
    signature = private_key.sign(canonical_json(envelope).encode("utf-8"))
    return {
        **envelope,
        "signature": base64.b64encode(signature).decode(),
        "public_key": _public_key(private_key),
        "signature_algorithm": "Ed25519",
        "signature_valid": True,
    }


def _load_metric(monkeypatch, *, response_key: Ed25519PrivateKey, tamper_audit: bool = False) -> dict[str, Any]:
    trusted_key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(prototype, "settings", replace(prototype.settings, app_env="demo"))
    with SessionLocal() as db:
        node = db.query(LocalSubjectNode).filter_by(org_id="org-generator-t01").one()
        node.endpoint_ref = "https://connector.example"
        node.public_key = None
        db.commit()
        user = db.get(User, "user-generator")
        assert user is not None
        view = prototype._dashboard_view(db, user, None)

        monkeypatch.setattr(
            prototype.httpx,
            "get",
            lambda *_args, **_kwargs: _JsonResponse(
                {
                    "status": "就绪",
                    "connector_id": node.node_code,
                    "organization_id": node.org_id,
                    "energy_domain": "electricity",
                    "public_key": _public_key(trusted_key),
                }
            ),
        )

        def post(_url: str, *, json: dict[str, Any], **_kwargs: Any) -> _JsonResponse:
            return _JsonResponse(
                _dashboard_result(
                    json,
                    response_key,
                    tamper_audit_result_hash=tamper_audit,
                )
            )

        monkeypatch.setattr(prototype.httpx, "post", post)
        return prototype._load_subject_metric(db, user, view)


def test_dashboard_rejects_a_result_that_bootstraps_its_own_forged_key(monkeypatch):
    forged_key = Ed25519PrivateKey.generate()
    metric = _load_metric(monkeypatch, response_key=forged_key)

    assert metric["status"] == "unavailable"
    assert metric["value"] is None


def test_dashboard_rejects_resigned_tampered_audit_pointer(monkeypatch):
    # The response is rebuilt below with the trusted health key so signature
    # verification succeeds; only the audit binding should reject it.
    trusted_key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(prototype, "settings", replace(prototype.settings, app_env="demo"))

    with SessionLocal() as db:
        node = db.query(LocalSubjectNode).filter_by(org_id="org-generator-t01").one()
        node.endpoint_ref = "https://connector.example"
        node.public_key = None
        db.commit()
        user = db.get(User, "user-generator")
        assert user is not None
        view = prototype._dashboard_view(db, user, None)
        monkeypatch.setattr(
            prototype.httpx,
            "get",
            lambda *_args, **_kwargs: _JsonResponse(
                {
                    "connector_id": node.node_code,
                    "organization_id": node.org_id,
                    "energy_domain": "electricity",
                    "public_key": _public_key(trusted_key),
                }
            ),
        )
        monkeypatch.setattr(
            prototype.httpx,
            "post",
            lambda _url, *, json, **_kwargs: _JsonResponse(
                _dashboard_result(json, trusted_key, tamper_audit_result_hash=True)
            ),
        )
        metric = prototype._load_subject_metric(db, user, view)

    assert metric["status"] == "unavailable"
    assert metric["value"] is None


def test_dashboard_accepts_verified_health_key_and_exposes_only_audit_summary(monkeypatch):
    trusted_key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(prototype, "settings", replace(prototype.settings, app_env="demo"))
    with SessionLocal() as db:
        node = db.query(LocalSubjectNode).filter_by(org_id="org-generator-t01").one()
        node.endpoint_ref = "http://electricity-connector:8000"
        node.public_key = None
        db.commit()
        user = db.get(User, "user-generator")
        assert user is not None
        view = prototype._dashboard_view(db, user, None)
        monkeypatch.setattr(
            prototype.httpx,
            "get",
            lambda *_args, **_kwargs: _JsonResponse(
                {
                    "connector_id": node.node_code,
                    "organization_id": node.org_id,
                    "energy_domain": "electricity",
                    "public_key": _public_key(trusted_key),
                }
            ),
        )
        monkeypatch.setattr(
            prototype.httpx,
            "post",
            lambda _url, *, json, **_kwargs: _JsonResponse(
                _dashboard_result(json, trusted_key)
            ),
        )
        metric = prototype._load_subject_metric(db, user, view)

    assert metric["status"] == "available"
    assert {
        key: value
        for key, value in metric["connector_audit"].items()
        if key != "platform_received_at"
    } == {
        "status": "VERIFIED",
        "pointer_verified": True,
        "event_hash_verified": True,
        "verification_scope": "SINGLE_SIGNED_EVENT_POINTER",
        "action": "DASHBOARD_AGGREGATE_ISSUED",
        "connector_id": "local-node-org-generator-t01",
        "organization_id": "org-generator-t01",
        "energy_domain": "electricity",
        "sequence": 1,
        "previous_hash": "0" * 64,
        "audit_hash": metric["connector_audit"]["audit_hash"],
        "connector_declared_at": metric["connector_audit"]["connector_declared_at"],
        "key_source": "VERIFIED_HEALTH_DISCOVERY",
    }
    assert "audit_event" not in metric["connector_audit"]
    assert "request_hash" not in metric["connector_audit"]


def test_dashboard_health_discovery_rejects_non_http_endpoint(monkeypatch):
    monkeypatch.setattr(prototype, "settings", replace(prototype.settings, app_env="demo"))
    try:
        prototype._dashboard_connector_public_key(
            endpoint="file://electricity-connector/runtime/key",
            node={"node_code": "local-node-org-generator-t01", "public_key": None},
            provider_org_id="org-generator-t01",
            energy_domain="electricity",
        )
    except ValueError as exc:
        assert "端点不安全" in str(exc)
    else:
        raise AssertionError("non-HTTP connector discovery endpoint must be rejected")


def test_dashboard_production_rejects_http_even_with_registered_key(monkeypatch):
    monkeypatch.setattr(prototype, "settings", replace(prototype.settings, app_env="production"))
    registered_key = _public_key(Ed25519PrivateKey.generate())
    try:
        prototype._dashboard_connector_public_key(
            endpoint="http://electricity-connector:8000",
            node={
                "node_code": "local-node-org-generator-t01",
                "public_key": registered_key,
            },
            provider_org_id="org-generator-t01",
            energy_domain="electricity",
        )
    except ValueError as exc:
        assert "必须使用 HTTPS" in str(exc)
    else:
        raise AssertionError("production connector endpoint must require HTTPS")


def test_dashboard_audit_validator_rejects_missing_raw_export_flag():
    request_payload = {
        "request_id": "dashboard-missing-raw-flag",
        "provider_org_id": "org-generator-t01",
        "resource": "generation",
        "aggregation": "sum",
        "start_date": "2026-08-01",
        "end_date": "2026-08-29",
        "decimals": 2,
    }
    result = _dashboard_result(request_payload, Ed25519PrivateKey.generate())
    signed_result = {
        key: value
        for key, value in result.items()
        if key not in {"signature", "public_key", "signature_algorithm", "signature_valid"}
    }
    event = signed_result["audit_event"]
    assert isinstance(event, dict)
    event.pop("raw_data_exported")
    signed_result["audit_hash"] = hashlib.sha256(
        (str(signed_result["previous_audit_hash"]) + canonical_json(event)).encode("utf-8")
    ).hexdigest()

    with pytest.raises(ConnectorAuditError):
        verify_dashboard_audit_pointer(
            signed_result,
            request_payload,
            expected_connector_id="local-node-org-generator-t01",
            expected_provider_org_id="org-generator-t01",
            expected_energy_domain="electricity",
        )
