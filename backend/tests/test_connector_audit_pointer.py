from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from app.security import canonical_json, sha256_json
from app.services.privacy_attestation import (
    ConnectorAuditError,
    verify_connector_audit_pointer,
)


def _signed_result() -> tuple[dict[str, object], dict[str, object]]:
    occurred_at = datetime.now(UTC).isoformat()
    request = {
        "task_id": "task-1",
        "authorization_id": "authorization-1",
        "request_item_id": "request-item-1",
        "provider_org_id": "org-generator-t01",
        "rule_version": 3,
        "resource": "generation",
        "function": "average",
    }
    result: dict[str, object] = {
        "task_id": "task-1",
        "authorization_id": "authorization-1",
        "request_item_id": "request-item-1",
        "provider_org_id": "org-generator-t01",
        "rule_version": 3,
        "connector_id": "local-node-org-generator-t01",
        "energy_domain": "electricity",
        "result": 12.5,
        "unit": "MWh",
        "record_count": 2,
        "dataset_version": "version-1",
        "raw_records_returned": False,
    }
    event = {
        "action": "LOCAL_CONTROLLED_RESULT_ISSUED",
        "task_id": "task-1",
        "authorization_id": "authorization-1",
        "request_item_id": "request-item-1",
        "provider_org_id": "org-generator-t01",
        "request_hash": sha256_json(request),
        "result_payload_hash": sha256_json(result),
        "record_count": 2,
        "dataset_version": "version-1",
        "raw_records_returned": False,
        "raw_data_exported": False,
        "connector_id": "local-node-org-generator-t01",
        "organization_id": "org-generator-t01",
        "energy_domain": "electricity",
        "occurred_at": occurred_at,
    }
    previous_hash = "0" * 64
    result.update(
        {
            "audit_sequence": 1,
            "previous_audit_hash": previous_hash,
            "audit_hash": sha256_json_string(previous_hash + canonical_json(event)),
            "audit_event": event,
        }
    )
    return request, result


def sha256_json_string(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _verify(request: dict[str, object], result: dict[str, object]) -> dict[str, object]:
    return verify_connector_audit_pointer(
        result,
        request,
        expected_connector_id="local-node-org-generator-t01",
        expected_provider_org_id="org-generator-t01",
        expected_energy_domain="electricity",
        expected_task_id="task-1",
        expected_request_item_id="request-item-1",
    )


def test_connector_audit_pointer_binds_result_request_and_identity() -> None:
    request, result = _signed_result()

    verified = _verify(request, result)

    assert {key: value for key, value in verified.items() if key != "platform_received_at"} == {
        "status": "VERIFIED",
        "pointer_verified": True,
        "event_hash_verified": True,
        "verification_scope": "SINGLE_SIGNED_EVENT_POINTER",
        "action": "LOCAL_CONTROLLED_RESULT_ISSUED",
        "connector_id": "local-node-org-generator-t01",
        "organization_id": "org-generator-t01",
        "energy_domain": "electricity",
        "sequence": 1,
        "previous_hash": "0" * 64,
        "audit_hash": result["audit_hash"],
        "connector_declared_at": result["audit_event"]["occurred_at"],
    }
    assert datetime.fromisoformat(str(verified["platform_received_at"])).tzinfo is not None


def test_audit_pointer_does_not_claim_chain_continuity() -> None:
    request, result = _signed_result()
    result["audit_sequence"] = 99
    result["previous_audit_hash"] = "a" * 64
    result["audit_hash"] = sha256_json_string(
        str(result["previous_audit_hash"]) + canonical_json(result["audit_event"])
    )

    verified = _verify(request, result)

    assert verified["pointer_verified"] is True
    assert verified["event_hash_verified"] is True
    assert verified["verification_scope"] == "SINGLE_SIGNED_EVENT_POINTER"
    assert verified["sequence"] == 99
    assert not any(
        key.endswith("chain_verified") and value is True
        for key, value in verified.items()
    )


@pytest.mark.parametrize(
    "occurred_at",
    [
        lambda: datetime.now(UTC) - timedelta(minutes=11),
        lambda: datetime.now(UTC) + timedelta(seconds=61),
    ],
)
def test_audit_pointer_rejects_stale_or_future_event(occurred_at) -> None:
    request, result = _signed_result()
    result["audit_event"]["occurred_at"] = occurred_at().isoformat()
    result["audit_hash"] = sha256_json_string(
        str(result["previous_audit_hash"]) + canonical_json(result["audit_event"])
    )

    with pytest.raises(ConnectorAuditError):
        _verify(request, result)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("audit_hash",), "f" * 64),
        (("audit_event", "request_hash"), "f" * 64),
        (("audit_event", "result_payload_hash"), "f" * 64),
        (("audit_event", "connector_id"), "attacker-node"),
        (("audit_event", "organization_id"), "org-attacker"),
        (("audit_event", "raw_data_exported"), True),
        (("task_id",), "task-attacker"),
    ],
)
def test_connector_audit_pointer_rejects_tampering(
    path: tuple[str, ...], value: object
) -> None:
    request, original = _signed_result()
    result = deepcopy(original)
    target: dict[str, object] = result
    for key in path[:-1]:
        target = target[key]  # type: ignore[assignment]
    target[path[-1]] = value

    with pytest.raises(ConnectorAuditError):
        _verify(request, result)
