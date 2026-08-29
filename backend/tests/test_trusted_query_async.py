from __future__ import annotations

import base64
import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import (
    AnomalyEvent,
    AuditLog,
    DataRequestItem,
    DataUsageRequest,
    ExecutionReceipt,
    LocalSubjectNode,
    PrivacyComputeJob,
    TrustedQueryTask,
    User,
    new_id,
    utc_now,
)
from app.routers import trusted_query
from app.production import _is_supported_local_subject_compute_record
from app.security import canonical_json, create_access_token, hash_password, sha256_json
from app.trust_models import DataAsset, DataAssetVersion, DataSource


QUERY_PATH = "/api/trust-space/query"


def _public_key(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode()


def _prepare_authorization(
    *,
    applicant_user_id: str = "user-exchange",
    applicant_org_id: str = "org-exchange-t01",
) -> tuple[str, Ed25519PrivateKey]:
    private_key = Ed25519PrivateKey.generate()
    with SessionLocal() as db:
        source = db.scalar(
            select(DataSource).where(DataSource.owner_org_id == "org-generator-t01")
        )
        assert source is not None
        asset = DataAsset(
            asset_id=new_id(),
            source_id=source.source_id,
            owner_org_id="org-generator-t01",
            asset_code=f"ASYNC_GENERATION_{new_id()}",
            asset_name="异步可信查询发电量",
            asset_type="ELECTRICITY_METRIC",
            classification="ENTERPRISE_DATA_PRODUCT",
            sensitivity_level="L2",
            status="ACTIVE",
            metadata_json={
                "domain": "electricity",
                "resource_id": "generation",
                "raw_data_centrally_stored": False,
            },
        )
        db.add(asset)
        db.flush()
        version = DataAssetVersion(
            version_id=new_id(),
            asset_id=asset.asset_id,
            version_no=1,
            schema_version="connector-csv-v1",
            schema_json={"fields": ["record_date", "value"]},
            data_ref="connector://node/generation/versions/1",
            data_hash=sha256_json({"asset_id": asset.asset_id, "version": 1}),
            record_count=2,
            immutable_hash=sha256_json({"asset_id": asset.asset_id, "immutable": 1}),
            status="ACTIVE",
        )
        db.add(version)
        db.flush()
        asset.current_version_id = version.version_id
        authorization = DataUsageRequest(
            request_id=new_id(),
            asset_id=asset.asset_id,
            asset_version_id=version.version_id,
            applicant_user_id=applicant_user_id,
            applicant_org_id=applicant_org_id,
            provider_org_id="org-generator-t01",
            applicant_did=f"did:hiddenchain:org:{applicant_org_id}",
            provider_did="did:hiddenchain:org:org-generator-t01",
            purpose="CONTROLLED_AGGREGATE_QUERY",
            usage_mode="AGGREGATE_ONLY",
            requested_scope_json={"raw_data_export": False},
            requested_fields_json=["generation", "average"],
            terms_json={"raw_data_export": False, "output_mode": "AGGREGATE_ONLY"},
            duration_days=1,
            expires_at=utc_now() + timedelta(days=1),
            status="APPROVED",
            decision_hash=sha256_json({"authorization": asset.asset_id}),
            decision_capability_label="LOCAL_REAL",
            state_version=1,
            request_fingerprint=sha256_json({"request": asset.asset_id}),
            submitted_at=utc_now(),
            decided_at=utc_now(),
            trace_id=f"trace-{new_id()}",
        )
        node = db.scalar(
            select(LocalSubjectNode).where(
                LocalSubjectNode.org_id == "org-generator-t01"
            )
        )
        assert node is not None
        node.endpoint_ref = "https://connector.example"
        node.public_key = _public_key(private_key)
        db.add(authorization)
        db.commit()
        return authorization.request_id, private_key


def _query_body(client, headers: dict[str, str], authorization_id: str) -> dict[str, Any]:
    conditions = {
        "authorization_id": authorization_id,
        "provider_org_id": "org-generator-t01",
        "energy_domain": "electricity",
        "resource": "generation",
        "function": "average",
        "start_date": "2026-08-01",
        "end_date": "2026-08-02",
        "region": None,
        "decimals": 2,
    }
    confirmation = client.post(
        f"{QUERY_PATH}/confirm",
        headers=headers,
        json=conditions,
    )
    assert confirmation.status_code == 200, confirmation.text
    return {
        **conditions,
        "hour": None,
        "threshold": None,
        "group_by": None,
        "confirmation_token": confirmation.json()["confirmation_token"],
    }


def _signed_connector_response(
    request_payload: dict[str, Any],
    private_key: Ed25519PrivateKey,
    *,
    version_overrides: dict[str, Any] | None = None,
) -> httpx.Response:
    request_hash = sha256_json(request_payload)
    signed_result = {
        "task_id": request_payload["task_id"],
        "authorization_id": request_payload["authorization_id"],
        "request_item_id": request_payload["request_item_id"],
        "provider_org_id": request_payload["provider_org_id"],
        "rule_version": request_payload["rule_version"],
        "connector_id": "local-node-org-generator-t01",
        "energy_domain": "electricity",
        "generated_at": "2026-08-29T12:00:00Z",
        "result": 12.5,
        "unit": "MWh",
        "record_count": 2,
        "dataset_version": request_payload["dataset_version"],
        "dataset_local_ref": request_payload["dataset_local_ref"],
        "dataset_content_hash": request_payload["dataset_content_hash"],
        "trend": [],
        "resource_name": "异步可信查询发电量",
        "function_name": "平均值",
        "capability": "本地受控计算",
        "raw_records_returned": False,
        "privacy": {
            "raw_records_returned": False,
            "raw_data_exported": False,
            "non_export_attestation": {
                "status": "SIGNED",
                "issuer": "local-node-org-generator-t01",
                "boundary": "CONNECTOR_LOCAL_DATA",
                "request_hash": request_hash,
                "result_scope": "AGGREGATE_ONLY",
                "raw_data_exported": False,
            },
        },
        "privacy_verification": {
            "mode": "SIGNED_CONNECTOR_NON_EXPORT",
            "request_hash": request_hash,
            "result_scope": "AGGREGATE_ONLY",
            "raw_data_exported": False,
        },
    }
    signed_result.update(version_overrides or {})
    previous_audit_hash = "0" * 64
    audit_event = {
        "action": "LOCAL_CONTROLLED_RESULT_ISSUED",
        "task_id": request_payload["task_id"],
        "authorization_id": request_payload["authorization_id"],
        "request_item_id": request_payload["request_item_id"],
        "provider_org_id": request_payload["provider_org_id"],
        "request_hash": request_hash,
        "result_payload_hash": sha256_json(signed_result),
        "record_count": 2,
        "dataset_version": signed_result["dataset_version"],
        "dataset_local_ref": signed_result["dataset_local_ref"],
        "dataset_content_hash": signed_result["dataset_content_hash"],
        "raw_records_returned": False,
        "raw_data_exported": False,
        "connector_id": "local-node-org-generator-t01",
        "organization_id": "org-generator-t01",
        "energy_domain": "electricity",
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    signed_result.update(
        {
            "audit_sequence": 1,
            "previous_audit_hash": previous_audit_hash,
            "audit_hash": hashlib.sha256(
                (previous_audit_hash + canonical_json(audit_event)).encode()
            ).hexdigest(),
            "audit_event": audit_event,
        }
    )
    payload = {
        **signed_result,
        "signature": base64.b64encode(
            private_key.sign(canonical_json(signed_result).encode())
        ).decode(),
        "public_key": _public_key(private_key),
        "signature_algorithm": "Ed25519",
        "signature_valid": True,
    }
    return httpx.Response(
        200,
        json=payload,
        request=httpx.Request("POST", "https://connector.example/compute"),
    )


def _install_success_connector(monkeypatch, private_key: Ed25519PrivateKey):
    calls: list[dict[str, Any]] = []

    def post(url: str, *, json: dict[str, Any], headers: dict[str, str], timeout: float):
        calls.append(json)
        return _signed_connector_response(json, private_key)

    monkeypatch.setattr(trusted_query.httpx, "post", post)
    return calls


def _clear_registered_connector_key() -> None:
    with SessionLocal() as db:
        node = db.scalar(
            select(LocalSubjectNode).where(
                LocalSubjectNode.org_id == "org-generator-t01"
            )
        )
        assert node is not None
        node.public_key = None
        db.commit()


def _discovery_response(url: str, payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("GET", url))


def _execute(client, headers, body, key: str):
    return client.post(
        f"{QUERY_PATH}/execute",
        headers={**headers, "Idempotency-Key": key},
        json=body,
    )


def _alternate_valid_confirmation_token(token: str) -> str:
    encoded, _signature = token.split(".", 1)
    padding = "=" * (-len(encoded) % 4)
    claims = json.loads(base64.urlsafe_b64decode(f"{encoded}{padding}").decode())
    alternate_json = json.dumps(
        dict(reversed(list(claims.items()))),
        ensure_ascii=False,
        separators=(", ", ": "),
    )
    alternate_encoded = base64.urlsafe_b64encode(alternate_json.encode()).decode().rstrip("=")
    signature = hmac.new(
        trusted_query.settings.signing_secret.encode(),
        alternate_encoded.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{alternate_encoded}.{signature}"


def test_execute_returns_202_and_persists_a_sanitized_task(client, auth_headers, monkeypatch):
    authorization_id, private_key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    calls = _install_success_connector(monkeypatch, private_key)

    response = _execute(client, auth_headers["exchange"], body, "async-create-001")

    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["status"] == "QUEUED"
    assert accepted["status_url"] == f"{QUERY_PATH}/tasks/{accepted['task_id']}"
    assert "result" not in accepted
    assert "job_id" not in accepted
    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, accepted["task_id"])
        assert task is not None
        assert task.request_fingerprint
        assert task.request_fingerprint == sha256_json(task.canonical_payload_json)
        assert "confirmation_token" not in task.canonical_payload_json
        assert task.status == "SUCCEEDED"
        job = db.scalar(
            select(PrivacyComputeJob).where(
                PrivacyComputeJob.task_id == accepted["task_id"]
            )
        )
        assert job is not None
        assert _is_supported_local_subject_compute_record(
            db,
            job,
            replace(
                trusted_query.settings,
                subject_node_ids_json=(
                    '{"org-generator-t01":"local-node-org-generator-t01"}'
                ),
                subject_node_public_keys_json=(
                    '{"org-generator-t01":"' + _public_key(private_key) + '"}'
                ),
            ),
        ) is True
        receipt = db.scalar(
            select(ExecutionReceipt).where(
                ExecutionReceipt.request_item_id == task.request_item_id
            )
        )
        assert receipt is not None
        assert receipt.audit_sequence == 1
        assert receipt.previous_audit_hash == "0" * 64
        assert receipt.connector_audit_hash
        assert receipt.audit_event_verified is True
    assert len(calls) == 1
    assert calls[0]["dataset_version"] == 1
    assert calls[0]["dataset_local_ref"] == "connector://node/generation/versions/1"
    assert calls[0]["dataset_content_hash"]

    result = client.get(
        f"{QUERY_PATH}/tasks/{accepted['task_id']}/result",
        headers=auth_headers["exchange"],
    )
    assert result.status_code == 200, result.text
    assert result.json()["result"] == 12.5
    assert result.json()["raw_records_returned"] is False
    assert result.json()["privacy_verification"]["status"] == "VERIFIED"
    assert result.json()["connector_audit"]["status"] == "VERIFIED"
    assert result.json()["connector_audit"]["pointer_verified"] is True
    assert result.json()["connector_audit"]["event_hash_verified"] is True
    assert result.json()["connector_audit"]["verification_scope"] == "SINGLE_SIGNED_EVENT_POINTER"
    assert result.json()["connector_audit"]["connector_declared_at"]
    assert result.json()["connector_audit"]["platform_received_at"]
    assert "chain_verified" not in result.text
    assert result.json()["privacy_verification"]["connector_audit"]["sequence"] == 1
    assert result.json()["dataset_version"] == 1
    assert result.json()["dataset_local_ref"] == calls[0]["dataset_local_ref"]
    assert result.json()["dataset_content_hash"] == calls[0]["dataset_content_hash"]

    audit_list = client.get(
        "/api/trust-space/audit?page_size=100",
        headers=auth_headers["regulator"],
    )
    assert audit_list.status_code == 200
    assert accepted["task_id"] in {
        item["target_id"] for item in audit_list.json()["items"]
    }
    audit_detail = client.get(
        f"/api/trust-space/audit/tasks/{accepted['task_id']}",
        headers=auth_headers["regulator"],
    )
    assert audit_detail.status_code == 200, audit_detail.text
    assert {item["action_code"] for item in audit_detail.json()["audit_chain"]} >= {
        "TRUSTED_QUERY_QUEUED",
        "CONTROLLED_QUERY_COMPLETED",
    }
    audit_export = client.get(
        "/api/trust-space/audit/export?format=json",
        headers=auth_headers["regulator"],
    )
    assert audit_export.status_code == 200
    assert accepted["task_id"] in {
        item["target_id"] for item in audit_export.json()["items"]
    }


def test_failure_side_effects_require_winning_lease_fence(client, auth_headers, monkeypatch):
    authorization_id, _private_key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    monkeypatch.setattr(trusted_query, "run_trusted_query_task", lambda _task_id: None)
    accepted = _execute(client, auth_headers["exchange"], body, "failure-fence")
    task_id = accepted.json()["task_id"]

    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, task_id)
        assert task is not None
        task.status = "RUNNING"
        task.attempt = 1
        task.lease_owner = "old-worker"
        request_item_id = task.request_item_id
        db.commit()

        real_execute = db.execute

        def lose_fence(statement, *args, **kwargs):
            if getattr(getattr(statement, "table", None), "name", None) == "trusted_query_tasks":
                return SimpleNamespace(rowcount=0)
            return real_execute(statement, *args, **kwargs)

        monkeypatch.setattr(db, "execute", lose_fence)
        trusted_query._record_query_task_failure(
            db,
            task_id=task_id,
            lease_owner="old-worker",
            error=trusted_query.TrustedQueryExecutionError(
                "STALE_WORKER_FAILURE",
                "stale worker must not persist",
                retryable=False,
            ),
        )

    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, task_id)
        request_item = db.get(DataRequestItem, request_item_id)
        assert task is not None and request_item is not None
        assert task.status == "RUNNING"
        assert task.lease_owner == "old-worker"
        assert request_item.failure_code is None
        assert db.scalar(
            select(func.count(AnomalyEvent.event_id)).where(
                AnomalyEvent.task_id == task_id
            )
        ) == 0
        assert db.scalar(
            select(func.count(AuditLog.log_id)).where(
                AuditLog.target_type == "TRUSTED_QUERY_TASK",
                AuditLog.target_id == task_id,
                AuditLog.action_code.in_(("TRUSTED_QUERY_FAILED", "TRUSTED_QUERY_RETRY_SCHEDULED")),
            )
        ) == 0


