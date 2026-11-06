"""Regression evidence for receipt integrity and delayed registration boundaries."""
from __future__ import annotations

from copy import deepcopy

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import event, func, select

from app.database import SessionLocal, engine
from app.models import ConnectorIngestionReceipt, DataUpload, DidIdentity, User
from app.trust_models import DataAsset, DataAssetVersion
from test_connector_ingestion import _configure_generator_node, _signed_receipt
from test_connector_settlement_ingress import _receipt, _ticket


def _ordinary_ticket(client, auth_headers, *, classification="L3"):
    response = client.post("/api/trust-space/connectors/tickets", headers=auth_headers["generator"],
                           json={"resource_id": "generation", "classification": classification})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("field,value", [
    ("version", "1"), ("version", 1.0), ("version", True),
    ("record_count", "4"), ("byte_size", 128.0), ("audit_sequence", True),
])
def test_receipt_rejects_typed_payload_changes_under_original_signature(client, auth_headers, field, value):
    key = Ed25519PrivateKey.generate()
    _configure_generator_node(key)
    signed = _signed_receipt(_ordinary_ticket(client, auth_headers), key)
    tampered = {**signed, field: value}
    response = client.post("/api/trust-space/connectors/receipts", headers=auth_headers["generator"], json=tampered)
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert db.get(ConnectorIngestionReceipt, signed["receipt_id"]) is None


def test_settlement_summary_preserves_signed_batch_text(client, auth_headers):
    key = Ed25519PrivateKey.generate()
    _configure_generator_node(key)
    signed = _receipt(_ticket(client, auth_headers), key)
    tampered = deepcopy(signed)
    tampered["settlement_summary"]["trade_batch_no"] = f"  {signed['settlement_summary']['trade_batch_no']}  "
    response = client.post("/api/trust-space/connectors/receipts", headers=auth_headers["generator"], json=tampered)
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert db.get(ConnectorIngestionReceipt, signed["receipt_id"]) is None
        assert db.scalar(select(func.count()).select_from(DataUpload).where(DataUpload.trade_batch_no == signed["settlement_summary"]["trade_batch_no"])) == 0


def test_delayed_older_receipt_does_not_replace_current_resource_version(client, auth_headers):
    key = Ed25519PrivateKey.generate()
    _configure_generator_node(key)
    old_ticket = _ordinary_ticket(client, auth_headers, classification="L1")
    new_ticket = _ordinary_ticket(client, auth_headers, classification="L3")
    newest = _signed_receipt(new_ticket, key, receipt_id="receipt-delayed-new-v2", version=2,
                             local_ref="connector://local-node-org-generator-t01/generation/versions/2")
    older = _signed_receipt(old_ticket, key, receipt_id="receipt-delayed-old-v1")
    for receipt in (newest, older):
        response = client.post("/api/trust-space/connectors/receipts", headers=auth_headers["generator"], json=receipt)
        assert response.status_code == 201, response.text
    with SessionLocal() as db:
        stored = db.get(ConnectorIngestionReceipt, newest["receipt_id"])
        asset = db.get(DataAsset, stored.asset_id)
        current = db.get(DataAssetVersion, asset.current_version_id)
        assert current.version_no == 2
        assert asset.sensitivity_level == "L3"
        assert asset.metadata_json["ingestion_receipt_id"] == newest["receipt_id"]
        assert db.get(ConnectorIngestionReceipt, older["receipt_id"]) is not None
    catalog = client.get("/api/trust-space/connectors/catalog", headers=auth_headers["generator"])
    assert catalog.status_code == 200, catalog.text
    resource = next(item for item in catalog.json()["resources"] if item["resource_id"] == "generation")
    assert resource["current_version"] == 2


@pytest.mark.parametrize("registered", [False, True])
def test_receipt_lookup_requires_connector_management_permission(client, auth_headers, registered):
    key = Ed25519PrivateKey.generate()
    _configure_generator_node(key)
    ticket = _ordinary_ticket(client, auth_headers)
    if registered:
        response = client.post("/api/trust-space/connectors/receipts", headers=auth_headers["generator"], json=_signed_receipt(ticket, key))
        assert response.status_code == 201, response.text
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "generator"))
        user.permissions_json = [permission for permission in user.permissions_json if permission != "MANAGE_CONNECTOR"]
        db.commit()
    response = client.get(f"/api/trust-space/connectors/receipts/{ticket['ticket']['claims']['jti']}", headers=auth_headers["generator"])
    assert response.status_code == 403, response.text


def test_concurrent_newer_receipt_cannot_be_overwritten_by_stale_sqlite_reader(client, auth_headers):
    key = Ed25519PrivateKey.generate()
    _configure_generator_node(key)
    initial = _signed_receipt(_ordinary_ticket(client, auth_headers), key)
    response = client.post("/api/trust-space/connectors/receipts", headers=auth_headers["generator"], json=initial)
    assert response.status_code == 201, response.text
    pending = _signed_receipt(_ordinary_ticket(client, auth_headers, classification="L1"), key,
                             receipt_id="receipt-concurrent-v2", version=2,
                             local_ref="connector://local-node-org-generator-t01/generation/versions/2")
    newest = _signed_receipt(_ordinary_ticket(client, auth_headers, classification="L3"), key,
                            receipt_id="receipt-concurrent-v3", version=3,
                            local_ref="connector://local-node-org-generator-t01/generation/versions/3")
    interleaved = []
    def register_newer_before_pending_write(_connection, _cursor, statement, _parameters, context, _many):
        if statement.startswith("INSERT INTO data_asset_versions ") and context.compiled_parameters[0].get("version_no") == 2:
            # SQLite SELECT/FOR UPDATE does not acquire a write lock. Commit v3
            # after v2 read the asset but before v2 obtains its INSERT write lock.
            interleaved.append(client.post("/api/trust-space/connectors/receipts", headers=auth_headers["generator"], json=newest))
    event.listen(engine, "before_cursor_execute", register_newer_before_pending_write)
    try:
        response = client.post("/api/trust-space/connectors/receipts", headers=auth_headers["generator"], json=pending)
    finally:
        event.remove(engine, "before_cursor_execute", register_newer_before_pending_write)
    assert response.status_code == 201, response.text
    assert len(interleaved) == 1 and interleaved[0].status_code == 201
    with SessionLocal() as db:
        stored = db.get(ConnectorIngestionReceipt, newest["receipt_id"])
        asset = db.get(DataAsset, stored.asset_id)
        assert db.get(DataAssetVersion, asset.current_version_id).version_no == 3
        assert asset.sensitivity_level == "L3"
        assert asset.metadata_json["ingestion_receipt_id"] == newest["receipt_id"]


def test_revoked_identity_cannot_materialize_settlement_aggregate(client, auth_headers):
    key = Ed25519PrivateKey.generate()
    _configure_generator_node(key)
    receipt = _receipt(_ticket(client, auth_headers), key)
    with SessionLocal() as db:
        identity = db.scalar(select(DidIdentity).where(DidIdentity.owner_type == "ORG", DidIdentity.owner_id == "org-generator-t01"))
        identity.credential_status = "REVOKED"
        db.commit()
    response = client.post("/api/trust-space/connectors/receipts", headers=auth_headers["generator"], json=receipt)
    assert response.status_code == 403, response.text
    with SessionLocal() as db:
        assert db.get(ConnectorIngestionReceipt, receipt["receipt_id"]) is None
        assert db.scalar(select(func.count()).select_from(DataUpload).where(DataUpload.trade_batch_no == receipt["settlement_summary"]["trade_batch_no"])) == 0
