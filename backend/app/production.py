from __future__ import annotations

import base64
import hashlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .config import (
    Settings,
    VAULT_DIR,
    parse_subject_map,
    parse_subject_public_key_rings,
    settings as runtime_settings,
)
from .models import (
    BlockchainEvidence,
    DataRequestBatch,
    DataRequestItem,
    DataUsageRequest,
    ExecutionReceipt,
    Organization,
    PrivacyComputeJob,
    SettlementResult,
    SettlementTask,
    TrustedQueryTask,
    User,
)
from .security import canonical_json, sha256_json
from .services.privacy_attestation import (
    PrivacyAttestationError,
    canonical_connector_request_payload,
    verify_signed_connector_non_export,
)
from .services.trusted_query_results import (
    TrustedQueryProjectionError,
    build_trusted_query_public_result,
    validated_trend,
)
from .services.trust_domain import ExecutionSnapshotService
from .trust_models import DataAsset, DataAssetVersion, ExecutionSnapshot, TtcAttempt


NON_PRODUCTION_USERNAMES = {
    "generator",
    "retailer",
    "exchange",
    "regulator",
    "admin",
}

LOCAL_SETTLEMENT_ADAPTER = "LOCAL_CONTROLLED_SETTLEMENT_V1"
LOCAL_SUBJECT_NODE_ADAPTER_PREFIX = "LOCAL_SUBJECT_NODE_"
LEGACY_ENTERPRISE_ADAPTER = re.compile(
    r"^ENTERPRISE_CONNECTOR_(ELECTRICITY|COAL|HEAT|GAS|OIL)$"
)
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
TRUSTED_QUERY_RECEIPT_SCHEMA = "TRUSTED_QUERY_RECEIPT_V2"
_SIGNED_RESULT_METADATA_FIELDS = {
    "signature",
    "public_key",
    "signature_algorithm",
    "signature_valid",
}
_SIGNED_RESULT_AUDIT_FIELDS = {
    "audit_sequence",
    "previous_audit_hash",
    "audit_hash",
    "audit_event",
}
_MAX_AUDIT_EVENT_AGE = timedelta(minutes=10)
_MAX_AUDIT_EVENT_FUTURE_SKEW = timedelta(seconds=60)


def _configured_connector_id(settings_value: Settings, provider_org_id: str) -> str | None:
    return parse_subject_map(settings_value.subject_node_ids_json).get(provider_org_id)


def _trusted_public_keys(
    settings_value: Settings,
    provider_org_id: str,
) -> tuple[tuple[str, str, Ed25519PublicKey], ...]:
    active_key = parse_subject_map(settings_value.subject_node_public_keys_json).get(
        provider_org_id
    )
    retired_keys = parse_subject_public_key_rings(
        settings_value.subject_node_public_key_rings_json
    ).get(provider_org_id, ())
    candidates: list[tuple[str, str, Ed25519PublicKey]] = []
    for encoded in dict.fromkeys((active_key, *retired_keys)):
        if not encoded:
            continue
        try:
            key_bytes = base64.b64decode(encoded, validate=True)
            public_key = Ed25519PublicKey.from_public_bytes(key_bytes)
        except Exception:
            continue
        candidates.append((hashlib.sha256(key_bytes).hexdigest(), encoded, public_key))
    return tuple(candidates)


def _verify_deployment_signature(
    *,
    signed_result: dict,
    encoded_signature: str,
    trusted_keys: tuple[tuple[str, str, Ed25519PublicKey], ...],
    expected_fingerprint: str | None = None,
) -> tuple[str, str] | None:
    try:
        signature = base64.b64decode(encoded_signature, validate=True)
    except Exception:
        return None
    message = canonical_json(signed_result).encode("utf-8")
    for fingerprint, encoded_key, public_key in trusted_keys:
        if expected_fingerprint and fingerprint != expected_fingerprint:
            continue
        try:
            public_key.verify(signature, message)
        except Exception:
            continue
        return fingerprint, encoded_key
    return None