def test_platform_rejects_connector_result_from_an_unapproved_version(
    client, auth_headers, monkeypatch
):
    authorization_id, private_key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)

    def post(url: str, *, json: dict[str, Any], headers: dict[str, str], timeout: float):
        return _signed_connector_response(
            json,
            private_key,
            version_overrides={
                "dataset_version": 2,
                "dataset_local_ref": "connector://node/generation/versions/2",
                "dataset_content_hash": "2" * 64,
            },
        )

    monkeypatch.setattr(trusted_query.httpx, "post", post)
    accepted = _execute(client, auth_headers["exchange"], body, "wrong-result-version")
    assert accepted.status_code == 202, accepted.text
    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, accepted.json()["task_id"])
        assert task is not None
        assert task.status == "FAILED"
        assert task.failure_code == "DATA_VERSION_BINDING_MISMATCH"
        assert db.scalar(
            select(func.count(PrivacyComputeJob.job_id)).where(
                PrivacyComputeJob.task_id == task.task_id
            )
        ) == 0


def test_expired_last_attempt_uses_fenced_terminal_failure_transaction(
    client, auth_headers, monkeypatch
):
    authorization_id, _private_key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    monkeypatch.setattr(trusted_query, "run_trusted_query_task", lambda _task_id: None)
    accepted = _execute(client, auth_headers["exchange"], body, "expired-last-attempt")
    task_id = accepted.json()["task_id"]

    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, task_id)
        assert task is not None
        task.status = "RUNNING"
        task.attempt = task.max_attempts
        task.lease_owner = "crashed-worker"
        task.lease_expires_at = utc_now() - timedelta(seconds=1)
        request_item_id = task.request_item_id
        db.commit()

    with SessionLocal() as db:
        assert trusted_query._claim_query_task(
            db, task_id=task_id, lease_owner="takeover-worker"
        ) is None

    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, task_id)
        request_item = db.get(DataRequestItem, request_item_id)
        assert task is not None and request_item is not None
        assert task.status == "FAILED"
        assert task.failure_code == "RETRY_LIMIT_EXHAUSTED"
        assert task.lease_owner is None
        assert request_item.status == "FAILED"
        assert request_item.failure_code == "RETRY_LIMIT_EXHAUSTED"
        assert request_item.completed_at is not None
        assert db.scalar(
            select(func.count(AnomalyEvent.event_id)).where(
                AnomalyEvent.task_id == task_id,
                AnomalyEvent.event_type == "TRUSTED_QUERY_TERMINAL_FAILURE",
            )
        ) == 1
        assert db.scalar(
            select(func.count(AuditLog.log_id)).where(
                AuditLog.target_type == "TRUSTED_QUERY_TASK",
                AuditLog.target_id == task_id,
                AuditLog.action_code == "TRUSTED_QUERY_FAILED",
            )
        ) == 1


