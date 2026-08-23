from __future__ import annotations

import httpx

from app.routers.trusted_query import _connector_failure


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