def _parse_utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _durable_audit_pointer_is_valid(
    *,
    signed_result: dict,
    pointer: dict,
    receipt: ExecutionReceipt,
    task: TrustedQueryTask,
    connector_id: str,
) -> bool:
    sequence = signed_result.get("audit_sequence")
    previous_hash = signed_result.get("previous_audit_hash")
    audit_hash = signed_result.get("audit_hash")
    event = signed_result.get("audit_event")
    if (
        isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or sequence < 1
        or not isinstance(previous_hash, str)
        or not SHA256_HEX.fullmatch(previous_hash)
        or not isinstance(audit_hash, str)
        or not SHA256_HEX.fullmatch(audit_hash)
        or not isinstance(event, dict)
    ):
        return False
    if hashlib.sha256(
        (previous_hash + canonical_json(event)).encode("utf-8")
    ).hexdigest() != audit_hash:
        return False
    result_without_audit = {
        key: value
        for key, value in signed_result.items()
        if key not in _SIGNED_RESULT_AUDIT_FIELDS
    }
    expected_event = {
        "action": "LOCAL_CONTROLLED_RESULT_ISSUED",
        "connector_id": connector_id,
        "organization_id": task.provider_org_id,
        "energy_domain": (task.canonical_payload_json or {}).get("energy_domain"),
        "task_id": task.task_id,
        "request_item_id": task.request_item_id,
        "provider_org_id": task.provider_org_id,
        "authorization_id": task.authorization_id,
        "request_hash": receipt.request_hash,
        "result_payload_hash": sha256_json(result_without_audit),
        "record_count": signed_result.get("record_count"),
        "dataset_version": signed_result.get("dataset_version"),
        "raw_records_returned": False,
        "raw_data_exported": False,
    }
    if any(event.get(key) != value for key, value in expected_event.items()):
        return False
    expected_pointer = {
        "status": "VERIFIED",
        "pointer_verified": True,
        "event_hash_verified": True,
        "verification_scope": "SINGLE_SIGNED_EVENT_POINTER",
        "action": "LOCAL_CONTROLLED_RESULT_ISSUED",
        "connector_id": connector_id,
        "organization_id": task.provider_org_id,
        "energy_domain": (task.canonical_payload_json or {}).get("energy_domain"),
        "sequence": sequence,
        "previous_hash": previous_hash,
        "audit_hash": audit_hash,
        "connector_declared_at": event.get("occurred_at"),
    }
    if any(pointer.get(key) != value for key, value in expected_pointer.items()):
        return False
    declared_at = _parse_utc_timestamp(event.get("occurred_at"))
    received_at = _parse_utc_timestamp(pointer.get("platform_received_at"))
    if declared_at is None or received_at is None:
        return False
    if (
        declared_at < received_at - _MAX_AUDIT_EVENT_AGE
        or declared_at > received_at + _MAX_AUDIT_EVENT_FUTURE_SKEW
        or abs((_as_utc(receipt.executed_at) - received_at).total_seconds()) > 900
    ):
        return False
    return (
        receipt.audit_sequence == sequence
        and receipt.previous_audit_hash == previous_hash
        and receipt.connector_audit_hash == audit_hash
        and receipt.audit_event_verified is True
    )


def _connector_request_payload_for_record(
    *,
    task: TrustedQueryTask,
    authorization: DataUsageRequest,
    version: DataAssetVersion,
    request_item: DataRequestItem,
) -> dict:
    payload = task.canonical_payload_json or {}
    return canonical_connector_request_payload(
        {
            "task_id": task.task_id,
            "authorization_id": authorization.request_id,
            "request_item_id": request_item.request_item_id,
            "provider_org_id": authorization.provider_org_id,
            "rule_version": request_item.matched_rule_version,
            "dataset_version": version.version_no,
            "dataset_local_ref": version.data_ref,
            "dataset_content_hash": version.data_hash,
            "resource": payload.get("resource"),
            "function": payload.get("function"),
            "start_date": payload.get("start_date"),
            "end_date": payload.get("end_date"),
            "region": payload.get("region"),
            "hour": payload.get("hour"),
            "threshold": payload.get("threshold"),
            "group_by": payload.get("group_by"),
            "decimals": payload.get("decimals"),
        }
    )