def test_result_key_cannot_bootstrap_trust_without_valid_health_identity(
    client, auth_headers, monkeypatch
):
    authorization_id, forged_key = _prepare_authorization()
    _clear_registered_connector_key()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    compute_calls: list[dict[str, Any]] = []

    def get(url: str, *, timeout: float):
        return _discovery_response(
            url,
            {
                "organization_id": "org-attacker",
                "energy_domain": "electricity",
                "connector_id": "local-node-org-generator-t01",
                "public_key": _public_key(forged_key),
            },
        )

    def post(url: str, *, json: dict[str, Any], headers: dict[str, str], timeout: float):
        compute_calls.append(json)
        return _signed_connector_response(json, forged_key)

    monkeypatch.setattr(trusted_query.httpx, "get", get)
    monkeypatch.setattr(trusted_query.httpx, "post", post)

    accepted = _execute(client, auth_headers["exchange"], body, "forged-self-key")

    assert accepted.status_code == 202
    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, accepted.json()["task_id"])
        assert task is not None
        assert task.status == "FAILED"
        assert task.failure_code == "CONNECTOR_IDENTITY_MISMATCH"
    assert compute_calls == []


def test_connector_cannot_re_sign_a_tampered_local_audit_pointer(
    client, auth_headers, monkeypatch
):
    authorization_id, private_key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)

    def post(url: str, *, json: dict[str, Any], headers: dict[str, str], timeout: float):
        response = _signed_connector_response(json, private_key)
        payload = response.json()
        signed_result = {
            key: value
            for key, value in payload.items()
            if key not in {"signature", "public_key", "signature_algorithm", "signature_valid"}
        }
        signed_result["audit_event"]["result_payload_hash"] = "f" * 64
        payload.update(
            signed_result,
            signature=base64.b64encode(
                private_key.sign(canonical_json(signed_result).encode())
            ).decode(),
        )
        return httpx.Response(
            200,
            json=payload,
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(trusted_query.httpx, "post", post)

    accepted = _execute(client, auth_headers["exchange"], body, "tampered-audit-pointer")

    assert accepted.status_code == 202
    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, accepted.json()["task_id"])
        assert task is not None
        assert task.status == "FAILED"
        assert task.failure_code == "CONNECTOR_AUDIT_INVALID"
        assert db.scalar(
            select(func.count(ExecutionReceipt.receipt_id)).where(
                ExecutionReceipt.request_item_id == task.request_item_id
            )
        ) == 0


