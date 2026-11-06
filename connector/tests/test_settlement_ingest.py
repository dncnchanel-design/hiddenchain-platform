from __future__ import annotations

import base64
import hashlib
import importlib
import json
import sys
import time
from datetime import date, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


@pytest.fixture
def node(monkeypatch, tmp_path):
    platform_key = Ed25519PrivateKey.generate()
    node_key = Ed25519PrivateKey.generate()
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("ENERGY_DOMAIN", "electricity")
    monkeypatch.setenv("CONNECTOR_ID", "settlement-node")
    monkeypatch.setenv("ORGANIZATION_ID", "org-electricity-owner")
    monkeypatch.setenv("CONNECTOR_DATABASE_PATH", str(tmp_path / "settlement.db"))
    monkeypatch.setenv("CONNECTOR_SEED_SYNTHETIC_DATA", "false")
    monkeypatch.setenv("CONNECTOR_SIGNING_PRIVATE_KEY", base64.b64encode(node_key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())).decode())
    public_key = base64.b64encode(platform_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    monkeypatch.setenv("PLATFORM_SIGNING_PUBLIC_KEY", public_key)
    sys.modules.pop("connector.app.main", None)
    module = importlib.import_module("connector.app.main")
    with TestClient(module.app) as client:
        yield module, client, platform_key, node_key, public_key
    sys.modules.pop("connector.app.main", None)


def claims(**changes):
    now = int(time.time())
    result = {
        "iss": "hiddenchain-platform", "jti": "settlement-ticket-0001", "subject_user_id": "owner-user",
        "organization_id": "org-electricity-owner", "connector_id": "settlement-node", "energy_domain": "electricity",
        "resource_id": "generation", "resource_name": "发电量", "classification": "L3", "schema_version": "connector-csv-v1",
        "file_format": "csv", "max_bytes": 5 * 1024 * 1024, "purpose": "LOCAL_DATASET_INGEST", "issued_at": now, "expires_at": now + 300,
        "settlement_binding": {"schema_version": "connector-settlement-binding-v1", "trade_batch_no": "BATCH-20261106-001", "period_start": "2026-08-01", "period_end": "2026-08-03"},
    }
    result.update(changes)
    return result


def ticket(node, payload):
    return {"claims": payload, "signature": base64.b64encode(node[2].sign(canonical(payload))).decode(), "public_key": node[4], "algorithm": "Ed25519"}


def csv_bytes(values=("0.1", "0.2", "0.000003")):
    return ("record_date,value\n" + "".join(f"2026-08-{i + 1:02},{value}\n" for i, value in enumerate(values))).encode()


def ingest(node, payload=None, raw=None, envelope=None):
    return node[1].post("/ingest", data={"ticket": json.dumps(envelope or ticket(node, payload or claims()), ensure_ascii=False)}, files={"file": ("settlement.csv", raw if raw is not None else csv_bytes(), "text/csv")})


def assert_no_ingest(node):
    with node[0]._database() as db:
        for table in ("ingest_tickets", "resource_versions", "version_records", "ingest_receipts", "ingest_audit_chain"):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize(("resource", "name", "asset_type"), [("generation", "发电量", "GENERATION_DATA"), ("supply", "供电量", "RETAIL_DATA")])
def test_bound_csv_returns_exact_signed_summary_and_lookup(node, resource, name, asset_type):
    payload = claims(resource_id=resource, resource_name=name)
    raw = csv_bytes()
    response = ingest(node, payload, raw)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["settlement_summary"] == {
        "schema_version": "connector-settlement-summary-v1", "trade_batch_no": "BATCH-20261106-001",
        "period_start": "2026-08-01", "period_end": "2026-08-03", "asset_type": asset_type,
        "aggregation": "SUM", "unit": "MWh", "energy_mwh": "0.300003", "record_count": 3,
        "content_hash": hashlib.sha256(raw).hexdigest(), "claims_hash": hashlib.sha256(canonical(payload)).hexdigest(), "raw_records_returned": False,
    }
    signed = {key: value for key, value in body.items() if key not in {"signature", "public_key", "signature_algorithm", "signature_valid"}}
    node[3].public_key().verify(base64.b64decode(body["signature"]), canonical(signed))
    assert node[1].post("/ingest/receipts/lookup", json=ticket(node, payload)).json() == body
    assert ingest(node, payload, raw).status_code == 409
    with node[0]._database() as db:
        event = json.loads(db.execute("SELECT event_json FROM ingest_audit_chain").fetchone()[0])
        assert event["settlement_summary_hash"] == hashlib.sha256(canonical(body["settlement_summary"])).hexdigest()
        assert event["claims_hash"] == body["settlement_summary"]["claims_hash"]


@pytest.mark.parametrize("raw", [
    b"record_date,value\n2026-08-01,1\n2026-08-01,2\n2026-08-03,3\n",
    b"record_date,value\n2026-08-01,1\n2026-08-03,3\n",
    b"record_date,value\n2026-07-31,1\n2026-08-02,2\n2026-08-03,3\n",
    b"record_date,value,hour\n2026-08-01,1,0\n2026-08-02,2,\n2026-08-03,3,\n",
    csv_bytes(("-1", "2", "3")), csv_bytes(("NaN", "2", "3")), csv_bytes(("Infinity", "2", "3")),
    csv_bytes(("0.0000001", "2", "3")), csv_bytes(("1e-1000000", "2", "3")),
    csv_bytes(("1000000000000", "0.000001", "0")),
    b"record_date,value,unit\n2026-08-01,1,kWh\n2026-08-02,2,MWh\n2026-08-03,3,MWh\n",
    b"record_date,value\n20260801,1\n2026-08-02,2\n2026-08-03,3\n",
])
def test_invalid_settlement_data_is_rejected_atomically(node, raw):
    response = ingest(node, raw=raw)
    assert response.status_code == 422, response.text
    assert_no_ingest(node)
    assert ingest(node).status_code == 201


@pytest.mark.parametrize("change", [
    {"period_start": "2026-8-01"}, {"period_start": "2026-02-30"}, {"period_end": "2026-07-31"},
    {"period_start": "2025-01-01", "period_end": "2026-01-02"}, {"trade_batch_no": "ab"},
    {"schema_version": "other"}, {"asset_type": "GENERATION_DATA"},
])
def test_invalid_binding_is_rejected_before_any_write(node, change):
    payload = claims()
    payload["settlement_binding"].update(change)
    assert ingest(node, payload).status_code == 422
    assert_no_ingest(node)


@pytest.mark.parametrize("resource,name", [("load", "用电负荷"), ("price", "交易价格")])
def test_only_energy_resources_can_bind_a_settlement(node, resource, name):
    assert ingest(node, claims(resource_id=resource, resource_name=name)).status_code == 422
    assert_no_ingest(node)


def test_binding_cannot_be_changed_without_platform_signature(node):
    envelope = ticket(node, claims())
    envelope["claims"]["settlement_binding"]["trade_batch_no"] = "OTHER-BATCH"
    assert ingest(node, envelope=envelope).status_code == 401
    assert_no_ingest(node)


def test_production_rejects_binding_but_retains_ordinary_ingestion(node, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert ingest(node).status_code == 403
    assert_no_ingest(node)
    payload = claims()
    payload.pop("settlement_binding")
    ordinary = ingest(node, payload)
    assert ordinary.status_code == 201, ordinary.text
    assert "settlement_summary" not in ordinary.json()


def test_plain_upload_keeps_old_claims_signature_and_no_summary(node):
    payload = claims()
    payload.pop("settlement_binding")
    response = ingest(node, payload, csv_bytes(("0.0000001", "-1", "3")))
    assert response.status_code == 201, response.text
    assert "settlement_summary" not in response.json()
    assert node[1].post("/ingest/receipts/lookup", json=ticket(node, payload)).json() == response.json()


def test_summary_sign_failure_rolls_back_ticket_records_and_audit(node, monkeypatch):
    original = node[0]._signed_response
    def fail(_payload):
        raise RuntimeError("signing unavailable")
    monkeypatch.setattr(node[0], "_signed_response", fail)
    with pytest.raises(RuntimeError, match="signing unavailable"):
        ingest(node)
    assert_no_ingest(node)
    monkeypatch.setattr(node[0], "_signed_response", original)
    assert ingest(node).status_code == 201


def test_full_leap_year_and_upper_value_boundary_are_accepted(node):
    payload = claims()
    payload["settlement_binding"].update(period_start="2024-01-01", period_end="2024-12-31")
    raw = ("record_date,value\n" + "".join(f"{date(2024, 1, 1) + timedelta(days=i)},{'1000000000000' if i == 0 else '0'}\n" for i in range(366))).encode()
    response = ingest(node, payload, raw)
    assert response.status_code == 201, response.text
    assert response.json()["settlement_summary"]["energy_mwh"] == "1000000000000"
    assert response.json()["settlement_summary"]["record_count"] == 366


def test_summary_preserves_micro_mwh_near_the_limit_and_is_order_independent(node):
    raw = csv_bytes(("999999999999.999998", "0.000001", "0"))
    first = ingest(node, raw=raw)
    assert first.status_code == 201, first.text
    assert first.json()["settlement_summary"]["energy_mwh"] == "999999999999.999999"
    lines = raw.decode().splitlines()
    reordered = (lines[0] + "\n" + "\n".join(reversed(lines[1:])) + "\n").encode()
    second = ingest(node, claims(jti="settlement-ticket-0002"), reordered)
    assert second.status_code == 201, second.text
    assert second.json()["settlement_summary"]["energy_mwh"] == first.json()["settlement_summary"]["energy_mwh"]
    assert second.json()["content_hash"] != first.json()["content_hash"]


def test_ticket_expiring_while_file_is_read_cannot_commit_settlement(node, monkeypatch):
    payload = claims()
    times = iter((payload["issued_at"], payload["expires_at"] + 1))
    monkeypatch.setattr(node[0], "_now_epoch", lambda: next(times))
    response = ingest(node, payload)
    assert response.status_code == 401, response.text
    assert_no_ingest(node)