def _current_record_relations(
    db: Session,
    *,
    task: TrustedQueryTask,
    job: PrivacyComputeJob,
    receipt: ExecutionReceipt,
) -> tuple[DataUsageRequest, DataRequestItem, DataAsset, DataAssetVersion] | None:
    user = db.get(User, task.applicant_user_id)
    authorization = db.get(DataUsageRequest, task.authorization_id)
    request_item = db.get(DataRequestItem, task.request_item_id)
    asset = db.get(DataAsset, task.asset_id)
    version = db.get(DataAssetVersion, task.asset_version_id)
    if any(item is None for item in (user, authorization, request_item, asset, version)):
        return None
    assert authorization is not None
    assert request_item is not None
    assert asset is not None
    assert version is not None
    batch = db.get(DataRequestBatch, request_item.batch_id)
    canonical_payload = task.canonical_payload_json or {}
    stored_fingerprint = task.request_fingerprint
    fingerprint_payload = dict(canonical_payload)
    current_fingerprint = sha256_json(fingerprint_payload)
    if "confirmation_token_hash" in fingerprint_payload:
        fingerprint_payload.pop("confirmation_token_hash", None)
    legacy_fingerprint = sha256_json(fingerprint_payload)
    if (
        batch is None
        or task.operation_namespace != "TRUSTED_QUERY_EXECUTE_V1"
        or stored_fingerprint not in {current_fingerprint, legacy_fingerprint}
        or canonical_payload.get("authorization_id") != task.authorization_id
        or canonical_payload.get("provider_org_id") != task.provider_org_id
        or user.org_id != task.applicant_org_id
        or authorization.applicant_user_id != task.applicant_user_id
        or authorization.applicant_org_id != task.applicant_org_id
        or authorization.provider_org_id != task.provider_org_id
        or authorization.asset_id != task.asset_id
        or authorization.asset_version_id != task.asset_version_id
        or request_item.authorization_id != task.authorization_id
        or request_item.provider_org_id != task.provider_org_id
        or request_item.asset_id != task.asset_id
        or request_item.status != "SUCCEEDED"
        or request_item.result_hash != job.output_hash
        or request_item.result_json != job.result_json
        or batch.applicant_user_id != task.applicant_user_id
        or batch.applicant_org_id != task.applicant_org_id
        or asset.owner_org_id != task.provider_org_id
        or version.asset_id != task.asset_id
        or (asset.metadata_json or {}).get("domain")
        != canonical_payload.get("energy_domain")
        or (asset.metadata_json or {}).get("resource_id")
        != canonical_payload.get("resource")
        or job.algorithm_code != canonical_payload.get("function")
        or list(job.input_hashes_json or [])
        != [authorization.decision_hash or authorization.request_fingerprint]
        or list(receipt.visible_to_orgs_json or [])
        != [task.applicant_org_id, task.provider_org_id]
    ):
        return None
    return authorization, request_item, asset, version


def _expected_current_public_result(
    *,
    task: TrustedQueryTask,
    job: PrivacyComputeJob,
    signed_result: dict,
    connector_audit: dict,
    privacy_verification: dict,
) -> dict | None:
    try:
        return build_trusted_query_public_result(
            task_id=task.task_id,
            job_id=job.job_id,
            request_item_id=task.request_item_id,
            authorization_id=task.authorization_id,
            canonical_payload=task.canonical_payload_json or {},
            attempt=task.attempt,
            asset_version_id=task.asset_version_id,
            signed_result=signed_result,
            connector_audit=connector_audit,
            privacy_verification=privacy_verification,
            receipt_schema=TRUSTED_QUERY_RECEIPT_SCHEMA,
        )
    except TrustedQueryProjectionError:
        return None


def _contains_forbidden_raw_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            key in {"raw_records", "raw_payload", "source_records", "input_records"}
            or _contains_forbidden_raw_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_raw_key(item) for item in value)
    return False