def test_health_discovered_key_must_match_result_key(client, auth_headers, monkeypatch):
    authorization_id, _initial_key = _prepare_authorization()
    _clear_registered_connector_key()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    health_key = Ed25519PrivateKey.generate()
    forged_result_key = Ed25519PrivateKey.generate()

    def get(url: str, *, timeout: float):
        return _discovery_response(
            url,
            {
                "organization_id": "org-generator-t01",
                "energy_domain": "electricity",
                "connector_id": "local-node-org-generator-t01",
                "public_key": _public_key(health_key),
            },
        )

    monkeypatch.setattr(trusted_query.httpx, "get", get)
    monkeypatch.setattr(
        trusted_query.httpx,
        "post",
        lambda url, *, json, headers, timeout: _signed_connector_response(
            json, forged_result_key
        ),
    )

    accepted = _execute(client, auth_headers["exchange"], body, "health-key-mismatch")

    assert accepted.status_code == 202
    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, accepted.json()["task_id"])
        assert task is not None
        assert task.status == "FAILED"
        assert task.failure_code == "CONNECTOR_IDENTITY_MISMATCH"


def test_health_discovery_validates_catalog_identity_before_accepting_key(
    client, auth_headers, monkeypatch
):
    authorization_id, health_key = _prepare_authorization()
    _clear_registered_connector_key()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    discovery_urls: list[str] = []

    def get(url: str, *, timeout: float):
        discovery_urls.append(url)
        if url.endswith("/health"):
            payload = {
                "organization_id": "org-generator-t01",
                "energy_domain": "electricity",
                "public_key": _public_key(health_key),
            }
        else:
            payload = {
                "organization_id": "org-generator-t01",
                "energy_domain": "electricity",
                "connector_id": "local-node-org-generator-t01",
            }
        return _discovery_response(url, payload)

    monkeypatch.setattr(trusted_query.httpx, "get", get)
    monkeypatch.setattr(
        trusted_query.httpx,
        "post",
        lambda url, *, json, headers, timeout: _signed_connector_response(
            json, health_key
        ),
    )

    accepted = _execute(client, auth_headers["exchange"], body, "health-discovery")

    assert accepted.status_code == 202
    assert discovery_urls == [
        "https://connector.example/health",
        "https://connector.example/catalog",
    ]
    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, accepted.json()["task_id"])
        assert task is not None
        assert task.status == "SUCCEEDED"


