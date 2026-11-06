from __future__ import annotations

import base64
import json
import sqlite3
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, func, inspect, select, text

from app.database import SessionLocal, engine
from app.migrations import MIGRATIONS
from app.models import ConnectorIngestionReceipt, ConnectorIngestionTicket, DataUpload, LocalSubjectNode, SettlementRule
from app.routers import connector_ingestion
from app.security import canonical_json, sha256_json
from app.services import connector_settlement
from app.services.adapters import LocalControlledComputeAdapter
from app.services.connector_settlement import SettlementBinding, SettlementSummary, settlement_upload_id
from app.services.settlement_period import matches_period
from app.services.vault import LocalDomainVault
from app.trust_models import DataAssetPassport, DataAssetVersion
from test_connector_ingestion import _configure_generator_node, _private_text, _public_text, _signed_receipt
from test_connector_ingestion_e2e import _load_connector_module


BINDING = {"trade_batch_no": "NEW-SETTLEMENT-20261106", "period_start": "2026-09-01", "period_end": "2026-09-02"}


def _ticket(client, auth_headers, role="generator", **binding_overrides):
    response = client.post("/api/trust-space/connectors/tickets", headers=auth_headers[role], json={"resource_id": "generation" if role == "generator" else "supply", "settlement_binding": {**BINDING, **binding_overrides}})
    assert response.status_code == 201, response.text
    return response.json()


def _summary(ticket, **overrides):
    claims = ticket["ticket"]["claims"]
    return {**claims["settlement_binding"], "schema_version": "connector-settlement-summary-v1", "asset_type": "GENERATION_DATA", "aggregation": "SUM", "unit": "MWh", "energy_mwh": "1000.000001", "record_count": 2, "content_hash": "a" * 64, "claims_hash": sha256_json(claims), "raw_records_returned": False, **overrides}


def _receipt(ticket, key, **summary_overrides):
    return _signed_receipt(ticket, key, record_count=2, settlement_summary=_summary(ticket, **summary_overrides))


def test_binding_and_summary_validate_exact_dates_decimal_and_daily_count():
    binding = SettlementBinding(**{**BINDING, "trade_batch_no": "  NEW-BATCH  "})
    assert binding.trade_batch_no == "NEW-BATCH"
    for override in ({"period_start": "2026-9-01"}, {"period_end": "2026-02-30"}, {"period_end": "2026-08-31"}, {"period_end": "2028-09-02"}, {"trade_batch_no": "  x "}, {"period_start": 1790000000}):
        with pytest.raises(ValidationError):
            SettlementBinding(**{**BINDING, **override})
    valid = {**BINDING, "schema_version": "connector-settlement-summary-v1", "asset_type": "GENERATION_DATA", "aggregation": "SUM", "unit": "MWh", "energy_mwh": "1000.000001", "record_count": 2, "content_hash": "a" * 64, "claims_hash": "b" * 64, "raw_records_returned": False}
    assert SettlementSummary(**valid).energy_mwh == "1000.000001"
    for override in ({"energy_mwh": 1}, {"energy_mwh": "NaN"}, {"energy_mwh": "-1"}, {"energy_mwh": "1e3"}, {"energy_mwh": "1000000000000.000001"}, {"energy_mwh": "1.1234567"}, {"record_count": 1}, {"record_count": True}, {"raw_records_returned": 0}):
        with pytest.raises(ValidationError):
            SettlementSummary(**{**valid, **override})