def _legacy_signed_subject_record_is_valid(
    db: Session,
    *,
    job: PrivacyComputeJob,
    receipt: ExecutionReceipt,
    provider_org_id: str,
    connector_id: str,
    trusted_keys: tuple[tuple[str, str, Ed25519PublicKey], ...],
) -> bool:
    """Verify the two deployed pre-V2 generations as read-only records."""

    response = job.result_json
    attestation = job.execution_attestation_json
    guarantees = job.privacy_guarantees_json
    if not all(isinstance(item, dict) for item in (response, attestation, guarantees)):
        return False
    request_item = db.get(DataRequestItem, receipt.request_item_id)
    authorization_id = attestation.get("authorization_id")
    authorization = (
        db.get(DataUsageRequest, authorization_id)
        if isinstance(authorization_id, str)
        else None
    )
    asset = db.get(DataAsset, authorization.asset_id) if authorization else None
    batch = db.get(DataRequestBatch, request_item.batch_id) if request_item else None
    if any(item is None for item in (request_item, authorization, asset, batch)):
        return False
    assert request_item is not None
    assert authorization is not None
    assert asset is not None
    assert batch is not None
    signature = response.get("signature")
    signed_result = {
        key: value for key, value in response.items() if key not in _SIGNED_RESULT_METADATA_FIELDS
    }
    stored_item_result = request_item.result_json or {}
    allowed_item_results = (
        response,
        {
            **response,
            "_hiddenchain_task_id": job.task_id,
            "_hiddenchain_job_id": job.job_id,
        },
    )
    if (
        not isinstance(signature, str)
        or response.get("signature_algorithm") != "Ed25519"
        or any(field in signed_result for field in _SIGNED_RESULT_AUDIT_FIELDS)
        or attestation.get("receipt_verification_schema") is not None
        or guarantees.get("receipt_verification_schema") is not None
        or receipt.node_signature != signature
        or sha256_json(signed_result) != job.output_hash
        # Pre-V2 rows did not persist the complete connector request. Keep the
        # stored receipt hash structurally valid; reconstructing it from the
        # smaller historical scope would reject legitimate optional fields.
        or not SHA256_HEX.fullmatch(receipt.request_hash or "")
        or stored_item_result not in allowed_item_results
        or request_item.result_hash != job.output_hash
        or request_item.status != "SUCCEEDED"
        or request_item.authorization_id != authorization.request_id
        or request_item.provider_org_id != provider_org_id
        or request_item.asset_id != authorization.asset_id
        or authorization.provider_org_id != provider_org_id
        or authorization.applicant_org_id != attestation.get("applicant_org_id")
        or batch.applicant_org_id != authorization.applicant_org_id
        or batch.applicant_user_id != authorization.applicant_user_id
        or asset.owner_org_id != provider_org_id
        or job.algorithm_code != (request_item.scope_json or {}).get("function")
        or list(job.input_hashes_json or [])
        != [authorization.decision_hash or authorization.request_fingerprint]
        or list(receipt.visible_to_orgs_json or [])
        != [authorization.applicant_org_id, provider_org_id]
        or _contains_forbidden_raw_key(signed_result)
    ):
        return False
    verified = _verify_deployment_signature(
        signed_result=signed_result,
        encoded_signature=signature,
        trusted_keys=trusted_keys,
    )
    if verified is None:
        return False
    _fingerprint, verified_key = verified
    if response.get("public_key") != verified_key:
        return False
    required_identity = {
        "task_id": job.task_id,
        "request_item_id": receipt.request_item_id,
        "provider_org_id": provider_org_id,
        "authorization_id": authorization.request_id,
        "connector_id": connector_id,
    }
    if any(signed_result.get(key) != value for key, value in required_identity.items()):
        return False
    required_attestation_identity = {
        "connector_signature_verified": True,
        "signature_algorithm": "Ed25519",
        "raw_records_returned": False,
        "authorization_id": authorization.request_id,
        "applicant_org_id": authorization.applicant_org_id,
        "provider_org_id": provider_org_id,
        "request_item_id": receipt.request_item_id,
        "node_code": connector_id,
    }
    if (
        any(attestation.get(key) != value for key, value in required_attestation_identity.items())
        or receipt.node_code != connector_id
        or receipt.audit_sequence is not None
        or receipt.previous_audit_hash is not None
        or receipt.connector_audit_hash is not None
        or receipt.audit_event_verified is True
    ):
        return False
    privacy = signed_result.get("privacy")
    if not isinstance(privacy, dict) or privacy.get("raw_records_returned") is not False:
        return False
    has_non_export_claim = (
        isinstance(privacy.get("non_export_attestation"), dict)
        or isinstance(signed_result.get("privacy_verification"), dict)
    )
    if not has_non_export_claim:
        # Earliest signed generation: only the result signature is verifiable;
        # exact request binding and cross-domain non-export were not attested.
        return (
            guarantees == privacy
            and "raw_data_exported" not in attestation
            and "cross_domain_non_export_verified" not in attestation
            and receipt.result_summary_json
            == {
                "result": signed_result.get("result"),
                "unit": signed_result.get("unit"),
                "record_count": signed_result.get("record_count"),
                "raw_records_returned": False,
            }
        )

    nested_claim = privacy.get("non_export_attestation")
    top_level_claim = signed_result.get("privacy_verification")
    if not isinstance(nested_claim, dict) or not isinstance(top_level_claim, dict):
        return False
    if (
        privacy.get("raw_data_exported") is not False
        or nested_claim.get("status") != "SIGNED"
        or nested_claim.get("issuer") != connector_id
        or nested_claim.get("boundary") != "CONNECTOR_LOCAL_DATA"
        or nested_claim.get("request_hash") != receipt.request_hash
        or nested_claim.get("result_scope") != "AGGREGATE_ONLY"
        or nested_claim.get("raw_data_exported") is not False
        or top_level_claim.get("mode") != "SIGNED_CONNECTOR_NON_EXPORT"
        or top_level_claim.get("request_hash") != receipt.request_hash
        or top_level_claim.get("result_scope") != "AGGREGATE_ONLY"
        or top_level_claim.get("raw_data_exported") is not False
    ):
        return False
    try:
        trend = validated_trend(signed_result.get("trend"))
    except TrustedQueryProjectionError:
        return False
    privacy_verification = {
        "mode": "SIGNED_CONNECTOR_NON_EXPORT",
        "status": "VERIFIED",
        "issuer": connector_id,
        "boundary": "CONNECTOR_LOCAL_DATA",
        "request_hash": receipt.request_hash,
        "result_scope": "AGGREGATE_ONLY",
        "raw_records_returned": False,
        "raw_data_exported": False,
        "signature_claim_verified": True,
        "result_hash": job.output_hash,
    }
    required_non_export = {
        "raw_data_exported": False,
        "execution_environment": "SUBJECT_CONNECTOR",
        "attestation_status": "CONNECTOR_SIGNED",
        "cross_domain_non_export_verified": True,
        "privacy_verification": privacy_verification,
    }
    return (
        all(attestation.get(key) == value for key, value in required_non_export.items())
        and all(guarantees.get(key) == value for key, value in required_non_export.items())
        and guarantees.get("connector_signature_verified") is True
        and guarantees.get("raw_records_returned") is False
        and receipt.result_summary_json
        == {
            "result": signed_result.get("result"),
            "unit": signed_result.get("unit"),
            "record_count": signed_result.get("record_count"),
            "trend": trend,
            "raw_records_returned": False,
            "raw_data_exported": False,
            "privacy_verification": privacy_verification,
        }
    )