def test_demo_discovery_accepts_configured_compose_http_service_name(monkeypatch):
    private_key = Ed25519PrivateKey.generate()
    requested_urls: list[str] = []

    def get(url: str, *, timeout: float):
        requested_urls.append(url)
        return _discovery_response(
            url,
            {
                "connector_id": "local-node-org-generator-t01",
                "organization_id": "org-generator-t01",
                "energy_domain": "electricity",
                "public_key": _public_key(private_key),
            },
        )

    monkeypatch.setattr(trusted_query.httpx, "get", get)

    discovered = trusted_query._discover_connector_public_key(
        endpoint="http://electricity-connector:8000",
        node={"node_code": "local-node-org-generator-t01"},
        provider_org_id="org-generator-t01",
        energy_domain="electricity",
    )

    assert discovered == _public_key(private_key)
    assert requested_urls == ["http://electricity-connector:8000/health"]


def test_idempotency_replays_same_body_and_rejects_rebinding(client, auth_headers, monkeypatch):
    authorization_id, private_key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    calls = _install_success_connector(monkeypatch, private_key)

    first = _execute(client, auth_headers["exchange"], body, "async-replay-001")
    assert first.status_code == 202
    with SessionLocal() as db:
        legacy_task = db.get(TrustedQueryTask, first.json()["task_id"])
        assert legacy_task is not None
        legacy_payload = {
            **legacy_task.canonical_payload_json,
            "confirmation_token_hash": hashlib.sha256(
                body["confirmation_token"].encode()
            ).hexdigest(),
        }
        legacy_task.canonical_payload_json = legacy_payload
        legacy_task.request_fingerprint = sha256_json(legacy_payload)
        db.commit()
    refreshed_body = {
        **body,
        "confirmation_token": _alternate_valid_confirmation_token(
            body["confirmation_token"]
        ),
    }
    replay = _execute(client, auth_headers["exchange"], refreshed_body, "async-replay-001")
    changed_body = {**body, "decimals": 3}
    changed_confirmation = client.post(
        f"{QUERY_PATH}/confirm",
        headers=auth_headers["exchange"],
        json=changed_body,
    )
    assert changed_confirmation.status_code == 200
    changed_body["confirmation_token"] = changed_confirmation.json()["confirmation_token"]
    rebound = _execute(
        client,
        auth_headers["exchange"],
        changed_body,
        "async-replay-001",
    )
    wrong_payload_token = _execute(
        client,
        auth_headers["exchange"],
        {**body, "decimals": 3},
        "async-replay-001",
    )
    invalid_token = _execute(
        client,
        auth_headers["exchange"],
        {**body, "confirmation_token": f"{body['confirmation_token']}x"},
        "async-replay-001",
    )

    assert replay.status_code == 202
    assert first.json()["task_id"] == replay.json()["task_id"]
    assert replay.json()["idempotent_replay"] is True
    assert rebound.status_code == 409
    assert "幂等键" in rebound.json()["detail"]
    assert wrong_payload_token.status_code == 409
    assert "查询条件已变化" in wrong_payload_token.json()["detail"]
    assert invalid_token.status_code == 409
    assert "确认令牌无效" in invalid_token.json()["detail"]
    assert len(calls) == 1


