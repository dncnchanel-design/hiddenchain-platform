from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import LocalSubjectNode, PrivacyComputeJob, SettlementResult, SettlementTask
from app.services.adapters import LocalControlledComputeAdapter, PandapowerGridAdapter
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_connector_ingestion import _public_text, _signed_receipt
from test_connector_settlement_ingress import BINDING, _summary, _ticket


def _grid_passes(monkeypatch):
    # Isolate serialization from physical-grid limits in these precision tests.
    monkeypatch.setattr(PandapowerGridAdapter, "check", lambda self, **kwargs: {"passed": True, "adapter": self.code, "network_version": self.network_version})


def test_amount_that_loses_cents_is_rejected_before_returning_official_result(monkeypatch):
    _grid_passes(monkeypatch)
    monkeypatch.setattr(LocalControlledComputeAdapter, "_verified_vault_payload", staticmethod(lambda upload: {"energy_mwh": "999999999999.99"}))
    exact = (Decimal("999999999999.99") * Decimal("416.8")).quantize(Decimal("0.01"))
    assert exact == Decimal("416799999999995.83")
    assert Decimal(str(float(exact))) != exact
    with pytest.raises(ValueError, match="精度"):
        LocalControlledComputeAdapter().run_settlement(generator_upload=SimpleNamespace(commitment="generator"), retailer_upload=SimpleNamespace(commitment="retailer"), rule_package={"rule_hash": "rule", "parameters": {"contract_price": 420, "deviation_threshold_mwh": 0, "deviation_penalty_rate": 0, "service_fee_rate": 3.2, "rounding": 2}}, capsule_id="numeric-boundary")


def test_precision_failure_persists_failed_attempt_without_official_results(client, auth_headers, monkeypatch):
    _grid_passes(monkeypatch)
    for role, resource, asset in (("generator", "generation", "GENERATION_DATA"), ("retailer", "supply", "RETAIL_DATA")):
        key = Ed25519PrivateKey.generate()
        with SessionLocal() as db:
            node = db.scalar(select(LocalSubjectNode).where(LocalSubjectNode.org_id == f"org-{role}-t01"))
            node.public_key = _public_text(key)
            node.endpoint_ref = f"https://{role}.example.test"
            db.commit()
        ticket = _ticket(client, auth_headers, role)
        receipt = _signed_receipt(ticket, key, receipt_id=f"receipt-{role}-precision", record_count=2, local_ref=f"connector://local-node-org-{role}-t01/{resource}/versions/1", settlement_summary=_summary(ticket, asset_type=asset, energy_mwh="999999999999.99"))
        registered = client.post("/api/trust-space/connectors/receipts", headers=auth_headers[role], json=receipt)
        assert registered.status_code == 201, registered.text
    created = client.post("/api/settlement/tasks", headers=auth_headers["exchange"], json={**BINDING, "task_name": "金额精度门禁", "rule_id": "rule-settlement-v1", "participants": [{"org_id": "org-generator-t01", "role_in_task": "GENERATOR"}, {"org_id": "org-retailer-t01", "role_in_task": "RETAILER"}]})
    assert created.status_code == 201, created.text
    task_id = created.json()["task_id"]
    response = client.post(f"/api/settlement/tasks/{task_id}/run", headers={**auth_headers["exchange"], "If-Match": created.headers["etag"]}, json={"compute_mode": "LOCAL_CONTROLLED", "algorithm_code": "CONTROLLED_SETTLEMENT_V1"})
    assert response.status_code == 400, response.text
    assert "精度" in response.text
    with SessionLocal() as db:
        task = db.get(SettlementTask, task_id)
        assert task.ttc_state == "FAILED"
        assert db.scalar(select(func.count()).select_from(SettlementResult).where(SettlementResult.task_id == task_id)) == 0
        assert db.scalar(select(func.count()).select_from(PrivacyComputeJob).where(PrivacyComputeJob.task_id == task_id, PrivacyComputeJob.status == "SUCCESS")) == 0