def _is_supported_local_subject_compute_record(
    db: Session,
    job: PrivacyComputeJob,
    settings_value: Settings | None = None,
) -> bool:
    """Verify current or legacy connector receipts against deployment trust roots."""

    if not job.adapter_code.startswith(LOCAL_SUBJECT_NODE_ADAPTER_PREFIX):
        return False
    active_settings = settings_value or runtime_settings
    provider_org_id = job.adapter_code.removeprefix(LOCAL_SUBJECT_NODE_ADAPTER_PREFIX)
    connector_id = _configured_connector_id(active_settings, provider_org_id)
    trusted_keys = _trusted_public_keys(active_settings, provider_org_id)
    if not provider_org_id or not connector_id or not trusted_keys:
        return False
    if (
        job.status != "SUCCEEDED"
        or job.progress != 100
        or not SHA256_HEX.fullmatch(job.output_hash or "")
    ):
        return False
    receipts = db.scalars(
        select(ExecutionReceipt).where(
            ExecutionReceipt.task_id == job.task_id,
            ExecutionReceipt.provider_org_id == provider_org_id,
            ExecutionReceipt.result_hash == job.output_hash,
            ExecutionReceipt.node_code == connector_id,
            ExecutionReceipt.status == "CONFIRMED",
        )
    ).all()
    if len(receipts) != 1:
        return False
    receipt = receipts[0]
    task = db.get(TrustedQueryTask, job.task_id)
    if task is None:
        return _legacy_signed_subject_record_is_valid(
            db,
            job=job,
            receipt=receipt,
            provider_org_id=provider_org_id,
            connector_id=connector_id,
            trusted_keys=trusted_keys,
        )
    if (
        job.adapter_code != f"{LOCAL_SUBJECT_NODE_ADAPTER_PREFIX}{task.provider_org_id}"
        or task.status != "SUCCEEDED"
        or task.result_hash != job.output_hash
        or task.result_json != job.result_json
    ):
        return False
    relations = _current_record_relations(
        db,
        task=task,
        job=job,
        receipt=receipt,
    )
    if relations is None:
        return False
    authorization, request_item, asset, version = relations
    attestation = job.execution_attestation_json
    guarantees = job.privacy_guarantees_json
    result = job.result_json
    if not all(isinstance(item, dict) for item in (attestation, guarantees, result)):
        return False
    required_attestation = {
        "connector_signature_verified": True,
        "signature_algorithm": "Ed25519",
        "raw_records_returned": False,
        "raw_data_exported": False,
        "execution_environment": "SUBJECT_CONNECTOR",
        "attestation_status": "CONNECTOR_SIGNED",
        "cross_domain_non_export_verified": True,
        "connector_audit_event_verified": True,
        "receipt_verification_schema": TRUSTED_QUERY_RECEIPT_SCHEMA,
        "authorization_id": task.authorization_id,
        "applicant_org_id": task.applicant_org_id,
        "applicant_user_id": task.applicant_user_id,
        "provider_org_id": task.provider_org_id,
        "request_item_id": task.request_item_id,
    }
    if any(attestation.get(key) != value for key, value in required_attestation.items()):
        return False
    required_guarantees = {
        "connector_signature_verified": True,
        "raw_records_returned": False,
        "raw_data_exported": False,
        "execution_environment": "SUBJECT_CONNECTOR",
        "attestation_status": "CONNECTOR_SIGNED",
        "cross_domain_non_export_verified": True,
        "connector_audit_event_verified": True,
        "receipt_verification_schema": TRUSTED_QUERY_RECEIPT_SCHEMA,
    }
    if any(guarantees.get(key) != value for key, value in required_guarantees.items()):
        return False
    if (
        result.get("task_id") != task.task_id
        or result.get("job_id") != job.job_id
        or result.get("request_item_id") != task.request_item_id
        or result.get("authorization_scope") != task.authorization_id
        or result.get("raw_records_returned") is not False
    ):
        return False

    node_code = attestation.get("node_code")
    summary = receipt.result_summary_json
    verification_envelope = (
        summary.get("verification_envelope") if isinstance(summary, dict) else None
    )
    signed_result = (
        verification_envelope.get("signed_result")
        if isinstance(verification_envelope, dict)
        else None
    )
    signing_key_fingerprint = (
        verification_envelope.get("signing_key_fingerprint")
        if isinstance(verification_envelope, dict)
        else None
    )
    if (
        not isinstance(verification_envelope, dict)
        or verification_envelope.get("schema") != TRUSTED_QUERY_RECEIPT_SCHEMA
        or verification_envelope.get("verifier") != "ED25519_CANONICAL_JSON_V1"
        or not isinstance(signed_result, dict)
        or not isinstance(signing_key_fingerprint, str)
        or attestation.get("signing_key_fingerprint") != signing_key_fingerprint
        or guarantees.get("signing_key_fingerprint") != signing_key_fingerprint
        or sha256_json(signed_result) != job.output_hash
        or _verify_deployment_signature(
            signed_result=signed_result,
            encoded_signature=receipt.node_signature,
            trusted_keys=trusted_keys,
            expected_fingerprint=signing_key_fingerprint,
        )
        is None
    ):
        return False
    connector_audit = attestation.get("connector_audit")
    audit_sequence = (
        connector_audit.get("sequence") if isinstance(connector_audit, dict) else None
    )
    previous_audit_hash = (
        connector_audit.get("previous_hash")
        if isinstance(connector_audit, dict)
        else None
    )
    connector_audit_hash = (
        connector_audit.get("audit_hash") if isinstance(connector_audit, dict) else None
    )
    if (
        not isinstance(node_code, str)
        or not node_code.strip()
        or node_code != node_code.strip()
        or node_code != connector_id
        or not isinstance(connector_audit, dict)
        or isinstance(audit_sequence, bool)
        or not isinstance(audit_sequence, int)
        or audit_sequence < 1
        or not isinstance(previous_audit_hash, str)
        or not SHA256_HEX.fullmatch(previous_audit_hash)
        or not isinstance(connector_audit_hash, str)
        or not SHA256_HEX.fullmatch(connector_audit_hash)
        or connector_audit.get("pointer_verified") is not True
        or connector_audit.get("event_hash_verified") is not True
        or connector_audit.get("verification_scope") != "SINGLE_SIGNED_EVENT_POINTER"
        or guarantees.get("connector_audit") != connector_audit
        or result.get("connector_audit") != connector_audit
        or signed_result.get("task_id") != task.task_id
        or signed_result.get("authorization_id") != task.authorization_id
        or signed_result.get("request_item_id") != task.request_item_id
        or signed_result.get("rule_version") != request_item.matched_rule_version
        or signed_result.get("provider_org_id") != task.provider_org_id
        or signed_result.get("connector_id") != connector_id
        or signed_result.get("energy_domain")
        != (task.canonical_payload_json or {}).get("energy_domain")
        or signed_result.get("dataset_version") != version.version_no
        or signed_result.get("dataset_local_ref") != version.data_ref
        or signed_result.get("dataset_content_hash") != version.data_hash
    ):
        return False
    connector_payload = _connector_request_payload_for_record(
        task=task,
        authorization=authorization,
        version=version,
        request_item=request_item,
    )
    if sha256_json(connector_payload) != receipt.request_hash:
        return False
    try:
        recomputed_privacy_verification = verify_signed_connector_non_export(
            signed_result,
            connector_payload,
        )
    except PrivacyAttestationError:
        return False
    recomputed_privacy_verification = {
        **recomputed_privacy_verification,
        "result_hash": job.output_hash,
        "connector_audit": connector_audit,
    }
    expected_result = _expected_current_public_result(
        task=task,
        job=job,
        signed_result=signed_result,
        connector_audit=connector_audit,
        privacy_verification=recomputed_privacy_verification,
    )
    if expected_result is None or result != expected_result:
        return False
    if (
        attestation.get("privacy_verification") != recomputed_privacy_verification
        or guarantees.get("privacy_verification") != recomputed_privacy_verification
    ):
        return False
    expected_summary = {
        "result": signed_result.get("result"),
        "unit": signed_result.get("unit"),
        "record_count": signed_result.get("record_count"),
        "trend": expected_result["trend"],
        "raw_records_returned": False,
        "raw_data_exported": False,
        "connector_audit": connector_audit,
        "privacy_verification": recomputed_privacy_verification,
        "verification_envelope": verification_envelope,
    }
    if summary != expected_summary:
        return False
    return (
        receipt.request_item_id == task.request_item_id
        and _durable_audit_pointer_is_valid(
            signed_result=signed_result,
            pointer=connector_audit,
            receipt=receipt,
            task=task,
            connector_id=connector_id,
        )
    )


