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
    finally:
        import sys
        sys.modules.pop("connector.app.main", None)
