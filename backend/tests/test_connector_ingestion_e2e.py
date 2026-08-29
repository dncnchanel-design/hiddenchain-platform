from __future__ import annotations

import base64
import importlib.util
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal, engine
from app.models import ConnectorIngestionReceipt, LocalSubjectNode


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONNECTOR_MAIN = PROJECT_ROOT / "connector" / "app" / "main.py"


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


def _load_connector_module(name: str):
    spec = importlib.util.spec_from_file_location(name, CONNECTOR_MAIN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_demo_accepts_loopback_subject_node_endpoint(monkeypatch):
    from app.routers import connector_ingestion

    node = SimpleNamespace(node_id="node-exchange", org_id="org-exchange-t01")
    db = SimpleNamespace(scalar=lambda _statement: node)
    monkeypatch.setattr(
        connector_ingestion,
        "subject_node_config",
        lambda _db, _org_id: {"endpoint": "http://127.0.0.1:8107"},
    )
    monkeypatch.setattr(
        connector_ingestion,
        "settings",
        replace(
            connector_ingestion.settings,
            app_env="demo",
            subject_node_browser_endpoints_json=(
                '{"org-exchange-t01":"http://127.0.0.1:8107"}'
            ),
        ),
    )

    active_node, config = connector_ingestion._active_node(db, "org-exchange-t01")

    assert active_node is node
    assert config["endpoint"] == "http://127.0.0.1:8107"
    assert config["browser_endpoint"] == "http://127.0.0.1:8107"


def test_browser_direct_canary_stays_in_connector_and_central_registers_only_receipt(
    client,
    auth_headers,
    monkeypatch,
    tmp_path,
):
    from app.routers import connector_ingestion

    platform_key = Ed25519PrivateKey.generate()
    connector_key = Ed25519PrivateKey.generate()
    connector_db = tmp_path / "generator-connector.db"
    connector_id = "local-node-org-generator-t01"
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
    monkeypatch.setattr(
        connector_ingestion,
        "settings",
        replace(
            connector_ingestion.settings,
            platform_signing_private_key=_private_text(platform_key),
            subject_node_browser_endpoints_json="{}",
        ),
    )

    ticket_response = client.post(
        "/api/trust-space/connectors/tickets",
        headers=auth_headers["generator"],
        json={"resource_id": "generation", "classification": "L3"},
    )
    assert ticket_response.status_code == 201, ticket_response.text
    ticket = ticket_response.json()["ticket"]

    monkeypatch.setenv("ENERGY_DOMAIN", "electricity")
    monkeypatch.setenv("CONNECTOR_ID", connector_id)
    monkeypatch.setenv("CONNECTOR_NAME", "发电企业本地连接器")
    monkeypatch.setenv("ORGANIZATION_ID", "org-generator-t01")
    monkeypatch.setenv("CONNECTOR_DATABASE_PATH", str(connector_db))
    monkeypatch.setenv("CONNECTOR_SIGNING_PRIVATE_KEY", _private_text(connector_key))
    monkeypatch.setenv("PLATFORM_SIGNING_PUBLIC_KEY", _public_text(platform_key))
    monkeypatch.delenv("ALLOW_DEMO_KEY_REGISTRATION", raising=False)
    module_name = "hiddenchain_connector_ingestion_e2e"
    connector_module = _load_connector_module(module_name)
    canary = "RAW-CANARY-NEVER-CENTRAL-20260829-E2E"
    csv_bytes = (
        "record_date,value,region,organization,unit\n"
        f"2026-08-27,10,齐鲁片区,{canary},MWh\n"
        f"2026-08-28,20,齐鲁片区,{canary},MWh\n"
        f"2026-08-29,30,齐鲁片区,{canary},MWh\n"
    ).encode("utf-8")
    try:
        with TestClient(connector_module.app) as connector_client:
            uploaded = connector_client.post(
                "/ingest",
                data={"ticket": connector_module.json.dumps(ticket, ensure_ascii=False)},
                files={"file": ("generation.csv", csv_bytes, "text/csv")},
            )
            assert uploaded.status_code == 201, uploaded.text
            receipt = uploaded.json()
            assert receipt["local_ref"] == (
                f"connector://{connector_id}/generation/versions/1"
            )
            assert canary not in uploaded.text
    finally:
        sys.modules.pop(module_name, None)

    registered = client.post(
        "/api/trust-space/connectors/receipts",
        headers=auth_headers["generator"],
        json=receipt,
    )
    assert registered.status_code == 201, registered.text
    assert registered.json()["raw_data_centrally_stored"] is False
    with SessionLocal() as db:
        central_receipt = db.get(ConnectorIngestionReceipt, receipt["receipt_id"])
        assert central_receipt is not None
        assert canary not in str(central_receipt.signed_payload_json)
    with sqlite3.connect(connector_db) as local_db:
        assert local_db.execute(
            "SELECT COUNT(*) FROM version_records WHERE organization = ?",
            (canary,),
        ).fetchone()[0] == 3
    central_database = Path(str(engine.url.database))
    assert canary.encode("utf-8") not in central_database.read_bytes()
