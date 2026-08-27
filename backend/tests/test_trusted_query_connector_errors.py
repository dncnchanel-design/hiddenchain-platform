from __future__ import annotations

import httpx

from app.routers.trusted_query import _connector_failure
from app.security import sha256_json
from app.services.privacy_attestation import (
    canonical_connector_request_payload,
    verify_signed_connector_non_export,
)


def _response(status_code: int, content: bytes, content_type: str = "text/plain") -> httpx.Response:
    return httpx.Response(
        status_code,
        headers={"content-type": content_type},
        content=content,
        request=httpx.Request("POST", "https://connector.example/compute"),
    )


def test_connector_html_gateway_error_becomes_chinese_retryable_service_error():
    status_code, detail = _connector_failure(_response(502, b"Bad Gateway"))

    assert status_code == 503
    assert detail == "企业连接器正在启动或暂不可用，请稍后重试"


def test_connector_business_error_keeps_status_and_detail():
    response = _response(
        403,
        '{"detail":"企业连接器拒绝该授权范围"}'.encode(),
        "application/json",
    )

    status_code, detail = _connector_failure(response)

    assert status_code == 403
    assert detail == "企业连接器拒绝该授权范围"


def test_connector_signature_error_is_not_reported_as_user_session_expiry():
    response = _response(
        401,
        '{"detail":"平台数字签名验证失败"}'.encode(),
        "application/json",
    )

    status_code, detail = _connector_failure(response)

    assert status_code == 502
    assert detail == "平台数字签名验证失败"


def test_connector_request_canonicalization_omits_null_optional_subject_fields():
    payload = {
        "task_id": "TASK-20260827-0001",
        "authorization_id": "AUTH-20260827-0001",
        "request_item_id": "ITEM-20260827-0001",
        "provider_org_id": "org-retailer-t01",
        "rule_version": None,
        "resource": "load",
        "function": "trend",
        "start_date": "2026-06-01",
        "end_date": "2026-06-30",
        "region": None,
        "hour": None,
        "threshold": None,
        "group_by": None,
        "decimals": 2,
    }

    normalized = canonical_connector_request_payload(payload)

    assert "rule_version" not in normalized
    assert normalized["request_item_id"] == payload["request_item_id"]
    assert normalized["provider_org_id"] == payload["provider_org_id"]
    assert normalized["region"] is None


def test_connector_attestation_accepts_legacy_null_subject_fields_during_rollout():
    payload = {
        "task_id": "TASK-20260827-0002",
        "authorization_id": "AUTH-20260827-0002",
        "request_item_id": "ITEM-20260827-0002",
        "provider_org_id": "org-retailer-t01",
        "rule_version": None,
        "resource": "load",
        "function": "trend",
        "start_date": "2026-06-01",
        "end_date": "2026-06-30",
        "region": None,
        "hour": None,
        "threshold": None,
        "group_by": None,
        "decimals": 2,
    }
    canonical_payload = canonical_connector_request_payload(payload)
    legacy_hash = sha256_json({**canonical_payload, "rule_version": None})
    result = {
        "connector_id": "node-org-retailer-t01",
        "raw_records_returned": False,
        "privacy": {
            "raw_records_returned": False,
            "raw_data_exported": False,
            "non_export_attestation": {
                "status": "SIGNED",
                "issuer": "node-org-retailer-t01",
                "boundary": "CONNECTOR_LOCAL_DATA",
                "request_hash": legacy_hash,
                "result_scope": "AGGREGATE_ONLY",
                "raw_data_exported": False,
            },
        },
        "privacy_verification": {
            "mode": "SIGNED_CONNECTOR_NON_EXPORT",
            "request_hash": legacy_hash,
            "result_scope": "AGGREGATE_ONLY",
            "raw_data_exported": False,
        },
    }

    proof = verify_signed_connector_non_export(result, canonical_payload)

    assert proof["status"] == "VERIFIED"
    assert proof["request_hash"] == sha256_json(canonical_payload)


def test_connector_attestation_accepts_legacy_missing_top_level_raw_flag():
    request_payload = {
        "task_id": "TASK-20260827-0003",
        "authorization_id": "AUTH-20260827-0003",
        "resource": "inventory",
        "function": "average",
        "start_date": "2026-08-01",
        "end_date": "2026-08-02",
        "region": None,
        "hour": None,
        "threshold": None,
        "group_by": None,
        "decimals": 2,
    }
    request_hash = sha256_json(request_payload)
    result = {
        "connector_id": "node-org-coal-t01",
        "privacy": {
            "raw_records_returned": False,
            "raw_data_exported": False,
            "non_export_attestation": {
                "status": "SIGNED",
                "issuer": "node-org-coal-t01",
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

    proof = verify_signed_connector_non_export(result, request_payload)

    assert proof["status"] == "VERIFIED"