def _is_supported_local_settlement_compute_record(
    db: Session,
    *,
    job: PrivacyComputeJob,
    task: SettlementTask,
) -> bool:
    if (
        job.adapter_code != LOCAL_SETTLEMENT_ADAPTER
        or job.status != "SUCCESS"
        or job.progress != 100
        or not SHA256_HEX.fullmatch(job.output_hash or "")
        or job.output_hash != sha256_json(job.result_json or {})
        or _contains_forbidden_raw_key(job.result_json or {})
        or not job.attempt_id
        or not job.execution_snapshot_id
    ):
        return False
    attempt = db.get(TtcAttempt, job.attempt_id)
    snapshot = db.get(ExecutionSnapshot, job.execution_snapshot_id)
    if attempt is None or snapshot is None:
        return False
    try:
        ExecutionSnapshotService.verify(snapshot)
    except Exception:
        return False
    summaries = db.scalars(
        select(SettlementResult).where(
            SettlementResult.task_id == task.task_id,
            SettlementResult.attempt_id == job.attempt_id,
            SettlementResult.result_scope == "SUMMARY",
            SettlementResult.org_id.is_(None),
        )
    ).all()
    if len(summaries) != 1:
        return False
    summary = summaries[0]
    attestation = job.execution_attestation_json or {}
    guarantees = job.privacy_guarantees_json or {}
    required_attestation = {
        "runtime": "application-process",
        "attestation_status": "NOT_PROVIDED",
        "api_raw_records_returned": False,
        "cross_domain_non_export_verified": False,
        "deterministic_engine": "decimal-v1",
    }
    required_guarantees = {
        "api_raw_records_returned": False,
        "output_mode": "AGGREGATE_ONLY",
        "input_commitments_only": False,
        "execution_environment": "APPLICATION_PROCESS",
        "cross_domain_non_export_verified": False,
        "attestation_status": "NOT_PROVIDED",
        "strategy": LOCAL_SETTLEMENT_ADAPTER,
    }
    is_current_attempt = attempt.attempt_no == task.current_attempt
    current_pointer_is_valid = (
        snapshot.snapshot_id == task.execution_snapshot_id
        and snapshot.snapshot_hash == task.execution_snapshot_hash
    )
    return (
        attempt.task_id == task.task_id
        and attempt.capsule_id == task.capsule_id
        and 0 < attempt.attempt_no <= task.current_attempt
        and snapshot.task_id == task.task_id
        and snapshot.attempt_id == attempt.attempt_id
        and (not is_current_attempt or current_pointer_is_valid)
        and snapshot.algorithm_code == job.algorithm_code
        and summary.result_json == job.result_json
        and summary.result_hash == job.output_hash
        and all(attestation.get(key) == value for key, value in required_attestation.items())
        and all(guarantees.get(key) == value for key, value in required_guarantees.items())
        and isinstance(guarantees.get("strategy_hash"), str)
        and SHA256_HEX.fullmatch(guarantees["strategy_hash"]) is not None
    )


