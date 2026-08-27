from __future__ import annotations

import httpx

from app.routers.trusted_query import _connector_failure
from app.services.privacy_attestation import canonical_connector_request_payload


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
