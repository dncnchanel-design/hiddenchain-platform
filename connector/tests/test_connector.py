from __future__ import annotations

import base64
import importlib
import json
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient


def _raw_private(key: Ed25519PrivateKey) -> str:
    return base64.b64encode(
        key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    ).decode()


def _raw_public(key: Ed25519PrivateKey) -> str:
    return base64.b64encode(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode()


def test_connector_keeps_raw_records_local_and_signs_controlled_result(monkeypatch, tmp_path):
    connector_key = Ed25519PrivateKey.generate()
    platform_key = Ed25519PrivateKey.generate()
    monkeypatch.setenv("ENERGY_DOMAIN", "coal")
    monkeypatch.setenv("CONNECTOR_SIGNING_PRIVATE_KEY", _raw_private(connector_key))
    monkeypatch.setenv("PLATFORM_SIGNING_PUBLIC_KEY", _raw_public(platform_key))
    monkeypatch.setenv("CONNECTOR_DATABASE_PATH", str(tmp_path / "coal.db"))
    monkeypatch.setenv("ORGANIZATION_ID", "org-coal-t01")
    monkeypatch.setenv("PRIVACY_MIN_GROUP_SIZE", "3")
    try:
        module = importlib.import_module("connector.app.main")
        with TestClient(module.app) as client:
            catalog = client.get("/catalog")
            assert catalog.status_code == 200
            assert catalog.json()["notice"] == "这里只发布目录信息，原始数据保存在企业连接器中。"
            payload = {
                "task_id": "TASK-20260823-0001",
                "authorization_id": "AUTH-20260823-0001",
                "resource": "inventory",
                "function": "average",
                "start_date": "2026-08-01",
                "end_date": "2026-08-23",
                "region": None,
                "hour": None,
                "threshold": None,
                "group_by": None,
                "decimals": 2,
            }
            timestamp = str(int(datetime.now(UTC).timestamp()))
            nonce = "connector-test-nonce-0001"
            envelope = {"timestamp": timestamp, "nonce": nonce, "payload": payload}
            signature = platform_key.sign(
                json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            )
            response = client.post(
                "/compute",
                json=payload,
                headers={
                    "X-Request-Timestamp": timestamp,
                    "X-Request-Nonce": nonce,
                    "X-Request-Signature": base64.b64encode(signature).decode(),
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["resource_name"] == "煤炭库存"
            assert body["function_name"] == "平均值"
            assert body["privacy"]["raw_records_returned"] is False
            assert body["privacy"]["raw_data_exported"] is False
            assert body["privacy"]["non_export_attestation"]["status"] == "SIGNED"
            assert body["privacy"]["non_export_attestation"]["request_hash"]
            assert body["privacy_verification"]["mode"] == "SIGNED_CONNECTOR_NON_EXPORT"
            assert body["signature_algorithm"] == "Ed25519"
            connector_key.public_key().verify(
                base64.b64decode(body["signature"]),
                json.dumps(
                    {key: value for key, value in body.items() if key not in {"signature", "public_key", "signature_algorithm", "signature_valid"}},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode(),
            )

            trend_payload = {**payload, "task_id": "TASK-20260823-0002", "function": "trend"}
            trend_timestamp = str(int(datetime.now(UTC).timestamp()))
            trend_nonce = "connector-trend-nonce-0001"
            trend_envelope = {"timestamp": trend_timestamp, "nonce": trend_nonce, "payload": trend_payload}
            trend_signature = platform_key.sign(
                json.dumps(trend_envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            )
            trend_response = client.post(
                "/compute",
                json=trend_payload,
                headers={
                    "X-Request-Timestamp": trend_timestamp,
                    "X-Request-Nonce": trend_nonce,
                    "X-Request-Signature": base64.b64encode(trend_signature).decode(),
                },
            )
            assert trend_response.status_code == 200, trend_response.text
            trend_body = trend_response.json()
            assert trend_body["result"]["方向"] in {"上升", "下降", "平稳"}
            assert len(trend_body["trend"]) > 1
            assert all(set(point) == {"date", "value"} for point in trend_body["trend"])
            assert trend_body["privacy"]["raw_records_returned"] is False
            assert trend_body["privacy"]["non_export_attestation"]["status"] == "SIGNED"

            dashboard_payload = {
                "request_id": "dashboard-test-0001",
                "provider_org_id": "org-coal-t01",
                "resource": "inventory",
                "aggregation": "average",
                "start_date": "2026-08-01",
                "end_date": "2026-08-23",
                "decimals": 2,
            }
            dashboard_timestamp = str(int(datetime.now(UTC).timestamp()))
            dashboard_nonce = "connector-dashboard-nonce-0001"
            dashboard_envelope = {
                "timestamp": dashboard_timestamp,
                "nonce": dashboard_nonce,
                "payload": dashboard_payload,
            }
            dashboard_signature = platform_key.sign(
                json.dumps(dashboard_envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            )
            dashboard_response = client.post(
                "/dashboard",
                json=dashboard_payload,
                headers={
                    "X-Request-Timestamp": dashboard_timestamp,
                    "X-Request-Nonce": dashboard_nonce,
                    "X-Request-Signature": base64.b64encode(dashboard_signature).decode(),
                },
            )
            assert dashboard_response.status_code == 200, dashboard_response.text
            dashboard_body = dashboard_response.json()
            assert dashboard_body["energy_domain"] == "coal"
            assert dashboard_body["resource_name"] == "煤炭库存"
            assert dashboard_body["trend"]
            assert isinstance(dashboard_body["latest"]["value"], (int, float))
            assert dashboard_body["raw_records_returned"] is False
            assert dashboard_body["privacy_verification"]["mode"] == "SIGNED_CONNECTOR_NON_EXPORT"
            assert "raw_records" not in dashboard_body
            connector_key.public_key().verify(
                base64.b64decode(dashboard_body["signature"]),
                json.dumps(
                    {key: value for key, value in dashboard_body.items() if key not in {"signature", "public_key", "signature_algorithm", "signature_valid"}},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode(),
            )
    finally:
        import sys
        sys.modules.pop("connector.app.main", None)