def _is_quarantined_legacy_enterprise_record(
    db: Session,
    job: PrivacyComputeJob,
) -> bool:
    """Recognize pre-receipt records solely so they remain isolated history."""

    if (
        LEGACY_ENTERPRISE_ADAPTER.fullmatch(job.adapter_code or "") is None
        or db.get(TrustedQueryTask, job.task_id) is not None
        or db.get(SettlementTask, job.task_id) is not None
        or job.status != "SUCCEEDED"
        or job.progress != 100
        or not SHA256_HEX.fullmatch(job.output_hash or "")
    ):
        return False
    if db.scalar(
        select(func.count(ExecutionReceipt.receipt_id)).where(
            ExecutionReceipt.task_id == job.task_id
        )
    ):
        return False
    response = job.result_json
    attestation = job.execution_attestation_json
    if not isinstance(response, dict) or not isinstance(attestation, dict):
        return False
    if (
        attestation.get("connector_signature_verified") is not True
        or attestation.get("raw_records_returned") is not False
        or not isinstance(attestation.get("applicant_org_id"), str)
        or _contains_forbidden_raw_key(response)
    ):
        return False
    signed_result = {
        key: value for key, value in response.items() if key not in _SIGNED_RESULT_METADATA_FIELDS
    }
    encoded_key = response.get("public_key")
    signature = response.get("signature")
    if (
        not isinstance(encoded_key, str)
        or not isinstance(signature, str)
        or response.get("signature_algorithm") != "Ed25519"
        or sha256_json(signed_result) != job.output_hash
    ):
        return False
    try:
        key_bytes = base64.b64decode(encoded_key, validate=True)
        key = Ed25519PublicKey.from_public_bytes(key_bytes)
    except Exception:
        return False
    return _verify_deployment_signature(
        signed_result=signed_result,
        encoded_signature=signature,
        trusted_keys=((hashlib.sha256(key_bytes).hexdigest(), encoded_key, key),),
    ) is not None