def test_ticket_binding_persisted_and_environment_resource_and_role_scoped(client, auth_headers, monkeypatch):
    _configure_generator_node(Ed25519PrivateKey.generate())
    body = _ticket(client, auth_headers, trade_batch_no="  NEW-BATCH  ")
    claims = body["ticket"]["claims"]
    assert claims["settlement_binding"]["trade_batch_no"] == "NEW-BATCH"
    assert claims["settlement_binding"]["schema_version"] == "connector-settlement-binding-v1"
    with SessionLocal() as db:
        ticket = db.get(ConnectorIngestionTicket, claims["jti"])
        assert ticket.settlement_binding_json == claims["settlement_binding"]
        assert ticket.claims_hash == sha256_json(claims)
    denied = client.post("/api/trust-space/connectors/tickets", headers=auth_headers["generator"], json={"resource_id": "supply", "settlement_binding": BINDING})
    assert denied.status_code == 403
    monkeypatch.setattr(connector_ingestion, "settings", replace(connector_ingestion.settings, app_env="production"))
    denied = client.post("/api/trust-space/connectors/tickets", headers=auth_headers["generator"], json={"resource_id": "generation", "settlement_binding": BINDING})
    assert denied.status_code == 403


def test_verified_receipt_materializes_exact_aggregate_and_idempotent_reference(client, auth_headers):
    key = Ed25519PrivateKey.generate()
    _configure_generator_node(key)
    ticket = _ticket(client, auth_headers)
    receipt = _receipt(ticket, key)
    registered = client.post("/api/trust-space/connectors/receipts", headers=auth_headers["generator"], json=receipt)
    assert registered.status_code == 201, registered.text
    settlement = registered.json()["settlement"]
    assert settlement["trade_batch_no"] == BINDING["trade_batch_no"]
    catalog = client.get("/api/data/catalog", headers=auth_headers["exchange"], params={"trade_batch_no": BINDING["trade_batch_no"]})
    assert catalog.status_code == 200, catalog.text
    entry = next(item for item in catalog.json()["entries"] if item["upload_id"] == settlement["upload_id"])
    assert entry["quality"]["period_start"] == BINDING["period_start"]
    assert entry["quality"]["period_end"] == BINDING["period_end"]
    with SessionLocal() as db:
        upload = db.get(DataUpload, settlement["upload_id"])
        payload = LocalControlledComputeAdapter._verified_vault_payload(upload)
        assert payload["energy_mwh"] == "1000.000001"
        assert payload["source"]["signed_receipt"]["settlement_summary"] == receipt["settlement_summary"]
        assert "raw_records" not in payload
        from datetime import date
        assert matches_period(upload, SimpleNamespace(period_start=date(2026, 9, 1), period_end=date(2026, 9, 2)))
        version = db.scalar(select(DataAssetVersion).where(DataAssetVersion.data_hash == upload.data_hash))
        passport = db.scalar(select(DataAssetPassport).where(DataAssetPassport.asset_version_id == version.version_id))
        assert passport.provenance_json["source_receipt_id"] == receipt["receipt_id"]
        before = LocalDomainVault.read(upload.data_ref)
    replay = client.post("/api/trust-space/connectors/receipts", headers=auth_headers["generator"], json=receipt)
    lookup = client.get(f"/api/trust-space/connectors/receipts/{receipt['ticket_id']}", headers=auth_headers["generator"])
    assert replay.status_code == lookup.status_code == 200
    assert replay.json()["settlement"] == lookup.json()["settlement"] == settlement
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(DataUpload).where(DataUpload.trade_batch_no == BINDING["trade_batch_no"])) == 1
        assert LocalDomainVault.read(db.get(DataUpload, settlement["upload_id"]).data_ref) == before


def test_receipt_binding_tamper_missing_summary_and_wrong_owner_are_rejected(client, auth_headers):
    key = Ed25519PrivateKey.generate()
    _configure_generator_node(key)
    ticket = _ticket(client, auth_headers)
    valid = _receipt(ticket, key)
    tampered = {**valid, "settlement_summary": {**valid["settlement_summary"], "energy_mwh": "9"}}
    candidates = [tampered, _signed_receipt(ticket, key), *[_receipt(ticket, key, **change) for change in ({"trade_batch_no": "OTHER-BATCH"}, {"period_start": "2026-10-01", "period_end": "2026-10-02"}, {"asset_type": "RETAIL_DATA"}, {"claims_hash": "f" * 64}, {"content_hash": "f" * 64})]]
    for receipt in candidates:
        response = client.post("/api/trust-space/connectors/receipts", headers=auth_headers["generator"], json=receipt)
        assert response.status_code == 422, response.text
    assert client.post("/api/trust-space/connectors/receipts", headers=auth_headers["retailer"], json=valid).status_code == 403
    with SessionLocal() as db:
        assert db.get(ConnectorIngestionReceipt, valid["receipt_id"]) is None
        assert db.scalar(select(func.count()).select_from(DataUpload).where(DataUpload.trade_batch_no == BINDING["trade_batch_no"])) == 0