def test_same_key_is_isolated_by_user_and_task_reads_require_exact_owner(
    client, auth_headers, monkeypatch
):
    with SessionLocal() as db:
        db.add(
            User(
                user_id="user-exchange-peer",
                org_id="org-exchange-t01",
                username="exchange_peer",
                password_hash=hash_password("unused"),
                display_name="交易中心同组织第二账号",
                role_code="EXCHANGE",
                permissions_json=["CREATE_COMPUTE_TASK", "VIEW_COMPUTE_RESULT"],
                is_org_owner=False,
                status="ACTIVE",
            )
        )
        db.commit()
    peer_headers = {
        "Authorization": "Bearer "
        + create_access_token("user-exchange-peer", "EXCHANGE", "org-exchange-t01")
    }
    authorization_id, _first_private_key = _prepare_authorization()
    retailer_authorization_id, private_key = _prepare_authorization(
        applicant_user_id="user-retailer",
        applicant_org_id="org-retailer-t01",
    )
    owner_body = _query_body(client, auth_headers["exchange"], authorization_id)
    peer_body = _query_body(client, peer_headers, authorization_id)
    retailer_body = _query_body(
        client,
        auth_headers["retailer"],
        retailer_authorization_id,
    )
    calls = _install_success_connector(monkeypatch, private_key)

    owner = _execute(client, auth_headers["exchange"], owner_body, "shared-key")
    peer = _execute(client, peer_headers, peer_body, "shared-key")
    retailer = _execute(
        client,
        auth_headers["retailer"],
        retailer_body,
        "shared-key",
    )

    assert owner.status_code == peer.status_code == retailer.status_code == 202
    assert len(
        {
            owner.json()["task_id"],
            peer.json()["task_id"],
            retailer.json()["task_id"],
        }
    ) == 3
    assert len(calls) == 3
    hidden = client.get(
        f"{QUERY_PATH}/tasks/{owner.json()['task_id']}", headers=peer_headers
    )
    assert hidden.status_code == 404
    cross_org_hidden = client.get(
        f"{QUERY_PATH}/tasks/{owner.json()['task_id']}",
        headers=auth_headers["retailer"],
    )
    assert cross_org_hidden.status_code == 404


