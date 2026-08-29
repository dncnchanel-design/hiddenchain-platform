from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import UTC, datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import httpx
from sqlalchemy import select

from app.database import SessionLocal
from app.models import ConnectorIngestionReceipt, ConnectorIngestionTicket, LocalSubjectNode
from app.security import canonical_json, sha256_json
from app.trust_models import DataAsset, DataAssetVersion


def _private_text(key: Ed25519PrivateKey) -> str:
    return base64.b64encode(
        key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    ).decode()


def _public_text(key: Ed25519PrivateKey) -> str:
    return base64.b64encode(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode()


def _configure_generator_node(connector_key: Ed25519PrivateKey) -> None:
    with SessionLocal() as db:
        node = db.scalar(
            select(LocalSubjectNode).where(
                LocalSubjectNode.org_id == "org-generator-t01"
            )
        )
        assert node is not None
        node.endpoint_ref = "https://generator-connector.example.test"
        node.public_key = _public_text(connector_key)
        db.commit()


def _issue_ticket(client, auth_headers, monkeypatch):
    from app.routers import connector_ingestion

    platform_key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(
        connector_ingestion,
        "settings",
        replace(
            connector_ingestion.settings,
            platform_signing_private_key=_private_text(platform_key),
        ),
    )
    response = client.post(
        "/api/trust-space/connectors/tickets",
        headers=auth_headers["generator"],
        json={
            "resource_id": "generation",
            "classification": "L3",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["upload_url"] == "https://generator-connector.example.test/ingest"
    assert body["connector"]["organization_id"] == "org-generator-t01"
    assert body["connector"]["energy_domain"] == "electricity"
    assert body["ticket"]["claims"]["resource_name"] == "发电量"
    assert body["ticket"]["claims"]["connector_id"] == "local-node-org-generator-t01"
    assert body["ticket"]["claims"]["max_bytes"] == 5 * 1024 * 1024
    assert "raw" not in canonical_json(body).lower()

    envelope = body["ticket"]
    platform_key.public_key().verify(
        base64.b64decode(envelope["signature"]),
        canonical_json(envelope["claims"]).encode(),
    )
    return body, platform_key


def _signed_receipt(
    ticket_body: dict,
    connector_key: Ed25519PrivateKey,
    **overrides,
) -> dict:
    claims = ticket_body["ticket"]["claims"]
    payload = {
        "receipt_id": "receipt-generator-generation-v1",
        "ticket_id": claims["jti"],
        "connector_id": claims["connector_id"],
        "organization_id": claims["organization_id"],
        "energy_domain": claims["energy_domain"],
        "resource_id": claims["resource_id"],
        "resource_name": claims["resource_name"],
        "version": 1,
        "schema_version": claims["schema_version"],
        "schema_hash": sha256_json(["record_date", "value"]),
        "content_hash": "a" * 64,
        "record_count": 4,
        "byte_size": 128,
        "local_ref": "connector://local-node-org-generator-t01/generation/versions/1",
        "audit_sequence": 1,
        "audit_hash": "b" * 64,
        "issued_at": datetime.now(UTC).isoformat(),
        **overrides,
    }
    return {
        **payload,
        "signature": base64.b64encode(
            connector_key.sign(canonical_json(payload).encode())
        ).decode(),
        "public_key": _public_text(connector_key),
        "signature_algorithm": "Ed25519",
        "signature_valid": True,
    }


def test_connector_ticket_is_subject_scoped_signed_and_never_accepts_a_file(
    client, auth_headers, monkeypatch
):
    connector_key = Ed25519PrivateKey.generate()
    _configure_generator_node(connector_key)
    body, _platform_key = _issue_ticket(client, auth_headers, monkeypatch)

    schema = client.get("/api/openapi.json").json()
    operation = schema["paths"]["/api/trust-space/connectors/tickets"]["post"]
    request_schema = canonical_json(operation.get("requestBody", {})).lower()
    assert "multipart" not in request_schema
    assert "binary" not in request_schema
    assert "file" not in request_schema

    with SessionLocal() as db:
        ticket = db.get(ConnectorIngestionTicket, body["ticket"]["claims"]["jti"])
        assert ticket is not None
        assert ticket.org_id == "org-generator-t01"
        assert ticket.resource_id == "generation"
        assert ticket.status == "ISSUED"

    assert client.post(
        "/api/trust-space/connectors/tickets",
        headers=auth_headers["regulator"],
        json={"resource_id": "generation", "classification": "L3"},
    ).status_code == 403
    assert client.post(
        "/api/trust-space/connectors/tickets",
        headers=auth_headers["admin"],
        json={"resource_id": "generation", "classification": "L3"},
    ).status_code == 403


def test_signed_connector_receipt_registers_metadata_only_and_is_idempotent(
    client, auth_headers, monkeypatch
):
    connector_key = Ed25519PrivateKey.generate()
    _configure_generator_node(connector_key)
    ticket_body, _platform_key = _issue_ticket(client, auth_headers, monkeypatch)
    receipt = _signed_receipt(ticket_body, connector_key)

    registered = client.post(
        "/api/trust-space/connectors/receipts",
        headers=auth_headers["generator"],
        json=receipt,
    )
    assert registered.status_code == 201, registered.text
    result = registered.json()
    assert result["receipt_id"] == receipt["receipt_id"]
    assert result["idempotent_replay"] is False
    assert result["raw_data_centrally_stored"] is False
    assert result["asset"]["version"] == 1

    replay = client.post(
        "/api/trust-space/connectors/receipts",
        headers=auth_headers["generator"],
        json=receipt,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["idempotent_replay"] is True

    ticket_id = ticket_body["ticket"]["claims"]["jti"]
    status = client.get(
        f"/api/trust-space/connectors/receipts/{ticket_id}",
        headers=auth_headers["generator"],
    )
    assert status.status_code == 200
    assert status.json()["receipt_id"] == receipt["receipt_id"]

    with SessionLocal() as db:
        ticket = db.get(ConnectorIngestionTicket, ticket_id)
        stored = db.get(ConnectorIngestionReceipt, receipt["receipt_id"])
        assert ticket is not None and ticket.status == "REGISTERED"
        assert stored is not None
        assert stored.signed_payload_json["content_hash"] == "a" * 64
        assert "records" not in canonical_json(stored.signed_payload_json).lower()
        asset = db.get(DataAsset, stored.asset_id)
        version = db.get(DataAssetVersion, stored.asset_version_id)
        assert asset is not None and asset.owner_org_id == "org-generator-t01"
        assert asset.metadata_json["raw_data_centrally_stored"] is False
        assert version is not None
        assert version.data_ref.startswith("connector://")
        assert version.record_count == 4


def test_receipt_registration_rejects_tamper_cross_subject_and_raw_fields(
    client, auth_headers, monkeypatch
):
    connector_key = Ed25519PrivateKey.generate()
    _configure_generator_node(connector_key)
    ticket_body, _platform_key = _issue_ticket(client, auth_headers, monkeypatch)
    valid = _signed_receipt(ticket_body, connector_key)

    tampered = {**valid, "record_count": 999}
    assert client.post(
        "/api/trust-space/connectors/receipts",
        headers=auth_headers["generator"],
        json=tampered,
    ).status_code == 422

    assert client.post(
        "/api/trust-space/connectors/receipts",
        headers=auth_headers["retailer"],
        json=valid,
    ).status_code == 403

    with_raw = {**valid, "raw_records": [{"record_date": "2026-08-01", "value": 1}]}
    assert client.post(
        "/api/trust-space/connectors/receipts",
        headers=auth_headers["generator"],
        json=with_raw,
    ).status_code == 422


def test_connector_catalog_is_server_sourced_and_owner_scoped(
    client, auth_headers
):
    connector_key = Ed25519PrivateKey.generate()
    _configure_generator_node(connector_key)
    response = client.get(
        "/api/trust-space/connectors/catalog",
        headers=auth_headers["generator"],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["connector"]["organization_id"] == "org-generator-t01"
    assert body["connector"]["energy_domain"] == "electricity"
    assert {item["resource_id"] for item in body["resources"]} == {
        "generation",
        "supply",
        "load",
        "price",
    }
    assert all(item["resource_name"] for item in body["resources"])
    assert all("raw" not in canonical_json(item).lower() for item in body["resources"])
    assert client.get(
        "/api/trust-space/connectors/catalog",
        headers=auth_headers["regulator"],
    ).status_code == 403


def test_demo_receipt_key_is_discovered_from_connector_identity_not_self_asserted(
    client, auth_headers, monkeypatch
):
    from app.routers import connector_ingestion

    trusted_connector_key = Ed25519PrivateKey.generate()
    forged_connector_key = Ed25519PrivateKey.generate()
    with SessionLocal() as db:
        node = db.scalar(
            select(LocalSubjectNode).where(
                LocalSubjectNode.org_id == "org-generator-t01"
            )
        )
        assert node is not None
        node.endpoint_ref = "https://generator-connector.example.test"
        node.public_key = None
        db.commit()

    def connector_health(url: str, **_kwargs):
        assert url == "https://generator-connector.example.test/health"
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "status": "就绪",
                "connector_id": "local-node-org-generator-t01",
                "organization_id": "org-generator-t01",
                "energy_domain": "electricity",
                "public_key": _public_text(trusted_connector_key),
            },
        )

    monkeypatch.setattr(connector_ingestion.httpx, "get", connector_health)
    ticket_body, _platform_key = _issue_ticket(client, auth_headers, monkeypatch)

    forged = _signed_receipt(ticket_body, forged_connector_key)
    rejected = client.post(
        "/api/trust-space/connectors/receipts",
        headers=auth_headers["generator"],
        json=forged,
    )
    assert rejected.status_code == 422, rejected.text
    assert "公钥" in rejected.json()["detail"]

    valid = _signed_receipt(ticket_body, trusted_connector_key)
    accepted = client.post(
        "/api/trust-space/connectors/receipts",
        headers=auth_headers["generator"],
        json=valid,
    )
    assert accepted.status_code == 201, accepted.text
    with SessionLocal() as db:
        node = db.scalar(
            select(LocalSubjectNode).where(
                LocalSubjectNode.org_id == "org-generator-t01"
            )
        )
        assert node is not None
        assert node.public_key == _public_text(trusted_connector_key)