def _is_acceptable_production_compute_record(
    db: Session,
    job: PrivacyComputeJob,
    settings_value: Settings,
) -> bool:
    settlement_task = db.get(SettlementTask, job.task_id)
    trusted_query_task = db.get(TrustedQueryTask, job.task_id)
    if settlement_task is not None:
        return _is_supported_local_settlement_compute_record(
            db,
            job=job,
            task=settlement_task,
        )
    if trusted_query_task is not None or job.adapter_code.startswith(
        LOCAL_SUBJECT_NODE_ADAPTER_PREFIX
    ):
        return _is_supported_local_subject_compute_record(db, job, settings_value)
    return _is_quarantined_legacy_enterprise_record(db, job)


def assert_production_runtime_clean(
    settings: Settings,
    *,
    vault_dir: Path = VAULT_DIR,
) -> None:
    """Refuse to start production while the central raw-data vault is populated."""

    if settings.app_env != "production" or not vault_dir.exists():
        return

    payload_count = sum(1 for path in vault_dir.rglob("*") if path.is_file())
    if payload_count:
        raise RuntimeError(
            "Production central vault contains "
            f"{payload_count} file(s). Isolate or migrate them before startup; "
            "records were not read or deleted automatically."
        )


def assert_production_database_clean(db: Session, settings: Settings) -> None:
    """Reject fixture data and compute records that fail their trust contract."""

    if settings.app_env != "production":
        return

    fixture_orgs = db.scalar(
        select(func.count(Organization.org_id)).where(
            or_(
                Organization.org_id.ilike("%demo%"),
                Organization.org_id.ilike("%test%"),
                Organization.org_id.ilike("%-t01%"),
                Organization.org_name.contains("演示"),
                Organization.org_name.contains("测试"),
                Organization.org_name.contains("模拟"),
            )
        )
    ) or 0
    fixture_tasks = db.scalar(
        select(func.count(SettlementTask.task_id)).where(
            or_(
                SettlementTask.task_id.ilike("%demo%"),
                SettlementTask.task_id.ilike("%test%"),
                SettlementTask.task_id.ilike("%-t01%"),
                SettlementTask.trade_batch_no.ilike("%demo%"),
                SettlementTask.trade_batch_no.ilike("%test%"),
                SettlementTask.trade_batch_no.ilike("%t01%"),
                SettlementTask.task_name.contains("演示"),
                SettlementTask.task_name.contains("测试"),
                SettlementTask.task_name.contains("模拟"),
            )
        )
    ) or 0
    fixture_users = db.scalar(
        select(func.count(User.user_id)).where(User.username.in_(NON_PRODUCTION_USERNAMES))
    ) or 0
    unsupported_compute_records = sum(
        1
        for job in db.scalars(
            select(PrivacyComputeJob).execution_options(yield_per=100)
        )
        if not _is_acceptable_production_compute_record(db, job, settings)
    )
    supported_evidence_backends = {
        "LOCAL_EVIDENCE_LEDGER_V1",
        "FISCO_BCOS_EVIDENCE_ANCHOR_V1",
    }
    unsupported_evidence_records = db.scalar(
        select(func.count(BlockchainEvidence.evidence_id)).where(
            BlockchainEvidence.chain_code.not_in(supported_evidence_backends)
        )
    ) or 0

    findings = []
    if fixture_orgs:
        findings.append(f"{fixture_orgs} fixture organizations")
    if fixture_tasks:
        findings.append(f"{fixture_tasks} fixture settlement tasks")
    if fixture_users:
        findings.append(f"{fixture_users} default test accounts")
    if unsupported_compute_records:
        findings.append(f"{unsupported_compute_records} unsupported compute records")
    if unsupported_evidence_records:
        findings.append(f"{unsupported_evidence_records} unsupported evidence records")
    if findings:
        raise RuntimeError(
            "Production database contains non-production records: "
            + ", ".join(findings)
            + ". Use an isolated production database; records were not deleted automatically."
        )
