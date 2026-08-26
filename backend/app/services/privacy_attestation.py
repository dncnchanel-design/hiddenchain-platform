from __future__ import annotations

from typing import Any, Mapping

from ..security import sha256_json


class PrivacyAttestationError(ValueError):
    """Raised when a connector cannot prove the declared non-export boundary."""


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

    expected_request_hash = sha256_json(dict(request_payload))
    privacy = signed_result.get("privacy")
    nested_claim = privacy.get("non_export_attestation") if isinstance(privacy, Mapping) else None
    top_level_claim = signed_result.get("privacy_verification")
    if not isinstance(nested_claim, Mapping) or not isinstance(top_level_claim, Mapping):
        raise PrivacyAttestationError("connector non-export attestation is missing")

    if signed_result.get("raw_records_returned") is not False:
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
    if nested_claim.get("request_hash") != expected_request_hash or top_level_claim.get("request_hash") != expected_request_hash:
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