def test_registration_failure_removes_only_new_aggregate_file(client, auth_headers, monkeypatch):
    key = Ed25519PrivateKey.generate()
    _configure_generator_node(key)
    ticket = _ticket(client, auth_headers)
    receipt = _receipt(ticket, key)
    upload_id = settlement_upload_id(SimpleNamespace(ticket_id=receipt["ticket_id"], receipt_id=receipt["receipt_id"]))
    created_paths = []
    original_project = connector_settlement.project_upload_to_asset_registry
    def fail_projection(_db, upload):
        path = connector_settlement.VAULT_DIR / (upload.data_ref.removeprefix("vault://") + ".json")
        created_paths.append(path)
        assert path.exists()
        raise RuntimeError("injected aggregate projection failure")
    monkeypatch.setattr(connector_settlement, "project_upload_to_asset_registry", fail_projection)
    with pytest.raises(RuntimeError, match="injected aggregate"):
        client.post("/api/trust-space/connectors/receipts", headers=auth_headers["generator"], json=receipt)
    assert len(created_paths) == 1 and not created_paths[0].exists()
    with SessionLocal() as db:
        assert db.get(DataUpload, upload_id) is None
        assert db.get(ConnectorIngestionReceipt, receipt["receipt_id"]) is None
    # A file from an earlier attempt is never reused or overwritten by a retry.
    path = created_paths[0]
    path.write_text('{"existing":"preserve"}', encoding="utf-8")
    monkeypatch.setattr(connector_settlement, "project_upload_to_asset_registry", original_project)
    retried = client.post("/api/trust-space/connectors/receipts", headers=auth_headers["generator"], json=receipt)
    assert retried.status_code == 201, retried.text
    assert path.read_text(encoding="utf-8") == '{"existing":"preserve"}'


def test_orphaned_aggregate_does_not_block_retry_or_change_payload_hash(client, auth_headers, monkeypatch):
    key = Ed25519PrivateKey.generate()
    _configure_generator_node(key)
    ticket = _ticket(client, auth_headers)
    receipt = _receipt(ticket, key)
    orphaned = []
    original_project = connector_settlement.project_upload_to_asset_registry
    original_unlink = Path.unlink
    def fail_after_write(_db, upload):
        orphaned.append(connector_settlement.VAULT_DIR / (upload.data_ref.removeprefix("vault://") + ".json"))
        raise RuntimeError("simulate interruption after file creation")
    def leave_orphan(path, *args, **kwargs):
        if path not in orphaned:
            return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(connector_settlement, "project_upload_to_asset_registry", fail_after_write)
    monkeypatch.setattr(Path, "unlink", leave_orphan)
    with pytest.raises(RuntimeError, match="simulate interruption"):
        client.post("/api/trust-space/connectors/receipts", headers=auth_headers["generator"], json=receipt)
    assert len(orphaned) == 1 and orphaned[0].exists()
    previous_payload = json.loads(orphaned[0].read_text(encoding="utf-8"))
    monkeypatch.setattr(connector_settlement, "project_upload_to_asset_registry", original_project)
    monkeypatch.setattr(Path, "unlink", original_unlink)
    retried = client.post("/api/trust-space/connectors/receipts", headers=auth_headers["generator"], json=receipt)
    assert retried.status_code == 201, retried.text
    with SessionLocal() as db:
        upload = db.get(DataUpload, retried.json()["settlement"]["upload_id"])
        assert LocalControlledComputeAdapter._verified_vault_payload(upload) == previous_payload
        assert upload.data_hash == sha256_json(previous_payload)
    assert orphaned[0].exists()