def test_polling_rejects_a_task_if_authorization_was_revoked_before_dispatch(
    client, auth_headers, monkeypatch
):
    authorization_id, private_key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    calls = _install_success_connector(monkeypatch, private_key)
    real_runner = trusted_query.run_trusted_query_task
    monkeypatch.setattr(trusted_query, "run_trusted_query_task", lambda _task_id: None)
    accepted = _execute(client, auth_headers["exchange"], body, "revoked-before-run")
    assert accepted.status_code == 202
    with SessionLocal() as db:
        authorization = db.get(DataUsageRequest, authorization_id)
        assert authorization is not None
        authorization.status = "REVOKED"
        authorization.revoked_at = utc_now()
        db.commit()
    monkeypatch.setattr(trusted_query, "run_trusted_query_task", real_runner)

    client.get(
        f"{QUERY_PATH}/tasks/{accepted.json()['task_id']}",
        headers=auth_headers["exchange"],
    )
    status = client.get(
        f"{QUERY_PATH}/tasks/{accepted.json()['task_id']}",
        headers=auth_headers["exchange"],
    )
    assert status.status_code == 200
    assert status.json()["status"] == "FAILED"
    assert status.json()["failure_code"] == "AUTHORIZATION_REVOKED"
    assert len(calls) == 0
    with SessionLocal() as db:
        anomaly = db.scalar(select(AnomalyEvent).where(
            AnomalyEvent.dedupe_key == f"trusted-query-terminal-failure:{accepted.json()['task_id']}"
        ))
        assert anomaly is not None
        assert anomaly.event_type == "TRUSTED_QUERY_TERMINAL_FAILURE"
        anomaly_id = anomaly.event_id
        db.add_all(
            [
                User(
                    user_id="query-regulator-no-scope",
                    org_id="org-regulator-t01",
                    username="query_regulator_no_scope",
                    password_hash=hash_password("unused"),
                    display_name="无查询范围监管员",
                    role_code="REGULATOR",
                    permissions_json=["VIEW_AUDIT"],
                ),
                User(
                    user_id="query-regulator-task-scope",
                    org_id="org-regulator-t01",
                    username="query_regulator_task_scope",
                    password_hash=hash_password("unused"),
                    display_name="查询任务监管员",
                    role_code="REGULATOR",
                    permissions_json=[
                        "VIEW_AUDIT",
                        f"VIEW_AUDIT:TASK:{accepted.json()['task_id']}",
                    ],
                ),
            ]
        )
        db.commit()

    applicant_anomalies = client.get("/api/anomalies", headers=auth_headers["exchange"])
    assert applicant_anomalies.status_code == 200
    assert anomaly_id in {item["event_id"] for item in applicant_anomalies.json()}
    no_scope_headers = {
        "Authorization": "Bearer "
        + create_access_token(
            "query-regulator-no-scope", "REGULATOR", "org-regulator-t01"
        )
    }
    task_scope_headers = {
        "Authorization": "Bearer "
        + create_access_token(
            "query-regulator-task-scope", "REGULATOR", "org-regulator-t01"
        )
    }
    assert anomaly_id not in {
        item["event_id"]
        for item in client.get("/api/anomalies", headers=no_scope_headers).json()
    }
    assert anomaly_id in {
        item["event_id"]
        for item in client.get("/api/anomalies", headers=task_scope_headers).json()
    }
    assert client.post(
        f"/api/anomalies/{anomaly_id}/resolve",
        headers={
            **no_scope_headers,
            "If-Match": '"1"',
            "Idempotency-Key": "query-anomaly-no-scope",
        },
        json={"resolution": "不应允许处置"},
    ).status_code == 404
    resolved = client.post(
        f"/api/anomalies/{anomaly_id}/resolve",
        headers={
            **task_scope_headers,
            "If-Match": '"1"',
            "Idempotency-Key": "query-anomaly-task-scope",
        },
        json={"resolution": "确认查询终态失败"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "RESOLVED"


def test_polling_recovers_an_expired_running_lease(client, auth_headers, monkeypatch):
    authorization_id, private_key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    calls = _install_success_connector(monkeypatch, private_key)
    real_runner = trusted_query.run_trusted_query_task
    monkeypatch.setattr(trusted_query, "run_trusted_query_task", lambda _task_id: None)
    accepted = _execute(client, auth_headers["exchange"], body, "expired-lease")
    task_id = accepted.json()["task_id"]
    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, task_id)
        assert task is not None
        task.status = "RUNNING"
        task.attempt = 1
        task.lease_owner = "dead-process"
        task.lease_expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
    monkeypatch.setattr(trusted_query, "run_trusted_query_task", real_runner)

    client.get(f"{QUERY_PATH}/tasks/{task_id}", headers=auth_headers["exchange"])

    with SessionLocal() as db:
        recovered = db.get(TrustedQueryTask, task_id)
        assert recovered is not None
        assert recovered.status == "SUCCEEDED"
        assert recovered.attempt == 2
        assert recovered.lease_owner is None
    assert len(calls) == 1


def test_atomic_lease_allows_only_one_worker_to_dispatch(client, auth_headers, monkeypatch):
    authorization_id, private_key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    calls = _install_success_connector(monkeypatch, private_key)
    real_runner = trusted_query.run_trusted_query_task
    monkeypatch.setattr(trusted_query, "run_trusted_query_task", lambda _task_id: None)
    accepted = _execute(client, auth_headers["exchange"], body, "atomic-lease")
    task_id = accepted.json()["task_id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(real_runner, task_id) for _ in range(2)]
        for future in futures:
            future.result(timeout=10)

    with SessionLocal() as db:
        completed = db.get(TrustedQueryTask, task_id)
        assert completed is not None
        assert completed.status == "SUCCEEDED"
        assert completed.attempt == 1
    assert len(calls) == 1


def test_retry_reuses_connector_task_and_request_item_ids(client, auth_headers, monkeypatch):
    authorization_id, private_key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    calls: list[dict[str, Any]] = []

    def flaky_post(url: str, *, json: dict[str, Any], headers: dict[str, str], timeout: float):
        calls.append(json)
        if len(calls) == 1:
            raise httpx.ReadTimeout(
                "response lost",
                request=httpx.Request("POST", "https://connector.example/compute"),
            )
        return _signed_connector_response(json, private_key)

    monkeypatch.setattr(trusted_query.httpx, "post", flaky_post)
    accepted = _execute(client, auth_headers["exchange"], body, "retry-response-lost")
    task_id = accepted.json()["task_id"]
    with SessionLocal() as db:
        pending = db.get(TrustedQueryTask, task_id)
        assert pending is not None
        assert pending.status == "PENDING_RETRY"
        pending.next_attempt_at = utc_now() - timedelta(seconds=1)
        db.commit()

    client.get(f"{QUERY_PATH}/tasks/{task_id}", headers=auth_headers["exchange"])

    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert calls[0]["task_id"] == task_id
    assert calls[0]["request_item_id"]
    with SessionLocal() as db:
        completed = db.get(TrustedQueryTask, task_id)
        assert completed is not None
        assert completed.status == "SUCCEEDED"
        assert completed.attempt == 2
        assert db.scalar(
            select(func.count(PrivacyComputeJob.job_id)).where(
                PrivacyComputeJob.task_id == task_id
            )
        ) == 1
        assert db.scalar(
            select(func.count(ExecutionReceipt.receipt_id)).where(
                ExecutionReceipt.request_item_id == completed.request_item_id
            )
        ) == 1
        assert db.scalar(
            select(func.count(DataRequestItem.request_item_id)).where(
                DataRequestItem.request_item_id == completed.request_item_id
            )
        ) == 1


def test_dispatch_keeps_the_authorized_version_when_a_newer_version_exists(
    client, auth_headers, monkeypatch
):
    authorization_id, private_key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    calls = _install_success_connector(monkeypatch, private_key)
    real_runner = trusted_query.run_trusted_query_task
    monkeypatch.setattr(trusted_query, "run_trusted_query_task", lambda _task_id: None)
    accepted = _execute(client, auth_headers["exchange"], body, "version-pinned")
    task_id = accepted.json()["task_id"]
    authorized_version: tuple[int, str, str] | None = None
    with SessionLocal() as db:
        authorization = db.get(DataUsageRequest, authorization_id)
        assert authorization is not None
        asset = db.get(DataAsset, authorization.asset_id)
        current = db.get(DataAssetVersion, authorization.asset_version_id)
        assert asset is not None and current is not None
        authorized_version = (current.version_no, current.data_ref, current.data_hash)
        replacement = DataAssetVersion(
            version_id=new_id(),
            asset_id=asset.asset_id,
            version_no=current.version_no + 1,
            schema_version=current.schema_version,
            schema_json=current.schema_json,
            data_ref="connector://node/generation/versions/2",
            data_hash=sha256_json({"asset": asset.asset_id, "version": 2}),
            record_count=3,
            immutable_hash=sha256_json({"asset": asset.asset_id, "immutable": 2}),
            status="ACTIVE",
        )
        db.add(replacement)
        db.flush()
        asset.current_version_id = replacement.version_id
        db.commit()
    monkeypatch.setattr(trusted_query, "run_trusted_query_task", real_runner)

    client.get(f"{QUERY_PATH}/tasks/{task_id}", headers=auth_headers["exchange"])

    with SessionLocal() as db:
        completed = db.get(TrustedQueryTask, task_id)
        assert completed is not None
        assert completed.status == "SUCCEEDED"
        assert completed.failure_code is None
    assert authorized_version is not None
    assert len(calls) == 1
    assert (
        calls[0]["dataset_version"],
        calls[0]["dataset_local_ref"],
        calls[0]["dataset_content_hash"],
    ) == authorized_version


def test_dispatch_fails_closed_if_authorization_version_binding_is_tampered(
    client, auth_headers, monkeypatch
):
    authorization_id, private_key = _prepare_authorization()
    body = _query_body(client, auth_headers["exchange"], authorization_id)
    calls = _install_success_connector(monkeypatch, private_key)
    real_runner = trusted_query.run_trusted_query_task
    monkeypatch.setattr(trusted_query, "run_trusted_query_task", lambda _task_id: None)
    accepted = _execute(client, auth_headers["exchange"], body, "version-tampered")
    task_id = accepted.json()["task_id"]
    with SessionLocal() as db:
        task = db.get(TrustedQueryTask, task_id)
        authorization = db.get(DataUsageRequest, authorization_id)
        assert task is not None and authorization is not None
        asset = db.get(DataAsset, task.asset_id)
        current = db.get(DataAssetVersion, task.asset_version_id)
        assert asset is not None and current is not None
        replacement = DataAssetVersion(
            version_id=new_id(),
            asset_id=asset.asset_id,
            version_no=current.version_no + 1,
            schema_version=current.schema_version,
            schema_json=current.schema_json,
            data_ref="connector://node/generation/versions/2",
            data_hash=sha256_json({"asset": asset.asset_id, "version": 2}),
            record_count=3,
            immutable_hash=sha256_json({"asset": asset.asset_id, "immutable": 2}),
            status="ACTIVE",
        )
        db.add(replacement)
        db.flush()
        authorization.asset_version_id = replacement.version_id
        db.commit()
    monkeypatch.setattr(trusted_query, "run_trusted_query_task", real_runner)

    client.get(f"{QUERY_PATH}/tasks/{task_id}", headers=auth_headers["exchange"])

    with SessionLocal() as db:
        failed = db.get(TrustedQueryTask, task_id)
        assert failed is not None
        assert failed.status == "FAILED"
        assert failed.failure_code == "AUTHORIZATION_SCOPE_CHANGED"
    assert calls == []
