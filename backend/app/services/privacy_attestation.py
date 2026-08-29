from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from ..security import canonical_json, sha256_json


class PrivacyAttestationError(ValueError):
    """Raised when a connector cannot prove the declared non-export boundary."""


class ConnectorAuditError(ValueError):
    """Raised when a signed connector audit pointer is incomplete or unbound."""


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MAX_AUDIT_EVENT_AGE = timedelta(minutes=10)
_MAX_AUDIT_EVENT_FUTURE_SKEW = timedelta(seconds=60)


def _verified_audit_event_pointer(
    signed_result: Mapping[str, Any],
    *,
    expected_action: str,
    expected_connector_id: str,
    expected_provider_org_id: str,
    expected_energy_domain: str,
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    sequence = signed_result.get("audit_sequence")
    previous_hash = signed_result.get("previous_audit_hash")
    audit_hash = signed_result.get("audit_hash")
    event = signed_result.get("audit_event")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0:
        raise ConnectorAuditError("connector audit sequence is invalid")
    if not isinstance(previous_hash, str) or not _SHA256_PATTERN.fullmatch(previous_hash):
        raise ConnectorAuditError("connector previous audit hash is invalid")
    if not isinstance(audit_hash, str) or not _SHA256_PATTERN.fullmatch(audit_hash):
        raise ConnectorAuditError("connector audit hash is invalid")
    if not isinstance(event, Mapping):
        raise ConnectorAuditError("connector audit event is missing")
    if (
        event.get("action") != expected_action
        or event.get("connector_id") != expected_connector_id
        or event.get("organization_id") != expected_provider_org_id
        or event.get("energy_domain") != expected_energy_domain
    ):
        raise ConnectorAuditError("connector audit event identity is invalid")
    occurred_at = event.get("occurred_at")
    if not isinstance(occurred_at, str):
        raise ConnectorAuditError("connector audit timestamp is invalid")
    try:
        parsed_occurred_at = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConnectorAuditError("connector audit timestamp is invalid") from exc
    if parsed_occurred_at.tzinfo is None:
        raise ConnectorAuditError("connector audit timestamp must include a timezone")
    platform_received_at = datetime.now(UTC)
    declared_at = parsed_occurred_at.astimezone(UTC)
    if declared_at < platform_received_at - _MAX_AUDIT_EVENT_AGE:
        raise ConnectorAuditError("connector audit event is stale")
    if declared_at > platform_received_at + _MAX_AUDIT_EVENT_FUTURE_SKEW:
        raise ConnectorAuditError("connector audit event timestamp is in the future")
    expected_hash = hashlib.sha256(
        (previous_hash + canonical_json(dict(event))).encode("utf-8")
    ).hexdigest()
    if audit_hash != expected_hash:
        raise ConnectorAuditError("connector audit event hash is invalid")
    return event, {
        "status": "VERIFIED",
        "pointer_verified": True,
        "event_hash_verified": True,
        "verification_scope": "SINGLE_SIGNED_EVENT_POINTER",
        "action": expected_action,
        "connector_id": expected_connector_id,
        "organization_id": expected_provider_org_id,
        "energy_domain": expected_energy_domain,
        "sequence": sequence,
        "previous_hash": previous_hash,
        "audit_hash": audit_hash,
        "connector_declared_at": occurred_at,
        "platform_received_at": platform_received_at.isoformat(),
    }


def verify_connector_audit_pointer(
    signed_result: Mapping[str, Any],
    request_payload: Mapping[str, Any],
    *,
    expected_connector_id: str,
    expected_provider_org_id: str,
    expected_energy_domain: str,
    expected_task_id: str,
    expected_request_item_id: str,
) -> dict[str, Any]:
    """Verify a metadata-only pointer into the connector's local hash chain."""

    event, pointer = _verified_audit_event_pointer(
        signed_result,
        expected_action="LOCAL_CONTROLLED_RESULT_ISSUED",
        expected_connector_id=expected_connector_id,
        expected_provider_org_id=expected_provider_org_id,
        expected_energy_domain=expected_energy_domain,
    )

    expected_top_level = {
        "connector_id": expected_connector_id,
        "provider_org_id": expected_provider_org_id,
        "energy_domain": expected_energy_domain,
        "task_id": expected_task_id,
        "request_item_id": expected_request_item_id,
        "authorization_id": request_payload.get("authorization_id"),
        "rule_version": request_payload.get("rule_version"),
    }
    if any(signed_result.get(key) != value for key, value in expected_top_level.items()):
        raise ConnectorAuditError("connector result identity is not bound to the request")

    result_payload = {
        key: value
        for key, value in signed_result.items()
        if key
        not in {
            "audit_sequence",
            "previous_audit_hash",
            "audit_hash",
            "audit_event",
        }
    }
    expected_event = {
        "action": "LOCAL_CONTROLLED_RESULT_ISSUED",
        "connector_id": expected_connector_id,
        "organization_id": expected_provider_org_id,
        "energy_domain": expected_energy_domain,
        "task_id": expected_task_id,
        "request_item_id": expected_request_item_id,
        "provider_org_id": expected_provider_org_id,
        "authorization_id": request_payload.get("authorization_id"),
        "request_hash": sha256_json(canonical_connector_request_payload(request_payload)),
        "result_payload_hash": sha256_json(result_payload),
        "record_count": signed_result.get("record_count"),
        "dataset_version": signed_result.get("dataset_version"),
        "raw_records_returned": False,
        "raw_data_exported": False,
    }
    if any(event.get(key) != value for key, value in expected_event.items()):
        raise ConnectorAuditError("connector audit event is not bound to the result")
    return pointer


def verify_dashboard_audit_pointer(
    signed_result: Mapping[str, Any],
    request_payload: Mapping[str, Any],
    *,
    expected_connector_id: str,
    expected_provider_org_id: str,
    expected_energy_domain: str,
) -> dict[str, Any]:
    """Verify a signed dashboard aggregate against one connector audit event pointer."""

    event, pointer = _verified_audit_event_pointer(
        signed_result,
        expected_action="DASHBOARD_AGGREGATE_ISSUED",
        expected_connector_id=expected_connector_id,
        expected_provider_org_id=expected_provider_org_id,
        expected_energy_domain=expected_energy_domain,
    )
    expected_top_level = {
        "request_id": request_payload.get("request_id"),
        "provider_org_id": expected_provider_org_id,
        "connector_id": expected_connector_id,
        "energy_domain": expected_energy_domain,
        "resource": request_payload.get("resource"),
        "aggregation": request_payload.get("aggregation"),
        "raw_records_returned": False,
    }
    if any(signed_result.get(key) != value for key, value in expected_top_level.items()):
        raise ConnectorAuditError("connector dashboard result is not bound to the request")
    result_payload = {
        key: value
        for key, value in signed_result.items()
        if key
        not in {
            "audit_sequence",
            "previous_audit_hash",
            "audit_hash",
            "audit_event",
        }
    }
    expected_event = {
        "request_id": request_payload.get("request_id"),
        "provider_org_id": expected_provider_org_id,
        "resource_id": request_payload.get("resource"),
        "request_hash": sha256_json(canonical_connector_request_payload(request_payload)),
        "result_payload_hash": sha256_json(result_payload),
        "record_count": signed_result.get("record_count"),
        "dataset_version": signed_result.get("dataset_version"),
    }
    if any(event.get(key) != value for key, value in expected_event.items()):
        raise ConnectorAuditError("connector dashboard audit event is not bound to the result")
    privacy = signed_result.get("privacy")
    if (
        signed_result.get("raw_records_returned") is not False
        or not isinstance(privacy, Mapping)
        or privacy.get("raw_records_returned") is not False
        or privacy.get("raw_data_exported") is not False
        or event.get("raw_records_returned") is not False
        or event.get("raw_data_exported") is not False
    ):
        raise ConnectorAuditError("connector dashboard audit asserts raw-data export")
    return pointer


def canonical_connector_request_payload(request_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the payload shape used by platform/connector signatures and hashes.

    Subject-bound fields are optional for legacy connector calls. A missing
    optional field is represented by Pydantic as ``None`` on the connector,
    so both sides must omit it before signing or hashing.
    """

    optional_subject_fields = {"request_item_id", "provider_org_id", "rule_version"}
    return {
        key: value
        for key, value in dict(request_payload).items()
        if key not in optional_subject_fields or value is not None
    }


def verify_signed_connector_non_export(
    signed_result: Mapping[str, Any],
    request_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify the software-level non-export claim carried by a signed result.

    The connector signs the complete result envelope.  This validator binds the
    claim to the exact request hash and requires aggregate-only output.  It is
    deliberately not a TEE or MPC attestation: it proves what the registered
    connector asserted, not that the connector host is physically trustworthy.
    """

    canonical_payload = canonical_connector_request_payload(request_payload)
    expected_request_hash = sha256_json(canonical_payload)
    # During a rolling deployment, an older connector may still hash the
    # Pydantic-expanded request, which contains the optional subject fields as
    # explicit nulls. It is the same semantic request, so accept that exact
    # legacy representation while returning the canonical hash to callers.
    legacy_payload = {
        **canonical_payload,
        **{
            field: None
            for field in ("request_item_id", "provider_org_id", "rule_version")
            if field not in canonical_payload
        },
    }
    accepted_request_hashes = {expected_request_hash, sha256_json(legacy_payload)}
    privacy = signed_result.get("privacy")
    nested_claim = privacy.get("non_export_attestation") if isinstance(privacy, Mapping) else None
    top_level_claim = signed_result.get("privacy_verification")
    if not isinstance(nested_claim, Mapping) or not isinstance(top_level_claim, Mapping):
        raise PrivacyAttestationError("connector non-export attestation is missing")

    legacy_missing_raw_flag = (
        "raw_records_returned" not in signed_result
        and isinstance(privacy, Mapping)
        and privacy.get("raw_records_returned") is False
        and isinstance(top_level_claim, Mapping)
        and top_level_claim.get("raw_data_exported") is False
    )
    if signed_result.get("raw_records_returned") is not False and not legacy_missing_raw_flag:
        raise PrivacyAttestationError("connector raw-records flag is not false")
    if privacy.get("raw_records_returned") is not False or privacy.get("raw_data_exported") is not False:
        raise PrivacyAttestationError("connector privacy boundary is not aggregate-only")
    if nested_claim.get("status") != "SIGNED" or top_level_claim.get("mode") != "SIGNED_CONNECTOR_NON_EXPORT":
        raise PrivacyAttestationError("connector non-export attestation status is invalid")
    issuer = str(nested_claim.get("issuer") or "")
    connector_id = str(signed_result.get("connector_id") or "")
    if not issuer or (connector_id and issuer != connector_id):
        raise PrivacyAttestationError("connector non-export issuer is invalid")
    if nested_claim.get("boundary") != "CONNECTOR_LOCAL_DATA":
        raise PrivacyAttestationError("connector non-export boundary is invalid")
    if nested_claim.get("result_scope") != "AGGREGATE_ONLY" or top_level_claim.get("result_scope") != "AGGREGATE_ONLY":
        raise PrivacyAttestationError("connector result scope is not aggregate-only")
    if (
        nested_claim.get("request_hash") not in accepted_request_hashes
        or top_level_claim.get("request_hash") not in accepted_request_hashes
    ):
        raise PrivacyAttestationError("connector non-export attestation is bound to another request")
    if nested_claim.get("raw_data_exported") is not False or top_level_claim.get("raw_data_exported") is not False:
        raise PrivacyAttestationError("connector asserted raw-data export")

    def contains_forbidden_key(value: Any) -> bool:
        if isinstance(value, Mapping):
            return any(
                key in {"raw_records", "raw_payload", "source_records", "input_records"}
                or contains_forbidden_key(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(contains_forbidden_key(item) for item in value)
        return False

    if contains_forbidden_key(signed_result):
        raise PrivacyAttestationError("connector returned a raw-data field")

    return {
        "mode": "SIGNED_CONNECTOR_NON_EXPORT",
        "status": "VERIFIED",
        "issuer": str(nested_claim.get("issuer") or "UNKNOWN_CONNECTOR"),
        "boundary": "CONNECTOR_LOCAL_DATA",
        "request_hash": expected_request_hash,
        "result_scope": "AGGREGATE_ONLY",
        "raw_records_returned": False,
        "raw_data_exported": False,
        "signature_claim_verified": True,
    }