def test_failed_attempt_cleanup_cannot_delete_retry_committed_in_rollback_window(client, auth_headers, monkeypatch):
    key = Ed25519PrivateKey.generate()
    _configure_generator_node(key)
    receipt = _receipt(_ticket(client, auth_headers), key)
    first_paths, retry_responses = [], []
    original_project = connector_settlement.project_upload_to_asset_registry
    original_unlink = Path.unlink
    def fail_first_projection(db, upload):
        if not first_paths:
            first_paths.append(connector_settlement.VAULT_DIR / (upload.data_ref.removeprefix("vault://") + ".json"))
            raise RuntimeError("first registration failed")
        return original_project(db, upload)
    def retry_before_cleanup(path, *args, **kwargs):
        if path in first_paths and not retry_responses:
            retry_responses.append(client.post("/api/trust-space/connectors/receipts", headers=auth_headers["generator"], json=receipt))
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(connector_settlement, "project_upload_to_asset_registry", fail_first_projection)
    monkeypatch.setattr(Path, "unlink", retry_before_cleanup)
    with pytest.raises(RuntimeError, match="first registration failed"):
        client.post("/api/trust-space/connectors/receipts", headers=auth_headers["generator"], json=receipt)
    assert len(retry_responses) == 1 and retry_responses[0].status_code == 201, [response.text for response in retry_responses]
    assert not first_paths[0].exists()
    with SessionLocal() as db:
        upload = db.get(DataUpload, retry_responses[0].json()["settlement"]["upload_id"])
        assert LocalControlledComputeAdapter._verified_vault_payload(upload)["energy_mwh"] == "1000.000001"


def test_binding_migration_preserves_existing_ticket_and_is_idempotent(tmp_path):
    isolated = create_engine(f"sqlite:///{(tmp_path / 'binding-upgrade.db').as_posix()}")
    try:
        with isolated.begin() as connection:
            connection.execute(text("CREATE TABLE connector_ingestion_tickets (ticket_id TEXT PRIMARY KEY, claims_hash TEXT NOT NULL)"))
            connection.execute(text("INSERT INTO connector_ingestion_tickets VALUES ('old-ticket', 'old-hash')"))
            migration = next(item for item in MIGRATIONS if item.version == "20261106_001")
            migration.apply(connection)
            migration.apply(connection)
            assert connection.execute(text("SELECT ticket_id, claims_hash, settlement_binding_json FROM connector_ingestion_tickets")).one() == ("old-ticket", "old-hash", None)
    finally:
        isolated.dispose()


def test_real_connector_daily_inputs_complete_new_batch_settlement(client, auth_headers, monkeypatch, tmp_path):
    platform_key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(connector_ingestion, "settings", replace(connector_ingestion.settings, platform_signing_private_key=_private_text(platform_key), subject_node_browser_endpoints_json="{}"))
    canary = "RAW-ROW-CANARY-SETTLEMENT-ONLY-AT-CONNECTOR"
    uploads = []
    for role, values in (("generator", ("500.000001", "510.000002")), ("retailer", ("490.000001", "510.000002"))):
        key = Ed25519PrivateKey.generate()
        org_id = f"org-{role}-t01"
        connector_id = f"local-node-{org_id}"
        with SessionLocal() as db:
            node = db.scalar(select(LocalSubjectNode).where(LocalSubjectNode.org_id == org_id))
            node.endpoint_ref = f"https://{role}.example.test"
            node.public_key = _public_text(key)
            db.commit()
        ticket = _ticket(client, auth_headers, role=role)["ticket"]
        connector_db = tmp_path / f"{role}.db"
        for name, value in {"ENERGY_DOMAIN": "electricity", "CONNECTOR_ID": connector_id, "ORGANIZATION_ID": org_id, "CONNECTOR_DATABASE_PATH": str(connector_db), "CONNECTOR_SIGNING_PRIVATE_KEY": _private_text(key), "PLATFORM_SIGNING_PUBLIC_KEY": _public_text(platform_key), "SEED_DEMO_DATA": "false"}.items():
            monkeypatch.setenv(name, value)
        module_name = f"hiddenchain_settlement_e2e_{role}"
        module = _load_connector_module(module_name)
        try:
            with TestClient(module.app) as connector:
                raw = f"record_date,value,organization,unit\n2026-09-01,{values[0]},{canary},MWh\n2026-09-02,{values[1]},{canary},MWh\n".encode()
                uploaded = connector.post("/ingest", data={"ticket": json.dumps(ticket)}, files={"file": ("daily.csv", raw, "text/csv")})
                assert uploaded.status_code == 201, uploaded.text
                assert canary not in uploaded.text
                registered = client.post("/api/trust-space/connectors/receipts", headers=auth_headers[role], json=uploaded.json())
                assert registered.status_code == 201, registered.text
                uploads.append(registered.json()["settlement"]["upload_id"])
        finally:
            for name in list(sys.modules):
                if name == module_name or name.startswith(module_name + "."):
                    sys.modules.pop(name, None)
        with sqlite3.connect(connector_db) as connection:
            assert connection.execute("SELECT count(*) FROM version_records WHERE organization = ?", (canary,)).fetchone()[0] == 2
    assert canary.encode() not in Path(str(engine.url.database)).read_bytes()
    for path in connector_settlement.VAULT_DIR.rglob("*.json"):
        assert canary not in path.read_text(encoding="utf-8")
    created = client.post("/api/settlement/tasks", headers=auth_headers["exchange"], json={**BINDING, "task_name": "连接器新批次全链路", "rule_id": "rule-settlement-v1", "participants": [{"org_id": "org-generator-t01", "role_in_task": "GENERATOR"}, {"org_id": "org-retailer-t01", "role_in_task": "RETAILER"}]})
    assert created.status_code == 201, created.text
    assert created.json()["readiness"]["preflight_passed"]
    task_id = created.json()["task_id"]
    url = f"/api/settlement/tasks/{task_id}"
    def headers(role):
        return {**auth_headers[role], "If-Match": client.get(url, headers=auth_headers[role]).headers["etag"]}
    result = client.post(url + "/run", headers=headers("exchange"), json={"compute_mode": "LOCAL_CONTROLLED", "algorithm_code": "CONTROLLED_SETTLEMENT_V1"})
    assert result.status_code == 200, result.text
    body = result.json()
    with SessionLocal() as db:
        params = db.get(SettlementRule, "rule-settlement-v1").parameters_json
    energy = Decimal("1000.000003")
    penalty = max(Decimal("10") - Decimal(str(params["deviation_threshold_mwh"])), Decimal(0)) * Decimal(str(params["deviation_penalty_rate"]))
    expected_amount = (energy * (Decimal(str(params["contract_price"])) - Decimal(str(params["service_fee_rate"]))) - penalty).quantize(Decimal("0.01"))
    assert Decimal(str(body["compute_job"]["result_json"]["payable_amount_yuan"])) == expected_amount
    own = {item["org_id"]: item["result_id"] for item in body["results"] if item["result_scope"] == "ORG"}
    first = client.post(f"/api/results/{own['org-generator-t01']}/confirm", headers=headers("generator"), json={"decision": "APPROVE", "opinion": "确认新数据"})
    assert first.status_code == 200, first.text
    audit = client.post(f"/api/audit/reports/{body['report']['report_id']}/decision", headers=auth_headers["regulator"], json={"decision": "APPROVE", "opinion": "复核通过"})
    assert audit.status_code == 200, audit.text
    final = client.post(f"/api/results/{own['org-retailer-t01']}/confirm", headers=headers("retailer"), json={"decision": "APPROVE", "opinion": "确认新数据"})
    assert final.status_code == 200, final.text
    assert final.json()["task"]["ttc"]["state"] == "ARCHIVED"
